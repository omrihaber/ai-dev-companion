from adc_api.settings import Settings


def test_settings_defaults_and_env_prefix(monkeypatch):
    s = Settings()
    assert s.database_url.startswith("postgresql+asyncpg://")
    assert s.redis_url.startswith("redis://")
    monkeypatch.setenv("ADC_REDIS_URL", "redis://example:6380")
    assert Settings().redis_url == "redis://example:6380"


def test_multifile_settings_defaults():
    from adc_api.settings import Settings

    s = Settings()
    assert s.agent_file_cap == 25
    assert s.agent_file_ceiling == 150
    assert s.file_concurrency == 4
    assert s.max_files == 2000
    assert s.max_total_bytes == 50_000_000
    assert s.max_file_bytes == 512_000
    assert "node_modules" in s.ignore_globs
    assert s.work_root  # non-empty default path
