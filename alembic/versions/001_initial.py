"""Initial migration: api_keys, models, requests tables

Revision ID: 001
Revises:
Create Date: 2025-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("key_id", sa.String(255), nullable=False),
        sa.Column("label", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_id"),
    )

    op.create_table(
        "models",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("provider", sa.String(16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "requests",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("api_key_id", sa.Integer(), sa.ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True),
        sa.Column("model_id", sa.Integer(), sa.ForeignKey("models.id", ondelete="SET NULL"), nullable=True),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("action", sa.String(64), nullable=True),
        sa.Column("http_method", sa.String(8), nullable=False, server_default="POST"),
        sa.Column("url_path", sa.String(1024), nullable=False),
        sa.Column("client_ip", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("status_code", sa.SmallInteger(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("attempt_count", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("candidates_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("request_body", postgresql.JSONB(), nullable=True),
        sa.Column("response_body", postgresql.JSONB(), nullable=True),
        sa.Column("is_error", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("request_size", sa.Integer(), nullable=True),
        sa.Column("response_size", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("ix_requests_created_at", "requests", ["created_at"])
    op.create_index("ix_requests_api_key_id", "requests", ["api_key_id"])
    op.create_index("ix_requests_model_id", "requests", ["model_id"])
    op.create_index(
        "ix_requests_is_error", "requests", ["is_error"],
        postgresql_where=sa.text("is_error = TRUE"),
    )
    op.create_index("ix_requests_key_time", "requests", ["api_key_id", "created_at"])
    op.create_index("ix_requests_model_time", "requests", ["model_id", "created_at"])


def downgrade() -> None:
    op.drop_table("requests")
    op.drop_table("models")
    op.drop_table("api_keys")
