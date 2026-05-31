from __future__ import annotations

import os
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class ModelProvider(Protocol):
    name: str
    model: str

    async def complete_structured(
        self, *, system: str, user: str, response_model: type[T]
    ) -> T: ...


class MockProvider:
    """Deterministic provider for tests/CI (no network). Returns seeded findings."""

    name = "mock"
    model = "mock"

    def __init__(self, seed: list[dict] | None = None) -> None:
        self._seed = seed or []

    async def complete_structured(self, *, system: str, user: str, response_model: type[T]) -> T:
        return response_model.model_validate({"findings": self._seed})


class OllamaProvider:
    """OpenAI-compatible provider (Ollama default). JSON mode for reliable structured output."""

    name = "openai-compatible"

    def __init__(self, base_url: str, model: str, api_key: str = "ollama") -> None:
        import instructor
        from openai import AsyncOpenAI

        self.model = model
        self._client = instructor.from_openai(
            AsyncOpenAI(base_url=base_url, api_key=api_key), mode=instructor.Mode.JSON
        )

    async def complete_structured(self, *, system: str, user: str, response_model: type[T]) -> T:
        return await self._client.chat.completions.create(
            model=self.model,
            response_model=response_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )


class AnthropicProvider:
    """Native Anthropic provider via instructor."""

    name = "anthropic"

    def __init__(self, model: str, api_key: str, max_tokens: int = 2048) -> None:
        import instructor
        from anthropic import AsyncAnthropic

        self.model = model
        self._max_tokens = max_tokens
        self._client = instructor.from_anthropic(AsyncAnthropic(api_key=api_key))

    async def complete_structured(self, *, system: str, user: str, response_model: type[T]) -> T:
        return await self._client.messages.create(
            model=self.model,
            max_tokens=self._max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            response_model=response_model,
        )


def build_provider(model: str | None = None, kind: str | None = None) -> ModelProvider:
    kind = kind or os.getenv("ADC_MODEL_PROVIDER", "ollama")
    model = model or os.getenv("ADC_MODEL", "qwen2.5-coder:7b")
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
            model, api_key=os.environ["ADC_OPENAI_API_KEY"],
        )
    if kind == "anthropic":
        return AnthropicProvider(model, os.environ["ADC_ANTHROPIC_API_KEY"])
    raise ValueError(f"unknown provider: {kind}")
