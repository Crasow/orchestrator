import re
import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
from rotator import CredentialRotator
from random import randint

# Конфигурация
UPSTREAM_BASE = "https://us-central1-aiplatform.googleapis.com"
CREDS_DIR = "./credentials"

app = FastAPI()
rotator = CredentialRotator(CREDS_DIR)
client = httpx.AsyncClient(timeout=120.0)  # Таймаут побольше для видео

MAX_RETRIES = len(rotator._pool) # Сколько ключей перебрать, прежде чем сдаться


# Регулярка для поиска project_id в URL
# Vertex URL: /v1/projects/{PROJECT_ID}/locations/...
PROJECT_PATH_REGEX = re.compile(r"(v1/projects/)([^/]+)(/locations.*)")


async def stream_generator(response):
    async for chunk in response.aiter_bytes():
        yield chunk


@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    # Простейший middleware для логирования, если нужно
    response = await call_next(request)
    return response


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_request(request: Request, path: str):
    # 1. Читаем тело запроса (нужно для повторной отправки при ретраях)
    body = await request.body()

    # 2. Подготовка заголовков (убираем хостовые, оставляем контентные)
    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("content-length", None)  # httpx сам пересчитает
    headers.pop("authorization", None)  # Мы заменим его своим

    attempts = 0
    last_error_response = None

    while attempts < MAX_RETRIES:
        attempts += 1

        # 3. Берем следующий аккаунт из пула
        cred_wrapper = rotator.get_next_credential()

        try:
            # 4. Получаем актуальный Bearer токен
            token = rotator.get_token_for_credential(cred_wrapper)
        except Exception as e:
            print(f"[WARN] Token refresh failed for {cred_wrapper.project_id}: {e}")
            continue

        # 5. Подмена Project ID в URL
        # Входящий URL от клиента может содержать project_id из конфига клиента (mixora-474310)
        # Нам нужно заменить его на project_id текущего ключа (cred_wrapper.project_id)
        match = PROJECT_PATH_REGEX.match(path)
        if match:
            # path превращается в v1/projects/{NEW_ID}/locations/...
            new_path = f"{match.group(1)}{cred_wrapper.project_id}{match.group(3)}"
        else:
            # Если URL не содержит projects (редко для Vertex), оставляем как есть
            new_path = path

        target_url = f"{UPSTREAM_BASE}/{new_path}"

        # Подстановка заголовков авторизации и квоты
        current_headers = headers.copy()
        current_headers["Authorization"] = f"Bearer {token}"
        # Важно: X-Goog-User-Project должен совпадать с проектом токена
        current_headers["X-Goog-User-Project"] = cred_wrapper.project_id

        # Обработка Query Params
        params = dict(request.query_params)

        print(
            f"[PROXY] Attempt {attempts}/{MAX_RETRIES} via {cred_wrapper.project_id} -> {target_url}"
        )

        try:
            # 6. Отправка запроса в Google
            rp_req = client.build_request(
                request.method,
                target_url,
                headers=current_headers,
                content=body,
                params=params,
            )
            rp_resp = await client.send(rp_req, stream=True)
            
            #TODO: Remove this after testing
            rand_int = randint(0, 10)
            if rand_int == 0:
                rp_resp.status_code = 429

            # 7. Проверка статуса
            # 429 - Too Many Requests (Quota limit)
            # 402 - Payment Required (Quota limit / Billing issue)
            if rp_resp.status_code in [429, 402]:
                print(
                    f"[FAIL] {cred_wrapper.project_id} exhausted (Status {rp_resp.status_code}). Switching..."
                )
                await rp_resp.aclose()  # Закрываем соединение перед следующей попыткой
                continue  # Идем на следующий круг цикла (берем новый ключ)

            # Если успех (200) или ошибка клиента (400) или сервера (500) - возвращаем как есть
            # (Ретрай 500-х ошибок - спорный момент, обычно проксируем)
            return StreamingResponse(
                stream_generator(rp_resp),
                status_code=rp_resp.status_code,
                headers={
                    k: v
                    for k, v in rp_resp.headers.items()
                    if k.lower()
                    not in ("content-encoding", "content-length", "transfer-encoding")
                },
            )

        except httpx.RequestError as exc:
            print(
                f"[ERR] Network error connecting to Google via {cred_wrapper.project_id}: {exc}"
            )
            continue

    # Если мы вышли из цикла, значит все попытки провалились
    return Response(
        content="All backend pools exhausted or unavailable", status_code=503
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
