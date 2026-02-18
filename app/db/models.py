from datetime import datetime, timezone
from sqlalchemy import (
    Boolean, DateTime, Index, Integer, JSON, SmallInteger, String, Text,
    ForeignKey, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Use JSONB on PostgreSQL, fall back to JSON on other dialects (e.g. SQLite for tests)
JSONType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    key_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class Model(Base):
    __tablename__ = "models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    provider: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class Request(Base):
    __tablename__ = "requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    api_key_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True
    )
    model_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("models.id", ondelete="SET NULL"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    action: Mapped[str | None] = mapped_column(String(64), nullable=True)
    http_method: Mapped[str] = mapped_column(String(8), nullable=False, default="POST")
    url_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    client_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status_code: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    candidates_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_body: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    response_body: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    is_error: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        Index("ix_requests_created_at", "created_at"),
        Index("ix_requests_api_key_id", "api_key_id"),
        Index("ix_requests_model_id", "model_id"),
        Index("ix_requests_is_error", "is_error", postgresql_where=text("is_error = TRUE")),
        Index("ix_requests_key_time", "api_key_id", "created_at"),
        Index("ix_requests_model_time", "model_id", "created_at"),
    )
