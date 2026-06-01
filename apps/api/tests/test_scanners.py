import json as _json

import pytest
from adc_api.scanners import build_scanners
from adc_api.scanners.bandit import BanditScanner
from adc_api.scanners.semgrep import SemgrepScanner


@pytest.mark.asyncio
async def test_semgrep_skips_when_docker_unavailable(monkeypatch):
    import adc_api.scanners.semgrep as mod

    async def _unavailable() -> bool:
        return False

    monkeypatch.setattr(mod, "docker_available", _unavailable)
    assert await SemgrepScanner().scan_path("/tmp/fake_dir") == []


@pytest.mark.asyncio
async def test_bandit_skips_when_docker_unavailable(monkeypatch):
    import adc_api.scanners.bandit as mod

    async def _unavailable() -> bool:
        return False

    monkeypatch.setattr(mod, "docker_available", _unavailable)
    assert await BanditScanner().scan_path("/tmp/fake_dir") == []


def test_build_scanners_from_settings(monkeypatch):
    from adc_api.settings import settings
    monkeypatch.setattr(settings, "scanners", "semgrep,bandit")
    assert {s.name for s in build_scanners()} == {"semgrep", "bandit"}


def test_build_scanners_empty_disables(monkeypatch):
    from adc_api.settings import settings
    monkeypatch.setattr(settings, "scanners", "")
    assert build_scanners() == []


@pytest.mark.asyncio
async def test_semgrep_scan_path_returns_findings_with_files(monkeypatch, tmp_path):
    sarif = {
        "runs": [{
            "tool": {"driver": {"rules": []}},
            "results": [{
                "ruleId": "python.sqli", "level": "error",
                "message": {"text": "SQL injection"},
                "locations": [{"physicalLocation": {
                    "artifactLocation": {"uri": "app/auth.py"},
                    "region": {"startLine": 2, "endLine": 2},
                }}],
            }],
        }]
    }

    async def _true():
        return True

    async def _ret(**kwargs):
        return _json.dumps(sarif)

    monkeypatch.setattr("adc_api.scanners.semgrep.docker_available", _true)
    monkeypatch.setattr("adc_api.scanners.semgrep.run_in_container", _ret)
    out = await SemgrepScanner().scan_path(str(tmp_path))
    assert out and out[0].location.file == "app/auth.py"
