from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ADC_", extra="ignore")

    # "infra" = Postgres + Redis + arq worker (production). "memory" = in-process repo/bus +
    # inline execution (no services) — used by the e2e and a quick local/demo run.
    backend: str = "infra"
    database_url: str = "postgresql+asyncpg://adc:adc@localhost:5432/adc"
    redis_url: str = "redis://localhost:6379"
    max_code_bytes: int = 100_000
    max_code_lines: int = 2_000


settings = Settings()
