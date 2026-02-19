import time
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, func, delete, case, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import ApiKey, Model, Request

logger = logging.getLogger(__name__)


class StatsService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory
        self._start_time = time.time()
        # In-memory FK caches: key_id_str -> api_keys.id, model_name -> models.id
        self._api_key_cache: dict[str, int] = {}
        self._model_cache: dict[str, int] = {}

    async def _resolve_api_key_id(self, session: AsyncSession, key_id: str, provider: str) -> int | None:
        if key_id in self._api_key_cache:
            return self._api_key_cache[key_id]
        result = await session.execute(select(ApiKey.id).where(ApiKey.key_id == key_id))
        row = result.scalar_one_or_none()
        if row is None:
            ak = ApiKey(provider=provider, key_id=key_id)
            session.add(ak)
            await session.flush()
            row = ak.id
        if row is not None:
            self._api_key_cache[key_id] = row
        return row

    async def _resolve_model_id(self, session: AsyncSession, model_name: str, provider: str) -> int | None:
        if not model_name or model_name == "unknown":
            return None
        if model_name in self._model_cache:
            return self._model_cache[model_name]
        result = await session.execute(select(Model.id).where(Model.name == model_name))
        row = result.scalar_one_or_none()
        if row is None:
            m = Model(name=model_name, provider=provider)
            session.add(m)
            await session.flush()
            row = m.id
        if row is not None:
            self._model_cache[model_name] = row
        return row

    async def record_request(
        self,
        *,
        provider: str,
        model: str,
        key_id: str,
        status_code: int,
        latency_ms: int,
        action: str | None = None,
        http_method: str = "POST",
        url_path: str = "",
        client_ip: str | None = None,
        user_agent: str | None = None,
        attempt_count: int = 1,
        prompt_tokens: int | None = None,
        candidates_tokens: int | None = None,
        total_tokens: int | None = None,
        request_body: dict | None = None,
        response_body: dict | None = None,
        is_error: bool = False,
        error_detail: str | None = None,
        request_size: int | None = None,
        response_size: int | None = None,
    ) -> None:
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    api_key_id = await self._resolve_api_key_id(session, key_id, provider)
                    model_id = await self._resolve_model_id(session, model, provider)
                    req = Request(
                        api_key_id=api_key_id,
                        model_id=model_id,
                        provider=provider,
                        action=action,
                        http_method=http_method,
                        url_path=url_path,
                        client_ip=client_ip,
                        user_agent=user_agent,
                        status_code=status_code,
                        latency_ms=latency_ms,
                        attempt_count=attempt_count,
                        prompt_tokens=prompt_tokens,
                        candidates_tokens=candidates_tokens,
                        total_tokens=total_tokens,
                        request_body=request_body,
                        response_body=response_body,
                        is_error=is_error,
                        error_detail=error_detail,
                        request_size=request_size,
                        response_size=response_size,
                    )
                    session.add(req)
        except Exception as e:
            logger.error(f"Failed to record stats: {e}")

    async def get_stats(self, hours: int = 24, provider: str | None = None) -> dict:
        try:
            async with self._session_factory() as session:
                since = datetime.now(timezone.utc) - timedelta(hours=hours)

                stmt = select(
                    func.count(Request.id).label("total_requests"),
                    func.count(case((Request.is_error == True, 1))).label("total_errors"),
                    func.avg(Request.latency_ms).label("avg_latency_ms"),
                    func.sum(Request.prompt_tokens).label("total_prompt_tokens"),
                    func.sum(Request.candidates_tokens).label("total_candidates_tokens"),
                    func.sum(Request.total_tokens).label("total_tokens"),
                ).where(Request.created_at >= since)
                if provider:
                    stmt = stmt.where(Request.provider == provider)

                result = await session.execute(stmt)
                row = result.one()

                total_req = row.total_requests or 0
                total_err = row.total_errors or 0

                return {
                    "uptime_seconds": round(time.time() - self._start_time, 2),
                    "period_hours": hours,
                    "total_requests": total_req,
                    "total_errors": total_err,
                    "error_rate": round((total_err / total_req * 100), 2) if total_req > 0 else 0,
                    "avg_latency_ms": round(float(row.avg_latency_ms or 0), 2),
                    "total_prompt_tokens": row.total_prompt_tokens or 0,
                    "total_candidates_tokens": row.total_candidates_tokens or 0,
                    "total_tokens": row.total_tokens or 0,
                }
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {"error": str(e)}

    async def get_requests_log(
        self,
        limit: int = 50,
        offset: int = 0,
        model: str | None = None,
        provider: str | None = None,
        errors_only: bool = False,
    ) -> dict:
        try:
            async with self._session_factory() as session:
                stmt = (
                    select(
                        Request.id,
                        Request.provider,
                        Request.action,
                        Request.http_method,
                        Request.url_path,
                        Request.client_ip,
                        Request.status_code,
                        Request.latency_ms,
                        Request.attempt_count,
                        Request.prompt_tokens,
                        Request.candidates_tokens,
                        Request.total_tokens,
                        Request.is_error,
                        Request.error_detail,
                        Request.request_size,
                        Request.response_size,
                        Request.created_at,
                        ApiKey.key_id.label("api_key"),
                        Model.name.label("model_name"),
                    )
                    .outerjoin(ApiKey, Request.api_key_id == ApiKey.id)
                    .outerjoin(Model, Request.model_id == Model.id)
                    .order_by(Request.created_at.desc())
                )

                if model:
                    stmt = stmt.where(Model.name == model)
                if provider:
                    stmt = stmt.where(Request.provider == provider)
                if errors_only:
                    stmt = stmt.where(Request.is_error == True)

                count_stmt = select(func.count(Request.id))
                if model:
                    count_stmt = count_stmt.join(Model, Request.model_id == Model.id).where(Model.name == model)
                if provider:
                    count_stmt = count_stmt.where(Request.provider == provider)
                if errors_only:
                    count_stmt = count_stmt.where(Request.is_error == True)

                total_result = await session.execute(count_stmt)
                total = total_result.scalar()

                stmt = stmt.limit(limit).offset(offset)
                result = await session.execute(stmt)
                rows = result.all()

                return {
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                    "requests": [
                        {
                            "id": r.id,
                            "provider": r.provider,
                            "api_key": r.api_key,
                            "model": r.model_name,
                            "action": r.action,
                            "http_method": r.http_method,
                            "url_path": r.url_path,
                            "client_ip": r.client_ip,
                            "status_code": r.status_code,
                            "latency_ms": r.latency_ms,
                            "attempt_count": r.attempt_count,
                            "prompt_tokens": r.prompt_tokens,
                            "candidates_tokens": r.candidates_tokens,
                            "total_tokens": r.total_tokens,
                            "is_error": r.is_error,
                            "error_detail": r.error_detail,
                            "request_size": r.request_size,
                            "response_size": r.response_size,
                            "created_at": r.created_at.isoformat() if r.created_at else None,
                        }
                        for r in rows
                    ],
                }
        except Exception as e:
            logger.error(f"Failed to get requests log: {e}")
            return {"error": str(e)}

    async def get_model_stats(self, hours: int = 24) -> dict:
        try:
            async with self._session_factory() as session:
                since = datetime.now(timezone.utc) - timedelta(hours=hours)
                stmt = (
                    select(
                        Model.name,
                        Model.provider,
                        func.count(Request.id).label("total_requests"),
                        func.count(case((Request.is_error == True, 1))).label("total_errors"),
                        func.avg(Request.latency_ms).label("avg_latency_ms"),
                        func.sum(Request.total_tokens).label("total_tokens"),
                    )
                    .join(Model, Request.model_id == Model.id)
                    .where(Request.created_at >= since)
                    .group_by(Model.name, Model.provider)
                    .order_by(func.count(Request.id).desc())
                )
                result = await session.execute(stmt)
                rows = result.all()
                return {
                    "period_hours": hours,
                    "models": [
                        {
                            "name": r.name,
                            "provider": r.provider,
                            "total_requests": r.total_requests,
                            "total_errors": r.total_errors,
                            "avg_latency_ms": round(float(r.avg_latency_ms or 0), 2),
                            "total_tokens": r.total_tokens or 0,
                        }
                        for r in rows
                    ],
                }
        except Exception as e:
            logger.error(f"Failed to get model stats: {e}")
            return {"error": str(e)}

    async def get_token_stats(self, hours: int = 24, group_by: str = "hour") -> dict:
        try:
            async with self._session_factory() as session:
                since = datetime.now(timezone.utc) - timedelta(hours=hours)

                if group_by == "model":
                    stmt = (
                        select(
                            Model.name.label("group_key"),
                            func.sum(Request.prompt_tokens).label("prompt_tokens"),
                            func.sum(Request.candidates_tokens).label("candidates_tokens"),
                            func.sum(Request.total_tokens).label("total_tokens"),
                            func.count(Request.id).label("request_count"),
                        )
                        .join(Model, Request.model_id == Model.id)
                        .where(Request.created_at >= since)
                        .group_by(Model.name)
                        .order_by(func.sum(Request.total_tokens).desc())
                    )
                elif group_by == "key":
                    stmt = (
                        select(
                            ApiKey.key_id.label("group_key"),
                            func.sum(Request.prompt_tokens).label("prompt_tokens"),
                            func.sum(Request.candidates_tokens).label("candidates_tokens"),
                            func.sum(Request.total_tokens).label("total_tokens"),
                            func.count(Request.id).label("request_count"),
                        )
                        .join(ApiKey, Request.api_key_id == ApiKey.id)
                        .where(Request.created_at >= since)
                        .group_by(ApiKey.key_id)
                        .order_by(func.sum(Request.total_tokens).desc())
                    )
                elif group_by == "day":
                    # NOTE: date_trunc is PostgreSQL-only; not testable on SQLite
                    stmt = (
                        select(
                            func.date_trunc("day", Request.created_at).label("group_key"),
                            func.sum(Request.prompt_tokens).label("prompt_tokens"),
                            func.sum(Request.candidates_tokens).label("candidates_tokens"),
                            func.sum(Request.total_tokens).label("total_tokens"),
                            func.count(Request.id).label("request_count"),
                        )
                        .where(Request.created_at >= since)
                        .group_by(text("1"))
                        .order_by(text("1"))
                    )
                else:  # hour
                    # NOTE: date_trunc is PostgreSQL-only; not testable on SQLite
                    stmt = (
                        select(
                            func.date_trunc("hour", Request.created_at).label("group_key"),
                            func.sum(Request.prompt_tokens).label("prompt_tokens"),
                            func.sum(Request.candidates_tokens).label("candidates_tokens"),
                            func.sum(Request.total_tokens).label("total_tokens"),
                            func.count(Request.id).label("request_count"),
                        )
                        .where(Request.created_at >= since)
                        .group_by(text("1"))
                        .order_by(text("1"))
                    )

                result = await session.execute(stmt)
                rows = result.all()

                return {
                    "period_hours": hours,
                    "group_by": group_by,
                    "data": [
                        {
                            "group": str(r.group_key) if r.group_key else None,
                            "prompt_tokens": r.prompt_tokens or 0,
                            "candidates_tokens": r.candidates_tokens or 0,
                            "total_tokens": r.total_tokens or 0,
                            "request_count": r.request_count,
                        }
                        for r in rows
                    ],
                }
        except Exception as e:
            logger.error(f"Failed to get token stats: {e}")
            return {"error": str(e)}

    async def cleanup(self, days: int = 30) -> dict:
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
                    stmt = delete(Request).where(Request.created_at < cutoff)
                    result = await session.execute(stmt)
                    return {"deleted": result.rowcount, "older_than_days": days}
        except Exception as e:
            logger.error(f"Failed to cleanup stats: {e}")
            return {"error": str(e)}


# Will be initialized in app lifespan
stats_service: StatsService | None = None
