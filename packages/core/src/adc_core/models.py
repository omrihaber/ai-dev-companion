from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

Category = Literal["security", "performance", "logic", "quality", "docs", "tests", "syntax"]
Severity = Literal["info", "low", "medium", "high", "critical"]
ReviewStatus = Literal[
    "queued", "validating", "analyzing", "finalizing", "done", "failed"
]

class _Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

class Location(_Camel):
    file: str | None = None
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    start_col: int | None = None
    end_col: int | None = None

class Source(_Camel):
    type: Literal["agent", "tool"]
    name: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    rule_id: str | None = None
    url: str | None = None

class Finding(_Camel):
    id: str
    category: Category
    severity: Severity
    title: str
    description: str
    recommendation: str
    location: Location
    sources: list[Source] = Field(default_factory=list)
    code_snippet: str | None = None

class ReviewResult(_Camel):
    id: str
    status: ReviewStatus = "queued"
    language: str
    model: str
    findings: list[Finding] = Field(default_factory=list)
    summary: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    duration_ms: int | None = None
    error: str | None = None
