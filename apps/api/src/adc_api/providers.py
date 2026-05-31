from __future__ import annotations

import os
from typing import Protocol

from adc_api.schemas import RawFinding, ReviewOutput

REVIEW_SYSTEM_PROMPT = (
    "You are a senior code reviewer. Analyze the {language} code and report concrete "
    "issues across security, performance, logic, and style. For each issue give a short "
    "title, a clear description, an actionable recommendation, and the 1-based line range. "
    "Only report real issues."
)


class ModelProvider(Protocol):
    name: str
    model: str

    async def review(self, code: str, language: str) -> list[RawFinding]: ...


class MockProvider:
    """Deterministic provider for tests/CI (no network)."""

    name = "core-reviewer"
    model = "mock"

    def __init__(self, seed: list[dict] | None = None) -> None:
        self._seed = seed or []

    async def review(self, code: str, language: str) -> list[RawFinding]:
        return [RawFinding(**item) for item in self._seed]


class OllamaProvider:
    """OpenAI-compatible provider (Ollama by default; works for any OpenAI-compatible endpoint)."""

    name = "core-reviewer"

    def __init__(self, base_url: str, model: str, api_key: str = "ollama") -> None:
        import instructor
        from openai import AsyncOpenAI

        self.model = model
        self._client = instructor.from_openai(AsyncOpenAI(base_url=base_url, api_key=api_key))

    async def review(self, code: str, language: str) -> list[RawFinding]:
        out: ReviewOutput = await self._client.chat.completions.create(
            model=self.model,
            response_model=ReviewOutput,
            messages=[
                {"role": "system", "content": REVIEW_SYSTEM_PROMPT.format(language=language)},
                {"role": "user", "content": f"```{language}\n{code}\n```"},
            ],
        )
        return out.findings


def build_provider() -> ModelProvider:
    kind = os.getenv("ADC_MODEL_PROVIDER", "ollama")
    model = os.getenv("ADC_MODEL", "qwen2.5-coder:7b")
    if kind == "mock":
        return MockProvider(seed=[{
            "category": "security", "severity": "high", "title": "SQL injection vulnerability",
            "description": "User input concatenated into SQL string.",
            "recommendation": "Use parameterized queries.", "start_line": 2, "end_line": 2,
        }])
    if kind == "ollama":
        return OllamaProvider(os.getenv("ADC_OLLAMA_BASE_URL", "http://localhost:11434/v1"), model)
    if kind == "openai":
        return OllamaProvider(
            os.getenv("ADC_OPENAI_BASE_URL", "https://api.openai.com/v1"),
            model,
            api_key=os.environ["ADC_OPENAI_API_KEY"],
        )
    raise ValueError(f"unknown provider: {kind}")
