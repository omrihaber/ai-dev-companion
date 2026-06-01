from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# JSONB on Postgres, JSON elsewhere (SQLite in tests).
_JSON = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class ReviewRow(Base):
    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String, default="queued")
    language: Mapped[str] = mapped_column(String)
    model: Mapped[str] = mapped_column(String, default="pending")
    summary: Mapped[str] = mapped_column(String, default="")
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    findings: Mapped[list] = mapped_column(_JSON, default=list)
    coverage: Mapped[dict | None] = mapped_column(_JSON, nullable=True)
    parent_review_id: Mapped[str | None] = mapped_column(String, nullable=True)
