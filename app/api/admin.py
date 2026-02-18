import logging
from fastapi import APIRouter, Request, Depends, HTTPException, Query
from app.core.state import vertex_rotator, gemini_rotator
from app.security.auth import auth_manager, get_current_admin
from app.services import statistics

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
        vertex_rotator.reload()
        gemini_rotator.reload()

        logger.info(f"Admin {current_admin['sub']} reloaded credentials")

        return {
            "status": "reloaded",
            "vertex_count": len(vertex_rotator._pool),
            "gemini_count": len(gemini_rotator._keys),
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
            "vertex_credentials": len(vertex_rotator._pool),
            "gemini_keys": len(gemini_rotator._keys),
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
