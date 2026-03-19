import logging
import asyncio
import json
import os
import tempfile
from os.path import basename
from typing import Any

from fastapi import APIRouter, Request, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core import state
from app.security.auth import auth_manager, get_current_admin
from app.security.encryption import encryption_manager
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


class AddGeminiKeysRequest(BaseModel):
    keys: list[str] = Field(min_length=1)


class UpdateGeminiKeyRequest(BaseModel):
    key: str = Field(min_length=1)


class UploadVertexRequest(BaseModel):
    filename: str = Field(pattern=r'^[\w\-\.]+\.json$')
    credential: dict


class UpdateVertexRequest(BaseModel):
    credential: dict


# --- Helpers ---

def _get_stats_service():
    svc = statistics.stats_service
    if svc is None:
        raise HTTPException(status_code=503, detail="Stats service not initialized")
    return svc


def _mask_key(key: str) -> str:
    """Mask an API key, showing only the last 4 characters."""
    return f"...{key[-4:]}" if len(key) >= 4 else "...***"


def _atomic_write_json(filepath, data) -> None:
    """Write JSON to a temp file, then atomically replace the target."""
    dir_path = os.path.dirname(filepath)
    fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, str(filepath))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _read_gemini_keys_raw() -> tuple[list[str], bool]:
    """Read Gemini keys file and return (keys, is_encrypted).

    Mirrors logic from GeminiRotator.load_keys().
    """
    filepath = settings.paths.gemini_keys_file
    if not os.path.exists(filepath):
        return [], False

    with open(filepath, "r") as f:
        data = json.load(f)

    if isinstance(data, dict) and "encrypted_keys" in data:
        encrypted_keys = data["encrypted_keys"]
        keys = []
        for ek in encrypted_keys:
            keys.append(encryption_manager.decrypt_data(ek))
        return keys, True
    elif isinstance(data, list):
        return [k for k in data if isinstance(k, str) and k.strip()], False
    else:
        raise ValueError("Unrecognised Gemini keys file format")


def _write_gemini_keys(keys: list[str], is_encrypted: bool) -> None:
    """Write Gemini keys back to disk, re-encrypting if needed."""
    filepath = settings.paths.gemini_keys_file
    if is_encrypted:
        encrypted = [encryption_manager.encrypt_data(k) for k in keys]
        _atomic_write_json(filepath, {"encrypted_keys": encrypted})
    else:
        _atomic_write_json(filepath, keys)


def _reload_gemini() -> None:
    """Reload the Gemini rotator and re-register keys in the rate limiter."""
    state.gemini_rotator.reload()
    for key in state.gemini_rotator.keys:
        state.gemini_rate_limiter.register_key(key)


def _reload_vertex() -> None:
    """Reload the Vertex rotator and re-register credentials in the rate limiter."""
    state.vertex_rotator.reload()
    for cred in state.vertex_rotator.credentials:
        state.vertex_rate_limiter.register_key(cred.project_id)


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
        {"index": idx, "mask": _mask_key(k)}
        for idx, k in enumerate(state.gemini_rotator.keys)
    ]
    vertex_creds = [
        {"project_id": cred.project_id}
        for cred in state.vertex_rotator.credentials
    ]
    return {"gemini": gemini_keys, "vertex": vertex_creds}


# --- Gemini Key CRUD ---

@router.get("/keys/gemini")
async def list_gemini_keys(current_admin: dict = Depends(get_current_admin)):
    """List all Gemini API keys (masked)."""
    return [
        {"index": i, "mask": _mask_key(k)}
        for i, k in enumerate(state.gemini_rotator.keys)
    ]


@router.post("/keys/gemini", status_code=201)
async def add_gemini_keys(body: AddGeminiKeysRequest, current_admin: dict = Depends(get_current_admin)):
    """Add one or more Gemini API keys."""
    existing_keys, is_encrypted = _read_gemini_keys_raw()

    new_keys = [k.strip() for k in body.keys]
    if any(not k for k in new_keys):
        raise HTTPException(status_code=422, detail="Keys must not be empty or whitespace-only")

    existing_set = set(existing_keys)
    duplicates = [k for k in new_keys if k in existing_set]
    if duplicates:
        raise HTTPException(status_code=409, detail=f"{len(duplicates)} duplicate key(s) rejected")

    existing_keys.extend(new_keys)
    _write_gemini_keys(existing_keys, is_encrypted)
    _reload_gemini()

    logger.info(f"Admin {current_admin['sub']} added {len(new_keys)} Gemini key(s)")
    return {"added": len(new_keys), "total": len(existing_keys)}


@router.put("/keys/gemini/{index}")
async def update_gemini_key(index: int, body: UpdateGeminiKeyRequest, current_admin: dict = Depends(get_current_admin)):
    """Replace a Gemini API key at the given index."""
    keys, is_encrypted = _read_gemini_keys_raw()

    if index < 0 or index >= len(keys):
        raise HTTPException(status_code=404, detail=f"Index {index} out of range (0..{len(keys) - 1})")

    new_key = body.key.strip()
    if not new_key:
        raise HTTPException(status_code=422, detail="Key must not be empty")

    # Check duplicate against other keys (not the one being replaced)
    other_keys = keys[:index] + keys[index + 1:]
    if new_key in other_keys:
        raise HTTPException(status_code=409, detail="Duplicate key")

    keys[index] = new_key
    _write_gemini_keys(keys, is_encrypted)
    _reload_gemini()

    logger.info(f"Admin {current_admin['sub']} updated Gemini key at index {index}")
    return {"updated": index, "mask": _mask_key(new_key)}


@router.delete("/keys/gemini/{index}")
async def delete_gemini_key(index: int, current_admin: dict = Depends(get_current_admin)):
    """Remove a Gemini API key at the given index."""
    keys, is_encrypted = _read_gemini_keys_raw()

    if index < 0 or index >= len(keys):
        raise HTTPException(status_code=404, detail=f"Index {index} out of range (0..{len(keys) - 1})")

    removed = keys.pop(index)
    _write_gemini_keys(keys, is_encrypted)
    _reload_gemini()

    logger.info(f"Admin {current_admin['sub']} deleted Gemini key at index {index}")
    return {"deleted": index, "remaining": len(keys)}


# --- Vertex Credential CRUD ---

@router.get("/keys/vertex")
async def list_vertex_credentials(current_admin: dict = Depends(get_current_admin)):
    """List all Vertex service account credentials."""
    return [
        {"project_id": cred.project_id, "filename": basename(cred.json_path)}
        for cred in state.vertex_rotator.credentials
    ]


@router.post("/keys/vertex", status_code=201)
async def add_vertex_credential(body: UploadVertexRequest, current_admin: dict = Depends(get_current_admin)):
    """Upload a new Vertex service account JSON."""
    cred_data = body.credential
    if "private_key" not in cred_data or "project_id" not in cred_data:
        raise HTTPException(status_code=422, detail="Credential must contain 'private_key' and 'project_id'")

    project_id = cred_data["project_id"]
    creds_dir = settings.paths.vertex_creds_dir
    target_path = os.path.join(str(creds_dir), body.filename)

    # Check filename collision
    if os.path.exists(target_path):
        raise HTTPException(status_code=409, detail=f"File '{body.filename}' already exists")

    # Check project_id collision
    existing_pids = {c.project_id for c in state.vertex_rotator.credentials}
    if project_id in existing_pids:
        raise HTTPException(status_code=409, detail=f"Project ID '{project_id}' already loaded")

    _atomic_write_json(target_path, cred_data)
    _reload_vertex()

    logger.info(f"Admin {current_admin['sub']} added Vertex credential: {body.filename} ({project_id})")
    return {"added": body.filename, "project_id": project_id}


@router.put("/keys/vertex/{project_id}")
async def update_vertex_credential(project_id: str, body: UpdateVertexRequest, current_admin: dict = Depends(get_current_admin)):
    """Replace a Vertex service account by project_id."""
    cred = next((c for c in state.vertex_rotator.credentials if c.project_id == project_id), None)
    if cred is None:
        raise HTTPException(status_code=404, detail=f"Project ID '{project_id}' not found")

    cred_data = body.credential
    if "private_key" not in cred_data or "project_id" not in cred_data:
        raise HTTPException(status_code=422, detail="Credential must contain 'private_key' and 'project_id'")

    _atomic_write_json(cred.json_path, cred_data)
    _reload_vertex()

    logger.info(f"Admin {current_admin['sub']} updated Vertex credential: {project_id}")
    return {"updated": project_id}


@router.delete("/keys/vertex/{project_id}")
async def delete_vertex_credential(project_id: str, current_admin: dict = Depends(get_current_admin)):
    """Remove a Vertex service account by project_id."""
    cred = next((c for c in state.vertex_rotator.credentials if c.project_id == project_id), None)
    if cred is None:
        raise HTTPException(status_code=404, detail=f"Project ID '{project_id}' not found")

    os.remove(cred.json_path)
    _reload_vertex()

    logger.info(f"Admin {current_admin['sub']} deleted Vertex credential: {project_id}")
    return {"deleted": project_id}


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
        key_masked = _mask_key(key)
        futures = [_check("gemini", key, m) for m in body.models]
        key_results = await asyncio.gather(*futures)
        results["gemini"][key_masked] = [r for r in key_results if r is not None]

    # Vertex
    for cred in state.vertex_rotator.credentials:
        futures = [_check("vertex", cred, m) for m in body.models]
        cred_results = await asyncio.gather(*futures)
        results["vertex"][cred.project_id] = [r for r in cred_results if r is not None]

    return results
