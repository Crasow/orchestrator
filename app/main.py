import re
import os
import httpx
import logging
from fastapi import FastAPI, Request, Response, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from contextlib import asynccontextmanager
import asyncio

# Импортируем наши новые модули
from app.config import settings, ensure_directories
from app.services.rotators.vertex import VertexRotator
from app.services.rotators.gemini import GeminiRotator
from app.security.auth import auth_manager, get_current_admin

# --- LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("orchestrator")

# --- STATE ---
vertex_rotator = VertexRotator()
gemini_rotator = GeminiRotator()
http_client: httpx.AsyncClient = None  # type: ignore

# Регулярка для подмены Project ID в Vertex
PROJECT_PATH_REGEX = re.compile(r"(v1/projects/)([^/]+)(/locations.*)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client
    # Ensure credential directories exist before starting
    ensure_directories()
    
    http_client = httpx.AsyncClient(
        timeout=120.0, limits=httpx.Limits(max_keepalive_connections=50)
    )
    logger.info("Orchestrator is ready")
    yield
    await http_client.aclose()
    logger.info("Orchestrator stopped")


app = FastAPI(
    lifespan=lifespan,
    title="AI Services Orchestrator",
    description="Secure proxy for Google AI services",
    docs_url="/docs"
    if os.environ.get("ENABLE_DOCS", "false").lower() == "true"
    else None,
)


# --- ADMIN ENDPOINTS ---
@app.post("/admin/login")
async def admin_login(request: Request):
    """Вход в админ-панель"""
    try:
        data = await request.json()
        username = data.get("username")
        password = data.get("password")
        client_ip = getattr(request.client, "host", "unknown")

        if not username or not password:
            raise HTTPException(
                status_code=400, detail="Username and password required"
            )

        token = auth_manager.authenticate_admin(username, password, client_ip)
        return {"access_token": token, "token_type": "bearer"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(status_code=500, detail="Authentication failed")


@app.post("/admin/reload")
async def admin_reload(
    request: Request, current_admin: dict = Depends(get_current_admin)
):
    """Горячая перезагрузка ключей без остановки сервиса"""
    try:
        vertex_rotator.reload()
        gemini_rotator.reload()

        # Логируем действие админа
        logger.info(f"Admin {current_admin['sub']} reloaded credentials")

        return {
            "status": "reloaded",
            "vertex_count": len(vertex_rotator._pool),
            "gemini_count": len(gemini_rotator._keys),
        }
    except Exception as e:
        logger.error(f"Reload failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to reload credentials")


@app.get("/admin/status")
async def admin_status(current_admin: dict = Depends(get_current_admin)):
    """Статус системы"""
    try:
        from app.security.audit import security_auditor

        suspicious = security_auditor.get_suspicious_activity(hours=1)

        return {
            "status": "operational",
            "vertex_credentials": len(vertex_rotator._pool),
            "gemini_keys": len(gemini_rotator._keys),
            "suspicious_activity": suspicious,
            "admin_user": current_admin["sub"],
        }
    except Exception as e:
        logger.error(f"Status check failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to get status")


# --- PROXY LOGIC ---
@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_gateway(request: Request, path: str):
    client_ip = getattr(request.client, "host", "unknown")

    # Проверка IP-адреса по белому списку
    if settings.security.allowed_client_ips and client_ip not in settings.security.allowed_client_ips:
        logger.warning(f"Unauthorized access attempt from IP: {client_ip}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Your IP address is not whitelisted.",
        )

    # 1. Определяем провайдера по URL
    # Gemini Studio обычно содержит /models/gemini... и НЕ содержит /projects/
    # Либо явно путь /v1beta/
    is_gemini = "v1beta" in path or ("models/" in path and "projects/" not in path)

    body = await request.body()

    # Заголовки: копируем и чистим
    headers = dict(request.headers)
    for h in ["host", "content-length", "authorization", "x-goog-api-key"]:
        headers.pop(h, None)

    attempts = 0
    while attempts < settings.services.max_retries:
        attempts += 1

        try:
            # --- СТРАТЕГИЯ ВЫБОРА ---
            if is_gemini:
                upstream_base = settings.services.gemini_base_url
                target_path = path

                api_key = gemini_rotator.get_next_key()
                if not api_key:
                    return Response("No Gemini keys available", status_code=503)

                # Gemini auth через query param
                params = dict(request.query_params)
                params["key"] = api_key

                # Для логов (скрываем ключ)
                log_auth = f"Key ...{api_key[-4:]}"

            else:
                # Vertex AI
                upstream_base = settings.services.vertex_base_url

                cred = (
                    vertex_rotator.get_next_credential()
                )  # Может выбросить RuntimeError если пусто
                token = await vertex_rotator.get_token(cred)

                # Подмена Project ID
                match = PROJECT_PATH_REGEX.match(path)
                target_path = (
                    f"{match.group(1)}{cred.project_id}{match.group(3)}"
                    if match
                    else path
                )

                # Vertex auth через Header
                headers["Authorization"] = f"Bearer {token}"
                headers["X-Goog-User-Project"] = cred.project_id

                params = dict(request.query_params)
                log_auth = f"Project {cred.project_id}"

            # --- ОТПРАВКА ---
            url = f"{upstream_base}/{target_path}"
            logger.info(f"Attempt {attempts} [{log_auth}] -> {url}")

            req = http_client.build_request(
                request.method, url, content=body, headers=headers, params=params
            )

            resp = await http_client.send(req, stream=True)

            # --- ОБРАБОТКА ОШИБОК (RETRY) ---
            # 429 = Лимиты, 403 = Проблемы с доступом/оплатой (иногда)
            if resp.status_code in [429, 403, 503]:
                err_body = await resp.aread()
                logger.warning(f"Provider Error {resp.status_code}: {err_body[:200]}")
                continue  # Идем на следующий круг (берем новый ключ)

            # --- УСПЕХ ---
            return StreamingResponse(
                resp.aiter_bytes(),
                status_code=resp.status_code,
                headers={
                    k: v
                    for k, v in resp.headers.items()
                    if k.lower()
                    not in ("content-encoding", "content-length", "transfer-encoding")
                },
            )

        except Exception as e:
            logger.error(f"Proxy error: {e}")
            # Небольшая пауза перед ретраем, чтобы не дудосить себя
            await asyncio.sleep(0.5)
            continue

    return Response("All backends exhausted or unavailable", status_code=503)
