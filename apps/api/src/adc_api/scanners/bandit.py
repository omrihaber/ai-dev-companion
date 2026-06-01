from __future__ import annotations

import json

from adc_core.models import Finding

from adc_api.scanners.docker_runner import docker_available, run_in_container
from adc_api.scanners.sarif import sarif_to_findings


class BanditScanner:
    name = "bandit"
    languages = {"python"}

    def __init__(self, timeout: int = 60, image: str = "adc-bandit:latest") -> None:
        self._timeout = timeout
        self._image = image

    async def scan_path(self, work_dir: str) -> list[Finding]:
        if not await docker_available():
            return []
        try:
            out = await run_in_container(
                image=self._image,
                cmd=["bandit", "-r", "/src", "-f", "sarif"],
                host_dir=work_dir, timeout=self._timeout,
            )
        except Exception:  # noqa: BLE001
            return []
        try:
            return sarif_to_findings(json.loads(out), self.name)
        except (ValueError, KeyError):
            return []
