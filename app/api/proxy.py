import re
import json
import asyncio
import logging
import time
from typing import AsyncIterator

from fastapi import APIRouter, Request, Response, HTTPException, status
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from app.config import settings
from app.core import state
from app.services import statistics

logger = logging.getLogger(__name__)
router = APIRouter()

PROJECT_PATH_REGEX = re.compile(r"(v1(?:beta\d+)?/projects/)([^/]+)(/locations.*)")


def _get_client_ip(request: Request) -> str:
    """Extract real client IP, respecting X-Forwarded-For behind a trusted proxy."""
    if settings.security.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # First IP in the chain is the original client
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()
    return getattr(request.client, "host", "unknown")


def _extract_action(path: str) -> str | None:
    """Extract action from URL like 'models/gemini-pro:generateContent' -> 'generateContent'."""
    parts = path.split("/")
    for part in reversed(parts):
        if ":" in part:
            return part.split(":", 1)[1]
    return None


def _extract_model(path: str, is_gemini: bool) -> str:
    """Extract model name from URL path."""
    parts = path.split("/")
    if "models" in parts:
        try:
            idx = parts.index("models") + 1
            if idx < len(parts):
                return parts[idx].split(":")[0] if is_gemini else parts[idx]
        except (ValueError, IndexError):
            pass
    return "unknown"


def _parse_usage_metadata(body: bytes) -> dict:
    """Parse usageMetadata from response JSON. Works for both single and streaming responses."""
    result = {"prompt_tokens": None, "candidates_tokens": None, "total_tokens": None}
    try:
        text = body.decode("utf-8", errors="replace")
        # For streaming responses, the body is a JSON array of objects
        # The last chunk usually contains usageMetadata
        # Try parsing as single JSON first
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON objects in the stream (newline-delimited or array)
            # Look for the last usageMetadata occurrence
            data = None
            # Try parsing as JSON array
            if text.strip().startswith("["):
                try:
                    items = json.loads(text)
                    if isinstance(items, list) and items:
                        data = items[-1]
                except json.JSONDecodeError:
                    pass
            if data is None:
                return result

        # Navigate to usageMetadata
        usage = None
        if isinstance(data, dict):
            usage = data.get("usageMetadata")
        elif isinstance(data, list) and data:
            for item in reversed(data):
                if isinstance(item, dict) and "usageMetadata" in item:
                    usage = item["usageMetadata"]
                    break

        if usage:
            result["prompt_tokens"] = usage.get("promptTokenCount")
            result["candidates_tokens"] = usage.get("candidatesTokenCount")
            result["total_tokens"] = usage.get("totalTokenCount")
    except Exception:
        pass
    return result


def _safe_parse_json(body: bytes) -> dict | None:
    """Try to parse body as JSON, return None if fails."""
    try:
        return json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


async def _record_stats(
    provider: str,
    model: str,
    key_id: str,
    status_code: int,
    latency_ms: int,
    action: str | None,
    http_method: str,
    url_path: str,
    client_ip: str | None,
    user_agent: str | None,
    attempt_count: int,
    request_body: bytes | None,
    response_body: bytes | None,
    is_error: bool,
    error_detail: str | None,
):
    """Background task to record request stats to DB."""
    svc = statistics.stats_service
    if svc is None:
        return

    # Parse tokens from response
    tokens = {"prompt_tokens": None, "candidates_tokens": None, "total_tokens": None}
    if response_body:
        tokens = _parse_usage_metadata(response_body)

    # Parse request/response as JSON for storage (if enabled)
    req_json = None
    resp_json = None
    if settings.services.store_request_bodies:
        req_json = _safe_parse_json(request_body) if request_body else None
        resp_json = _safe_parse_json(response_body) if response_body else None

    await svc.record_request(
        provider=provider,
        model=model,
        key_id=key_id,
        status_code=status_code,
        latency_ms=latency_ms,
        action=action,
        http_method=http_method,
        url_path=url_path,
        client_ip=client_ip,
        user_agent=user_agent,
        attempt_count=attempt_count,
        prompt_tokens=tokens["prompt_tokens"],
        candidates_tokens=tokens["candidates_tokens"],
        total_tokens=tokens["total_tokens"],
        request_body=req_json,
        response_body=resp_json,
        is_error=is_error,
        error_detail=error_detail,
        request_size=len(request_body) if request_body else None,
        response_size=len(response_body) if response_body else None,
    )


def _check_ip_access(client_ip: str):
    """Raise 403 if client IP is not in the whitelist."""
    allowed = settings.security.allowed_client_ips
    if allowed and allowed != ["*"] and client_ip not in allowed:
        logger.warning(f"Unauthorized access attempt from IP: {client_ip}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Your IP address is not whitelisted.",
        )


@router.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
@router.api_route("/v1beta/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_gateway(request: Request, path: str):
    # Reconstruct the full API path (v1/... or v1beta/...)
    full_path = request.url.path.lstrip("/")

    client_ip = _get_client_ip(request)
    _check_ip_access(client_ip)

    is_gemini = "projects/" not in full_path
    provider = "gemini" if is_gemini else "vertex"
    model = _extract_model(full_path, is_gemini)
    action = _extract_action(full_path)
    is_streaming = action == "streamGenerateContent"
    user_agent = request.headers.get("user-agent")

    body = await request.body()

    # Allowlist: only forward safe headers to upstream
    _ALLOWED_HEADERS = {
        "content-type", "accept", "accept-encoding", "accept-language",
        "user-agent", "x-goog-user-project",
    }
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() in _ALLOWED_HEADERS
    }

    start_time = time.time()
    attempts = 0
    final_status = 503
    final_key_id = "unknown"
    final_error = None

    while attempts < settings.services.max_retries:
        attempts += 1
        key_id = "unknown"

        try:
            if is_gemini:
                upstream_base = settings.services.gemini_base_url
                target_path = full_path

                api_key = state.gemini_rotator.get_next_key()
                if not api_key:
                    latency_ms = int((time.time() - start_time) * 1000)
                    bg = BackgroundTask(
                        _record_stats,
                        provider=provider, model=model, key_id="system",
                        status_code=503, latency_ms=latency_ms, action=action,
                        http_method=request.method, url_path=full_path,
                        client_ip=client_ip, user_agent=user_agent,
                        attempt_count=attempts, request_body=body,
                        response_body=b"No Gemini keys available",
                        is_error=True, error_detail="No Gemini keys available",
                    )
                    return Response("No Gemini keys available", status_code=503, background=bg)

                params = dict(request.query_params)
                params["key"] = api_key
                key_id = f"...{api_key[-4:]}"
                log_auth = f"Key {key_id}"

            else:
                upstream_base = settings.services.vertex_base_url
                cred = state.vertex_rotator.get_next_credential()
                if not cred:
                    latency_ms = int((time.time() - start_time) * 1000)
                    bg = BackgroundTask(
                        _record_stats,
                        provider=provider, model=model, key_id="system",
                        status_code=503, latency_ms=latency_ms, action=action,
                        http_method=request.method, url_path=full_path,
                        client_ip=client_ip, user_agent=user_agent,
                        attempt_count=attempts, request_body=body,
                        response_body=b"No Vertex credentials available",
                        is_error=True, error_detail="No Vertex credentials available",
                    )
                    return Response("No Vertex credentials available", status_code=503, background=bg)
                token = await state.vertex_rotator.get_token(cred)

                match = PROJECT_PATH_REGEX.match(full_path)
                target_path = (
                    f"{match.group(1)}{cred.project_id}{match.group(3)}"
                    if match
                    else full_path
                )

                headers["Authorization"] = f"Bearer {token}"
                headers["X-Goog-User-Project"] = cred.project_id
                params = dict(request.query_params)
                key_id = cred.project_id
                log_auth = f"Project {cred.project_id}"

            final_key_id = key_id
            url = f"{upstream_base}/{target_path}"
            logger.info(f"Attempt {attempts} [{log_auth}] -> {url}")

            if state.http_client is None:
                raise HTTPException(status_code=503, detail="Service is not ready")

            req = state.http_client.build_request(
                request.method, url, content=body, headers=headers, params=params
            )

            if is_streaming:
                resp = await state.http_client.send(req, stream=True)

                if resp.status_code in [429, 403, 503]:
                    err_body = await resp.aread()
                    logger.warning(f"Provider Error {resp.status_code}: {err_body[:200]}")
                    continue

                # For streaming: collect chunks while forwarding to client
                chunks: list[bytes] = []
                stream_start = time.time()

                async def stream_and_collect() -> AsyncIterator[bytes]:
                    async for chunk in resp.aiter_bytes():
                        chunks.append(chunk)
                        yield chunk

                async def record_streaming_stats():
                    latency_ms = int((time.time() - start_time) * 1000)
                    full_body = b"".join(chunks)
                    await _record_stats(
                        provider=provider, model=model, key_id=key_id,
                        status_code=resp.status_code, latency_ms=latency_ms,
                        action=action, http_method=request.method, url_path=full_path,
                        client_ip=client_ip, user_agent=user_agent,
                        attempt_count=attempts, request_body=body,
                        response_body=full_body,
                        is_error=resp.status_code >= 400,
                        error_detail=None,
                    )

                return StreamingResponse(
                    stream_and_collect(),
                    status_code=resp.status_code,
                    headers={
                        k: v for k, v in resp.headers.items()
                        if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")
                    },
                    background=BackgroundTask(record_streaming_stats),
                )

            else:
                # Non-streaming: read full response
                resp = await state.http_client.send(req)

                if resp.status_code in [429, 403, 503]:
                    logger.warning(f"Provider Error {resp.status_code}: {resp.content[:200]}")
                    continue

                resp_body = resp.content
                latency_ms = int((time.time() - start_time) * 1000)

                bg = BackgroundTask(
                    _record_stats,
                    provider=provider, model=model, key_id=key_id,
                    status_code=resp.status_code, latency_ms=latency_ms,
                    action=action, http_method=request.method, url_path=full_path,
                    client_ip=client_ip, user_agent=user_agent,
                    attempt_count=attempts, request_body=body,
                    response_body=resp_body,
                    is_error=resp.status_code >= 400,
                    error_detail=None,
                )

                resp_headers = {
                    k: v for k, v in resp.headers.items()
                    if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")
                }

                return Response(
                    content=resp_body,
                    status_code=resp.status_code,
                    headers=resp_headers,
                    background=bg,
                )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Proxy error: {e}")
            final_error = str(e)
            final_key_id = key_id
            await asyncio.sleep(0.5)
            continue

    # All retries exhausted
    latency_ms = int((time.time() - start_time) * 1000)
    error_msg = "All backends exhausted or unavailable"
    bg = BackgroundTask(
        _record_stats,
        provider=provider, model=model, key_id=final_key_id,
        status_code=503, latency_ms=latency_ms, action=action,
        http_method=request.method, url_path=full_path,
        client_ip=client_ip, user_agent=user_agent,
        attempt_count=attempts, request_body=body,
        response_body=error_msg.encode(),
        is_error=True, error_detail=final_error or error_msg,
    )
    return Response(error_msg, status_code=503, background=bg)
