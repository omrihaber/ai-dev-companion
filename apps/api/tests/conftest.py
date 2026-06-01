import pytest


@pytest.fixture(autouse=True)
def _disable_scanners(monkeypatch):
    """Unit/API tests never invoke real scanner containers. Tests that specifically exercise
    scanners override this (e.g. by injecting a fake scanner or re-setting settings.scanners)."""
    from adc_api.settings import settings
    monkeypatch.setattr(settings, "scanners", "")
