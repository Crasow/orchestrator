import logging
import asyncio
from fastapi import APIRouter, Request, Depends, HTTPException
from app.core import state
from app.security.auth import auth_manager, get_current_admin
from app.services.statistics import stats_service
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin"])


def _get_stats_service():
    svc = statistics.stats_service
    if svc is None:
        raise HTTPException(status_code=503, detail="Stats service not initialized")
    return svc


@router.post("/login")
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


@router.post("/reload")
async def admin_reload(
    request: Request, current_admin: dict = Depends(get_current_admin)
):
    """Горячая перезагрузка ключей без остановки сервиса"""
    try:
        state.vertex_rotator.reload()
        state.gemini_rotator.reload()

        logger.info(f"Admin {current_admin['sub']} reloaded credentials")

        return {
            "status": "reloaded",
            "vertex_count": len(state.vertex_rotator._pool),
            "gemini_count": len(state.gemini_rotator._keys),
        }
    except Exception as e:
        logger.error(f"Reload failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to reload credentials")


@router.get("/status")
async def admin_status(current_admin: dict = Depends(get_current_admin)):
    """Статус системы"""
    try:
        from app.security.audit import security_auditor

        suspicious = security_auditor.get_suspicious_activity(hours=1)

        return {
            "status": "operational",
            "vertex_credentials": len(state.vertex_rotator._pool),
            "gemini_keys": len(state.gemini_rotator._keys),
            "suspicious_activity": suspicious,
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
    """Агрегированная статистика за период"""
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
    """Лог запросов с пагинацией"""
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
    """Статистика по моделям"""
    svc = _get_stats_service()
    return await svc.get_model_stats(hours=hours)


@router.get("/stats/tokens")
async def get_token_stats(
    current_admin: dict = Depends(get_current_admin),
    hours: int = Query(24, ge=1),
    group_by: str = Query("hour", pattern="^(hour|day|model|key)$"),
):
    """Использование токенов"""
    svc = _get_stats_service()
    return await svc.get_token_stats(hours=hours, group_by=group_by)


@router.delete("/stats/cleanup")
async def cleanup_stats(
    current_admin: dict = Depends(get_current_admin),
    days: int = Query(30, ge=1),
):
    """Очистка старых записей"""
    svc = _get_stats_service()
    return await svc.cleanup(days=days)
  
  
@router.get("/providers")
async def get_providers(current_admin: dict = Depends(get_current_admin)):
    """Get list of available providers and their keys/credentials identifiers"""
    gemini_keys = []
    for idx, k in enumerate(state.gemini_rotator._keys):
        gemini_keys.append({"index": idx, "mask": f"...{k[-4:]}"})
        
    vertex_creds = []
    for cred in state.vertex_rotator._pool:
        vertex_creds.append({"project_id": cred.project_id})
        
    return {
        "gemini": gemini_keys,
        "vertex": vertex_creds
    }


@router.post("/test-provider")
async def test_provider(request: Request, current_admin: dict = Depends(get_current_admin)):
    """Test a specific provider key against a model"""
    data = await request.json()
    provider = data.get("provider")
    identifier = data.get("identifier")
    model = data.get("model") 
    
    if not provider or identifier is None or not model:
        raise HTTPException(status_code=400, detail="Missing parameters")

    model_name = model.get("name")
    methods = model.get("supportedGenerationMethods", [])
    
    try:
        if provider == "gemini":
            idx = int(identifier)
            if idx < 0 or idx >= len(state.gemini_rotator._keys):
                 return {"status": "error", "error": "Invalid Gemini key index"}
            
            key = state.gemini_rotator._keys[idx]
            base = f"{settings.services.gemini_base_url}/v1beta"
            
            # Simplified logic for testing
            if "generateContent" in methods:
                endpoint = ":generateContent"
                payload = {"contents": [{"role": "user", "parts": [{"text": "Hi"}]}], "generationConfig": {"maxOutputTokens": 1}}
            elif "predict" in methods: # For completeness if any model requires it
                 endpoint = ":generateContent" # Fallback to generateContent for Gemini usually
                 payload = {"contents": [{"role": "user", "parts": [{"text": "Hi"}]}], "generationConfig": {"maxOutputTokens": 1}}
            else:
                 return {"status": "skipped", "error": "Method not supported for test"}
                 
            url = f"{base}/{model_name}{endpoint}"
            params = {"key": key}
            
            if state.http_client is None:
                 return {"status": "error", "error": "Client not ready"}

            resp = await state.http_client.post(url, params=params, json=payload, timeout=20.0)
            
            error_text = None
            if resp.status_code != 200:
                try:
                    error_text = resp.json()
                except:
                    error_text = resp.text
            
            return {
                "status": "working" if resp.status_code == 200 else "error",
                "code": resp.status_code,
                "error": error_text
            }

        elif provider == "vertex":
            pid = identifier
            cred = next((c for c in state.vertex_rotator._pool if c.project_id == pid), None)
            if not cred:
                return {"status": "error", "error": "Project ID not found"}
                
            clean_name = model_name.split("/")[-1]
            location = "us-central1"
            base = f"{settings.services.vertex_base_url}/v1"
            
            if "generateContent" in methods:
                endpoint = ":generateContent"
                payload = {"contents": [{"role": "user", "parts": [{"text": "Hi"}]}], "generationConfig": {"maxOutputTokens": 1}}
            elif "predict" in methods:
                endpoint = ":predict"
                payload = {"instances": [{"prompt": "Blue circle"}], "parameters": {"sampleCount": 1}}
            elif "predictLongRunning" in methods:
                 endpoint = ":predictLongRunning"
                 payload = {"instances": [{"prompt": "Cat jumping"}], "parameters": {}}
            else:
                 return {"status": "skipped", "error": "Method not supported"}

            url = f"{base}/projects/{cred.project_id}/locations/{location}/publishers/google/models/{clean_name}{endpoint}"
            
            try:
                token = await state.vertex_rotator.get_token(cred)
            except Exception as e:
                return {"status": "error", "error": f"Token error: {e}"}

            headers = {
                "Authorization": f"Bearer {token}",
                "X-Goog-User-Project": cred.project_id
            }
            
            if state.http_client is None:
                 return {"status": "error", "error": "Client not ready"}

            resp = await state.http_client.post(url, headers=headers, json=payload, timeout=20.0)
            
            error_text = None
            if resp.status_code != 200:
                try:
                    error_text = resp.json()
                except:
                    error_text = resp.text

            return {
                "status": "working" if resp.status_code == 200 else "error",
                "code": resp.status_code,
                "error": error_text
            }
            
    except Exception as e:
        return {"status": "error", "error": str(e)}
        
    return {"status": "error", "error": "Invalid provider"}


@router.post("/check-keys")
async def check_api_keys(
    request: Request,
    current_admin: dict = Depends(get_current_admin)
):
    """
    Checks all configured API keys and Credentials against a provided list of models.
    """
    body = await request.json()
    models = body.get("models", [])
    
    if not models:
        return {"error": "No models provided in body"}

    results = {
        "gemini": {},
        "vertex": {}
    }
    
    semaphore = asyncio.Semaphore(10) # Limit concurrency

    async def _check_gemini(key, model):
        async with semaphore:
            model_name = model["name"]
            # Usually only text models work with Gemini API directly (generateContent)
            # Use v1beta for widest compatibility
            base = f"{settings.services.gemini_base_url}/v1beta"
            
            endpoint = ":generateContent"
            payload = {
                "contents": [{"role": "user", "parts": [{"text": "Hi"}]}],
                "generationConfig": {"maxOutputTokens": 1}
            }
            
            methods = model.get("supportedGenerationMethods", [])
            if "generateContent" not in methods:
                 return None 

            url = f"{base}/{model_name}{endpoint}"
            params = {"key": key}
            
            try:
                if state.http_client is None:
                    return {"model": model_name, "status": "error", "error": "Client not ready"}

                resp = await state.http_client.post(url, params=params, json=payload, timeout=10.0)
                return {
                    "model": model_name,
                    "status": resp.status_code
                }
            except Exception as e:
                return {
                    "model": model_name,
                    "status": "error",
                    "error": str(e)
                }

    async def _check_vertex(cred, model):
        async with semaphore:
            model_name = model["name"]
            clean_name = model_name.split("/")[-1]
            
            methods = model.get("supportedGenerationMethods", [])
            
            if "generateContent" in methods:
                endpoint = ":generateContent"
                payload = {"contents": [{"role": "user", "parts": [{"text": "Hi"}]}], "generationConfig": {"maxOutputTokens": 1}}
            elif "predict" in methods:
                endpoint = ":predict"
                payload = {"instances": [{"prompt": "Blue circle"}], "parameters": {"sampleCount": 1}}
            elif "predictLongRunning" in methods:
                 endpoint = ":predictLongRunning"
                 payload = {"instances": [{"prompt": "Cat jumping"}], "parameters": {}}
            else:
                return None

            location = "us-central1"
            base = f"{settings.services.vertex_base_url}/v1"
            url = f"{base}/projects/{cred.project_id}/locations/{location}/publishers/google/models/{clean_name}{endpoint}"
            
            try:
                token = await state.vertex_rotator.get_token(cred)
                headers = {
                    "Authorization": f"Bearer {token}",
                    "X-Goog-User-Project": cred.project_id
                }
                
                if state.http_client is None:
                    return {"model": model_name, "status": "error", "error": "Client not ready"}

                resp = await state.http_client.post(url, headers=headers, json=payload, timeout=10.0)
                return {
                    "model": model_name,
                    "status": resp.status_code
                }
            except Exception as e:
                 return {
                    "model": model_name,
                    "status": "error",
                    "error": str(e)
                }

    # Gemini
    for key in state.gemini_rotator._keys:
        key_masked = f"...{key[-4:]}"
        key_futures = []
        for m in models:
            key_futures.append(_check_gemini(key, m))
        
        key_results = await asyncio.gather(*key_futures)
        results["gemini"][key_masked] = [r for r in key_results if r is not None]

    # Vertex
    for cred in state.vertex_rotator._pool:
        pid = cred.project_id
        cred_futures = []
        for m in models:
            cred_futures.append(_check_vertex(cred, m))
            
        cred_results = await asyncio.gather(*cred_futures)
        results["vertex"][pid] = [r for r in cred_results if r is not None]

    return results
