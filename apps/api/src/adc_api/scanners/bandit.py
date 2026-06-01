from __future__ import annotations

import json
import tempfile
from pathlib import Path

from adc_core.models import Finding

from adc_api.scanners.docker_runner import docker_available, run_in_container
from adc_api.scanners.sarif import sarif_to_findings


class BanditScanner:
    name = "bandit"
    languages = {"python"}

    def __init__(self, timeout: int = 60, image: str = "adc-bandit:latest") -> None:
        self._timeout = timeout
        self._image = image

    async def scan(self, code: str, language: str) -> list[Finding]:
        if language not in self.languages or not await docker_available():
            return []
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "snippet.py").write_text(code)
            try:
                out = await run_in_container(
                    image=self._image,
                    cmd=["bandit", "-r", "/src", "-f", "sarif"],
                    host_dir=d, timeout=self._timeout,
                )
            except Exception:  # noqa: BLE001
                return []
        try:
            return sarif_to_findings(json.loads(out), self.name)
        except (ValueError, KeyError):
            return []
