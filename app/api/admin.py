import logging
from fastapi import APIRouter, Request, Depends, HTTPException
from app.core.state import vertex_rotator, gemini_rotator
from app.security.auth import auth_manager, get_current_admin
from app.services.statistics import stats_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin"])


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
async def get_system_stats(current_admin: dict = Depends(get_current_admin)):
    """Детальная статистика использования"""
    return stats_service.get_stats()

