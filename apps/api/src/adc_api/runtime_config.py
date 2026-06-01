"""UI-editable runtime provider config, persisted to a JSON file (overrides env).

The API writes it; the worker (a separate process in the infra backend) reads it per review via
`build_provider`, so changing the provider/model/key in the UI takes effect on the next review
without a restart. Keys: provider, model, baseUrl, apiKey.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from adc_api.settings import settings

_KEYS = ("provider", "model", "baseUrl", "apiKey")


def _path() -> Path:
    return Path(settings.config_file)


def load() -> dict[str, str]:
    try:
        data = json.loads(_path().read_text("utf-8"))
        return {k: str(v) for k, v in data.items() if k in _KEYS and v}
    except (FileNotFoundError, ValueError, OSError):
        return {}


def save(values: dict[str, str]) -> dict[str, str]:
    """Merge the given keys into the stored config (empty/None values are ignored)."""
    current = load()
    for k in _KEYS:
        v = values.get(k)
        if v:
            current[k] = str(v)
    _path().write_text(json.dumps(current, indent=2), encoding="utf-8")
    return current


def effective() -> dict[str, str | None]:
    """Stored config over env defaults — the values build_provider actually uses."""
    cfg = load()
    return {
        "provider": cfg.get("provider") or os.getenv("ADC_MODEL_PROVIDER", "ollama"),
        "model": cfg.get("model") or os.getenv("ADC_MODEL", "qwen2.5-coder:7b"),
        "baseUrl": cfg.get("baseUrl")
        or os.getenv("ADC_OPENAI_BASE_URL")
        or os.getenv("ADC_OLLAMA_BASE_URL"),
        "apiKey": cfg.get("apiKey")
        or os.getenv("ADC_OPENAI_API_KEY")
        or os.getenv("ADC_ANTHROPIC_API_KEY"),
    }
