from __future__ import annotations

from typing import Literal

from adc_core.models import ReviewStatus
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class _Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

class FileInput(_Camel):
    path: str
    content: str
    language: str | None = None

class ReviewRequest(_Camel):
    language: str | None = None        # legacy single-snippet
    code: str | None = None            # legacy single-snippet
    files: list[FileInput] = Field(default_factory=list)
    marked: list[str] = Field(default_factory=list)
    model: str | None = None           # per-review model choice (provider/key come from env)

class RawFinding(_Camel):
    """Shape the LLM returns; ReviewService converts these into Findings."""
    category: Literal["security", "performance", "logic", "quality", "docs", "tests"]
    severity: Literal["info", "low", "medium", "high", "critical"]
    title: str
    description: str
    recommendation: str
    start_line: int = 1
    end_line: int = 1

class ReviewOutput(_Camel):
    findings: list[RawFinding] = Field(default_factory=list)

class ProgressEvent(_Camel):
    review_id: str
    stage: ReviewStatus
    percent: int | None = None
    sub_status: dict[str, str] = Field(default_factory=dict)
    message: str | None = None
