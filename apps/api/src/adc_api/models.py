"""Available models for the configured provider — powers the in-review model dropdown.

Best-effort: queries the provider's OpenAI-compatible /models endpoint (openai/ollama) and falls
back to a curated list. Provider + key come from env; this only enumerates model choices.
"""
from __future__ import annotations

import os

_FALLBACK: dict[str, list[str]] = {
    "openai": ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1", "o3-mini"],
    "anthropic": ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
    "ollama": ["qwen2.5-coder:7b", "llama3.1:8b"],
    "mock": ["mock"],
}


async def _fetch_openai_compatible(base: str, key: str) -> list[str]:
    from openai import AsyncOpenAI

    resp = await AsyncOpenAI(base_url=base, api_key=key).models.list()
    return [m.id for m in resp.data]


async def available() -> dict:
    kind = os.getenv("ADC_MODEL_PROVIDER", "ollama")
    current = os.getenv("ADC_MODEL", "qwen2.5-coder:7b")
    models = list(_FALLBACK.get(kind, [current]))

    if kind in ("openai", "ollama"):
        try:
            if kind == "openai":
                base = os.getenv("ADC_OPENAI_BASE_URL", "https://api.openai.com/v1")
                key = os.environ["ADC_OPENAI_API_KEY"]
            else:
                base = os.getenv("ADC_OLLAMA_BASE_URL", "http://localhost:11434/v1")
                key = "ollama"
            ids = await _fetch_openai_compatible(base, key)
            if kind == "openai":  # keep chat-capable ids only
                ids = [i for i in ids if i.startswith(("gpt", "o1", "o3", "o4", "chatgpt"))]
            if ids:
                models = sorted(set(ids))
        except Exception:  # noqa: BLE001 — network/key issues fall back to the curated list
            pass

    if current and current not in models:
        models = [current, *models]
    return {"provider": kind, "current": current, "models": models}
