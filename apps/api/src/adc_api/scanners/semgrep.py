from __future__ import annotations

import json

from adc_core.models import Finding

from adc_api.scanners.docker_runner import docker_available, run_in_container
from adc_api.scanners.sarif import sarif_to_findings


class SemgrepScanner:
    name = "semgrep"
    languages = {"python", "typescript", "java"}

    def __init__(self, timeout: int = 60, image: str = "semgrep/semgrep:latest") -> None:
        self._timeout = timeout
        self._image = image

    async def scan_path(self, work_dir: str) -> list[Finding]:
        if not await docker_available():
            return []
        try:
            # network="bridge": semgrep fetches its rule registry (--config auto) over the
            # network; the submitted code is mounted read-only and never executed.
            out = await run_in_container(
                image=self._image,
                cmd=["semgrep", "scan", "--sarif", "--quiet", "--config", "auto", "/src"],
                host_dir=work_dir, timeout=self._timeout, network="bridge",
            )
        except Exception:  # noqa: BLE001 — any scan failure degrades to no findings
            return []
        try:
            return sarif_to_findings(json.loads(out), self.name)
        except (ValueError, KeyError):
            return []
