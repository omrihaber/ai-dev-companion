from adc_api.settings import Settings


def test_settings_defaults_and_env_prefix(monkeypatch):
    s = Settings()
    assert s.database_url.startswith("postgresql+asyncpg://")
    assert s.redis_url.startswith("redis://")
    monkeypatch.setenv("ADC_REDIS_URL", "redis://example:6380")
    assert Settings().redis_url == "redis://example:6380"
