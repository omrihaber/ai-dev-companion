import pytest
from adc_api.scanners import build_scanners
from adc_api.scanners.bandit import BanditScanner
from adc_api.scanners.semgrep import SemgrepScanner


@pytest.mark.asyncio
async def test_bandit_skips_unsupported_language():
    assert await BanditScanner().scan("x = 1\n", "java") == []  # returns before any docker call


@pytest.mark.asyncio
async def test_semgrep_skips_when_docker_unavailable(monkeypatch):
    import adc_api.scanners.semgrep as mod

    async def _unavailable() -> bool:
        return False

    monkeypatch.setattr(mod, "docker_available", _unavailable)
    assert await SemgrepScanner().scan("x = 1\n", "python") == []


def test_build_scanners_from_settings(monkeypatch):
    from adc_api.settings import settings
    monkeypatch.setattr(settings, "scanners", "semgrep,bandit")
    assert {s.name for s in build_scanners()} == {"semgrep", "bandit"}


def test_build_scanners_empty_disables(monkeypatch):
    from adc_api.settings import settings
    monkeypatch.setattr(settings, "scanners", "")
    assert build_scanners() == []
