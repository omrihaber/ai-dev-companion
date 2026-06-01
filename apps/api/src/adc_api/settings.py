from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ADC_", extra="ignore")

    # "infra" = Postgres + Redis + arq worker (production). "memory" = in-process repo/bus +
    # inline execution (no services) — used by the e2e and a quick local/demo run.
    backend: str = "infra"
    database_url: str = "postgresql+asyncpg://adc:adc@localhost:5432/adc"
    redis_url: str = "redis://localhost:6379"
    scanners: str = "semgrep,bandit"   # comma list; empty disables the scanner layer
    scanner_timeout: int = 60          # seconds per container run
    max_code_bytes: int = 100_000
    max_code_lines: int = 2_000

    # Multi-file review
    agent_file_cap: int = 25          # default size of the agent deep-review set
    agent_file_ceiling: int = 150     # hard max even when files are explicitly marked
    file_concurrency: int = 4         # files reviewed by agents in parallel
    max_files: int = 2000             # ingestion cap (file count)
    max_total_bytes: int = 50_000_000 # ingestion cap (total uncompressed bytes)
    max_file_bytes: int = 512_000     # ingestion cap (per file)
    # Comma list of path globs dropped before review (dependencies, VCS, build output, binaries).
    ignore_globs: str = (
        ".git/*,node_modules/*,dist/*,build/*,vendor/*,__pycache__/*,"
        "*.lock,*.min.js,*.map,*.png,*.jpg,*.jpeg,*.gif,*.pdf,*.zip,*.so,*.dll,*.exe,*.bin"
    )
    work_root: str = ".adc_work"      # base dir for per-review corpus work dirs
    config_file: str = ".adc_config.json"  # runtime, UI-editable provider overrides (over env)


settings = Settings()
