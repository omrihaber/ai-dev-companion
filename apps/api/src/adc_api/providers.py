from __future__ import annotations

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
    # Runtime (UI-editable) config overrides env; explicit args still win (per-agent overrides).
    from adc_api.runtime_config import effective

    eff = effective()
    kind = kind or eff["provider"]
    model = model or eff["model"]
    if kind == "mock":
        return MockProvider(seed=[{
            "category": "security", "severity": "high", "title": "SQL injection vulnerability",
            "description": "User input concatenated into SQL string.",
            "recommendation": "Use parameterized queries.", "start_line": 2, "end_line": 2,
        }])
    if kind == "ollama":
        return OllamaProvider(eff["baseUrl"] or "http://localhost:11434/v1", model)
    if kind == "openai":
        key = eff["apiKey"]
        if not key:
            raise ValueError("OpenAI API key not set (set it in Settings or ADC_OPENAI_API_KEY)")
        base = eff["baseUrl"] or "https://api.openai.com/v1"
        return OllamaProvider(base, model, api_key=key)
    if kind == "anthropic":
        key = eff["apiKey"]
        if not key:
            raise ValueError("Anthropic API key not set (set it in Settings or env)")
        return AnthropicProvider(model, key)
    raise ValueError(f"unknown provider: {kind}")
