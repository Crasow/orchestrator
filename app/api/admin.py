import logging
import asyncio
from typing import Any

from fastapi import APIRouter, Request, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core import state
from app.security.auth import auth_manager, get_current_admin
from app.services import statistics
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin"])

COOKIE_NAME = "access_token"
COOKIE_MAX_AGE = 30 * 60  # 30 minutes, matches default token expiry


# --- Pydantic request models ---

class LoginRequest(BaseModel):
    username: str
    password: str


class ModelInfo(BaseModel):
    name: str
    supportedGenerationMethods: list[str] = []


class TestProviderRequest(BaseModel):
    provider: str
    identifier: str | int
    model: ModelInfo


class CheckKeysRequest(BaseModel):
    models: list[ModelInfo] = Field(min_length=1)


# --- Helpers ---

def _get_stats_service():
    svc = statistics.stats_service
    if svc is None:
        raise HTTPException(status_code=503, detail="Stats service not initialized")
    return svc


def _build_payload(methods: list[str]) -> tuple[str, dict] | None:
    """Build endpoint suffix and payload based on supported methods. Returns None if no method is supported."""
    if "generateContent" in methods:
        return ":generateContent", {
            "contents": [{"role": "user", "parts": [{"text": "Hi"}]}],
            "generationConfig": {"maxOutputTokens": 1},
        }
    if "predict" in methods:
        return ":predict", {
            "instances": [{"prompt": "Blue circle"}],
            "parameters": {"sampleCount": 1},
        }
    if "predictLongRunning" in methods:
        return ":predictLongRunning", {
            "instances": [{"prompt": "Cat jumping"}],
            "parameters": {},
        }
    return None


async def _test_single_model(
    provider: str,
    credential: Any,
    model_name: str,
    methods: list[str],
    timeout: float = 20.0,
) -> dict | None:
    """Test a single model against a provider credential. Returns result dict or None if skipped."""
    payload_info = _build_payload(methods)
    if payload_info is None:
        return None

    endpoint, payload = payload_info

    if state.http_client is None:
        return {"model": model_name, "status": "error", "error": "Client not ready"}

    try:
        if provider == "gemini":
            clean_name = model_name
            base = f"{settings.services.gemini_base_url}/v1beta"
            url = f"{base}/{clean_name}{endpoint}"
            params = {"key": credential}
            resp = await state.http_client.post(url, params=params, json=payload, timeout=timeout)
        elif provider == "vertex":
            clean_name = model_name.split("/")[-1]
            location = "us-central1"
            base = f"{settings.services.vertex_base_url}/v1"
            url = f"{base}/projects/{credential.project_id}/locations/{location}/publishers/google/models/{clean_name}{endpoint}"

            try:
                token = await state.vertex_rotator.get_token(credential)
            except Exception as e:
                return {"model": model_name, "status": "error", "error": f"Token error: {e}"}

            headers = {
                "Authorization": f"Bearer {token}",
                "X-Goog-User-Project": credential.project_id,
            }
            resp = await state.http_client.post(url, headers=headers, json=payload, timeout=timeout)
        else:
            return {"model": model_name, "status": "error", "error": "Invalid provider"}

        error_text = None
        if resp.status_code != 200:
            try:
                error_text = resp.json()
            except Exception:
                error_text = resp.text

        return {
            "model": model_name,
            "status": "working" if resp.status_code == 200 else "error",
            "code": resp.status_code,
            "error": error_text,
        }
    except Exception as e:
        return {"model": model_name, "status": "error", "error": str(e)}


# --- Endpoints ---

@router.post("/login")
async def admin_login(request: Request, body: LoginRequest):
    """Login to admin panel. Sets JWT in httpOnly cookie."""
    try:
        client_ip = getattr(request.client, "host", "unknown")
        token = auth_manager.authenticate_admin(body.username, body.password, client_ip)

        response = JSONResponse(content={"status": "ok", "username": body.username})
        response.set_cookie(
            key=COOKIE_NAME,
            value=token,
            max_age=COOKIE_MAX_AGE,
            httponly=True,
            samesite="lax",
            secure=settings.security.cookie_secure,
            path="/",
        )
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(status_code=500, detail="Authentication failed")


@router.post("/logout")
async def admin_logout():
    """Logout — deletes token cookie."""
    response = JSONResponse(content={"status": "ok"})
    response.delete_cookie(key=COOKIE_NAME, path="/")
    return response


@router.post("/reload")
async def admin_reload(
    request: Request, current_admin: dict = Depends(get_current_admin)
):
    """Hot-reload keys without stopping the service."""
    try:
        state.vertex_rotator.reload()
        state.gemini_rotator.reload()

        logger.info(f"Admin {current_admin['sub']} reloaded credentials")

        return {
            "status": "reloaded",
            "vertex_count": state.vertex_rotator.credential_count,
            "gemini_count": state.gemini_rotator.key_count,
        }
    except Exception as e:
        logger.error(f"Reload failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to reload credentials")


@router.get("/status")
async def admin_status(current_admin: dict = Depends(get_current_admin)):
    """System status."""
    try:
        return {
            "status": "operational",
            "vertex_credentials": state.vertex_rotator.credential_count,
            "gemini_keys": state.gemini_rotator.key_count,
            "admin_user": current_admin["sub"],
        }
    except Exception as e:
        logger.error(f"Status check failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to get status")


@router.get("/stats")
async def get_system_stats(
    current_admin: dict = Depends(get_current_admin),
    hours: int = Query(24, ge=1),
    provider: str | None = Query(None),
):
    """Aggregated stats for a period."""
    svc = _get_stats_service()
    return await svc.get_stats(hours=hours, provider=provider)


@router.get("/stats/requests")
async def get_requests_log(
    current_admin: dict = Depends(get_current_admin),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    model: str | None = Query(None),
    provider: str | None = Query(None),
    errors_only: bool = Query(False),
):
    """Request log with pagination."""
    svc = _get_stats_service()
    return await svc.get_requests_log(
        limit=limit, offset=offset, model=model,
        provider=provider, errors_only=errors_only,
    )


@router.get("/stats/models")
async def get_model_stats(
    current_admin: dict = Depends(get_current_admin),
    hours: int = Query(24, ge=1),
):
    """Per-model statistics."""
    svc = _get_stats_service()
    return await svc.get_model_stats(hours=hours)


@router.get("/stats/tokens")
async def get_token_stats(
    current_admin: dict = Depends(get_current_admin),
    hours: int = Query(24, ge=1),
    group_by: str = Query("hour", pattern="^(hour|day|model|key)$"),
):
    """Token usage."""
    svc = _get_stats_service()
    return await svc.get_token_stats(hours=hours, group_by=group_by)


@router.delete("/stats/cleanup")
async def cleanup_stats(
    current_admin: dict = Depends(get_current_admin),
    days: int = Query(30, ge=1),
):
    """Clean up old records."""
    svc = _get_stats_service()
    return await svc.cleanup(days=days)


@router.get("/providers")
async def get_providers(current_admin: dict = Depends(get_current_admin)):
    """Get list of available providers and their keys/credentials identifiers."""
    gemini_keys = [
        {"index": idx, "mask": f"...{k[-4:]}"}
        for idx, k in enumerate(state.gemini_rotator.keys)
    ]
    vertex_creds = [
        {"project_id": cred.project_id}
        for cred in state.vertex_rotator.credentials
    ]
    return {"gemini": gemini_keys, "vertex": vertex_creds}


@router.post("/test-provider")
async def test_provider(body: TestProviderRequest, current_admin: dict = Depends(get_current_admin)):
    """Test a specific provider key against a model."""
    model_name = body.model.name
    methods = body.model.supportedGenerationMethods

    if body.provider == "gemini":
        idx = int(body.identifier)
        keys = state.gemini_rotator.keys
        if idx < 0 or idx >= len(keys):
            return {"status": "error", "error": "Invalid Gemini key index"}
        credential = keys[idx]

    elif body.provider == "vertex":
        pid = str(body.identifier)
        credential = next((c for c in state.vertex_rotator.credentials if c.project_id == pid), None)
        if not credential:
            return {"status": "error", "error": "Project ID not found"}
    else:
        return {"status": "error", "error": "Invalid provider"}

    result = await _test_single_model(body.provider, credential, model_name, methods)
    if result is None:
        return {"status": "skipped", "error": "Method not supported for test"}
    return result


@router.post("/check-keys")
async def check_api_keys(
    body: CheckKeysRequest,
    current_admin: dict = Depends(get_current_admin),
):
    """Check all configured API keys and credentials against a list of models."""
    results: dict[str, dict] = {"gemini": {}, "vertex": {}}
    semaphore = asyncio.Semaphore(10)

    async def _check(provider: str, credential: Any, model: ModelInfo):
        async with semaphore:
            return await _test_single_model(
                provider, credential, model.name,
                model.supportedGenerationMethods, timeout=10.0,
            )

    # Gemini
    for key in state.gemini_rotator.keys:
        key_masked = f"...{key[-4:]}"
        futures = [_check("gemini", key, m) for m in body.models]
        key_results = await asyncio.gather(*futures)
        results["gemini"][key_masked] = [r for r in key_results if r is not None]

    # Vertex
    for cred in state.vertex_rotator.credentials:
        futures = [_check("vertex", cred, m) for m in body.models]
        cred_results = await asyncio.gather(*futures)
        results["vertex"][cred.project_id] = [r for r in cred_results if r is not None]

    return results
