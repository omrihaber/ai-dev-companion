from __future__ import annotations

from typing import Protocol

from adc_core.models import Finding, ReviewResult, ReviewStatus
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from adc_api.db.models import ReviewRow


def _row_to_result(row: ReviewRow) -> ReviewResult:
    return ReviewResult(
        id=row.id,
        status=row.status,  # type: ignore[arg-type]
        language=row.language,
        model=row.model,
        findings=[Finding.model_validate(f) for f in (row.findings or [])],
        summary=row.summary,
        created_at=row.created_at,
        duration_ms=row.duration_ms,
        error=row.error,
    )


class ReviewRepository(Protocol):
    async def create(self, review_id: str, language: str) -> None: ...
    async def set_status(self, review_id: str, status: ReviewStatus) -> None: ...
    async def save_result(self, result: ReviewResult) -> None: ...
    async def get(self, review_id: str) -> ReviewResult | None: ...
    async def list_all(self) -> list[ReviewResult]: ...


class InMemoryReviewRepository:
    def __init__(self) -> None:
        self._d: dict[str, ReviewResult] = {}

    async def create(self, review_id: str, language: str) -> None:
        self._d[review_id] = ReviewResult(id=review_id, language=language, model="pending")

    async def set_status(self, review_id: str, status: ReviewStatus) -> None:
        if review_id in self._d:
            self._d[review_id].status = status

    async def save_result(self, result: ReviewResult) -> None:
        existing = self._d.get(result.id)
        if existing is not None:
            result.created_at = existing.created_at
        self._d[result.id] = result

    async def get(self, review_id: str) -> ReviewResult | None:
        return self._d.get(review_id)

    async def list_all(self) -> list[ReviewResult]:
        return sorted(self._d.values(), key=lambda r: r.created_at, reverse=True)


class SqlReviewRepository:
    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._sf = session_factory

    async def create(self, review_id: str, language: str) -> None:
        async with self._sf() as s, s.begin():
            s.add(ReviewRow(id=review_id, status="queued", language=language))

    async def set_status(self, review_id: str, status: ReviewStatus) -> None:
        async with self._sf() as s, s.begin():
            row = await s.get(ReviewRow, review_id)
            if row is not None:
                row.status = status

    async def save_result(self, result: ReviewResult) -> None:
        async with self._sf() as s, s.begin():
            row = await s.get(ReviewRow, result.id)
            if row is None:
                row = ReviewRow(id=result.id, created_at=result.created_at)
                s.add(row)
            row.status = result.status
            row.language = result.language
            row.model = result.model
            row.summary = result.summary
            row.error = result.error
            row.duration_ms = result.duration_ms
            row.findings = [f.model_dump(by_alias=True, mode="json") for f in result.findings]

    async def get(self, review_id: str) -> ReviewResult | None:
        async with self._sf() as s:
            row = await s.get(ReviewRow, review_id)
            return _row_to_result(row) if row is not None else None

    async def list_all(self) -> list[ReviewResult]:
        async with self._sf() as s:
            rows = (
                await s.execute(select(ReviewRow).order_by(ReviewRow.created_at.desc()))
            ).scalars().all()
            return [_row_to_result(r) for r in rows]
