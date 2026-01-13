import os
import re
import json
import httpx
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
from rotator import CredentialRotator


# --- КОНФИГУРАЦИЯ ---
UPSTREAM_BASE = "https://us-central1-aiplatform.googleapis.com"

if os.path.exists("/app/credentials"):
    CREDS_DIR = "/app/credentials"  # Путь для Docker
else:
    CREDS_DIR = "credentials"  # Путь для локального запуска (Windows/Mac)

MAX_RETRIES = 10

# --- ЛОГИРОВАНИЕ ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("orchestrator")

# --- ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ---
rotator: CredentialRotator = None
client: httpx.AsyncClient = None

# Кэш для LRO: Operation Name -> Project ID
# Пример: {"projects/123/.../operations/abc": "project-id-123"}
# TODO: Move it to Redis
lro_cache: dict[str, str] = {}

# Регулярка для поиска project_id в URL
# Vertex URL: /v1/projects/{PROJECT_ID}/locations/...
PROJECT_PATH_REGEX = re.compile(r"(v1/projects/)([^/]+)(/locations.*)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global rotator, client
    # Инициализация при старте
    try:
        rotator = CredentialRotator(CREDS_DIR)
        client = httpx.AsyncClient(timeout=120.0)
        logger.info("[INIT] Orchestrator started successfully")
    except Exception as e:
        logger.critical(f"[INIT] Failed to start: {e}")
        raise e

    yield

    # Очистка при остановке
    if client:
        await client.aclose()
        logger.info("[SHUTDOWN] HTTP Client closed")


app = FastAPI(lifespan=lifespan)


async def stream_generator(response):
    async for chunk in response.aiter_bytes():
        yield chunk


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_request(request: Request, path: str):
    # 1. Читаем тело запроса (нужно для повторной отправки при ретраях)
    body = await request.body()

    # 2. Подготовка заголовков (убираем хостовые, оставляем контентные)
    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("content-length", None)  # httpx сам пересчитает
    headers.pop("authorization", None)  # Мы заменим его своим

    # --- LRO LOGIC (Routing) ---
    # Пытаемся понять, нужно ли форсировать конкретный проект
    target_project_id = None

    # Если это поллинг операции (:fetchPredictOperation), ищем operationName в теле
    if "fetchPredictOperation" in path and request.method == "POST":
        try:
            body_json = json.loads(body)
            op_name = body_json.get("operationName")
            if op_name and op_name in lro_cache:
                target_project_id = lro_cache[op_name]
                logger.info(
                    f"[LRO] Routing fetch request for {op_name} -> {target_project_id}"
                )
        except Exception:
            pass  # Если не смогли распарсить JSON, идем по стандартному пути

    attempts = 0

    while attempts < MAX_RETRIES:
        attempts += 1

        # 3. Выбор креденшила
        cred_wrapper = None

        # Если есть target_project_id (из LRO кэша), пробуем взять его
        if target_project_id:
            cred_wrapper = rotator.get_credential_by_project_id(target_project_id)
            if not cred_wrapper:
                # Если вдруг такого проекта нет, сбрасываем форсирование
                logger.warning(
                    f"[LRO] Target project {target_project_id} not found in pool. Fallback to rotation."
                )
                target_project_id = None

        # Если форсирования нет или проект не найден — берем следующий по кругу
        if not cred_wrapper:
            cred_wrapper = rotator.get_next_credential()

        try:
            # 4. Получение токена (асинхронно)
            token = await rotator.get_token_for_credential_async(cred_wrapper)
        except Exception as e:
            logger.warning(f"[TOKEN] Refresh failed for {cred_wrapper.project_id}: {e}")
            # Если это была форсированная попытка — прерываем цикл, т.к. другой ключ все равно не подойдет
            if target_project_id:
                return Response(content="Target credential failed", status_code=503)
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

        logger.info(
            f"[PROXY] {attempts}/{MAX_RETRIES} via {cred_wrapper.project_id} -> {target_url}"
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

            # 7. Проверка статуса
            # 429 - Too Many Requests (Quota limit)
            # 402 - Payment Required (Quota limit / Billing issue)
            if rp_resp.status_code in [429, 402]:
                logger.warning(f"[QUOTA] {cred_wrapper.project_id} exhausted ({rp_resp.status_code}). Switching...")
                await rp_resp.aclose()  # Закрываем соединение перед следующей попыткой
                # Если это был LRO-запрос к конкретному проекту, мы не можем "свитчнуться",
                # так как операция живет только там. Придется отдать ошибку клиенту.
                if target_project_id:
                    return Response(
                        content="Operation host quota exhausted", status_code=429
                    )
                continue
            
            # --- LRO LOGIC (Caching) ---
            # Если это успешный запуск LRO (:predictLongRunning), запоминаем, где он запустился
            if "predictLongRunning" in path and rp_resp.status_code == 200:
                # Нам нужно прочитать ответ целиком, чтобы достать имя операции
                resp_content = await rp_resp.aread()

                try:
                    resp_json = json.loads(resp_content)
                    # Vertex AI возвращает Operation resource, где поле "name" - это ID операции
                    # Пример: "projects/123/locations/.../operations/987"
                    op_name = resp_json.get("name")
                    if op_name:
                        lro_cache[op_name] = cred_wrapper.project_id
                        logger.info(
                            f"[LRO] Registered operation {op_name} on {cred_wrapper.project_id}"
                        )
                except Exception as e:
                    logger.error(f"[LRO] Failed to parse response body: {e}")

                # Возвращаем обычный Response, так как поток мы уже вычитали
                return Response(
                    content=resp_content,
                    status_code=rp_resp.status_code,
                    headers={
                        k: v
                        for k, v in rp_resp.headers.items()
                        if k.lower()
                        not in (
                            "content-encoding",
                            "content-length",
                            "transfer-encoding",
                        )
                    },
                )
                
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
            logger.error(f"[NET] Error via {cred_wrapper.project_id}: {exc}")
            continue

    # Если мы вышли из цикла, значит все попытки провалились
    return Response(
        content="All backend pools exhausted or unavailable", status_code=503
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
