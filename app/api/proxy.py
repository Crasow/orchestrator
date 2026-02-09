import re
import asyncio
import logging
from fastapi import APIRouter, Request, Response, HTTPException, status
from fastapi.responses import StreamingResponse
from app.config import settings
from app.core import state

logger = logging.getLogger(__name__)
router = APIRouter()

# Регулярка для подмены Project ID в Vertex
# Поддерживает v1, v1beta1, v2 и т.д.
PROJECT_PATH_REGEX = re.compile(r"(v1(?:beta\d+)?/projects/)([^/]+)(/locations.*)")

@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_gateway(request: Request, path: str):
    client_ip = getattr(request.client, "host", "unknown")

    # Проверка IP-адреса по белому списку
    if settings.security.allowed_client_ips and settings.security.allowed_client_ips == ["*"]:
        pass
    elif settings.security.allowed_client_ips and client_ip not in settings.security.allowed_client_ips:
        logger.warning(f"Unauthorized access attempt from IP: {client_ip}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Your IP address is not whitelisted.",
        )


    # 1. Определяем провайдера по URL
    is_gemini = "projects/" not in path

    body = await request.body()

    # Заголовки: копируем и чистим
    headers = dict(request.headers)
    for h in ["host", "content-length", "authorization", "x-goog-api-key"]:
        headers.pop(h, None)

    attempts = 0
    while attempts < settings.services.max_retries:
        attempts += 1

        try:
            if is_gemini:
                upstream_base = settings.services.gemini_base_url
                target_path = path

                api_key = state.gemini_rotator.get_next_key()
                if not api_key:
                    return Response("No Gemini keys available", status_code=503)

                params = dict(request.query_params)
                params["key"] = api_key
                log_auth = f"Key ...{api_key[-4:]}"
            else:
                upstream_base = settings.services.vertex_base_url
                cred = state.vertex_rotator.get_next_credential()
                token = await state.vertex_rotator.get_token(cred)

                match = PROJECT_PATH_REGEX.match(path)
                target_path = (
                    f"{match.group(1)}{cred.project_id}{match.group(3)}"
                    if match
                    else path
                )

                headers["Authorization"] = f"Bearer {token}"
                headers["X-Goog-User-Project"] = cred.project_id
                params = dict(request.query_params)
                log_auth = f"Project {cred.project_id}"

            url = f"{upstream_base}/{target_path}"
            logger.info(f"Attempt {attempts} [{log_auth}] -> {url}")

            if state.http_client is None:
                raise HTTPException(status_code=503, detail="Service is not ready")


            req = state.http_client.build_request(
                request.method, url, content=body, headers=headers, params=params
            )
            resp = await state.http_client.send(req, stream=True)

            if resp.status_code in [429, 403, 503]:
                err_body = await resp.aread()
                logger.warning(f"Provider Error {resp.status_code}: {err_body[:200]}")
                continue

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
            await asyncio.sleep(0.5)
            continue

    return Response("All backends exhausted or unavailable", status_code=503)
