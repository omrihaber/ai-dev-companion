from __future__ import annotations

import json
import tempfile
from pathlib import Path

from adc_core.models import Finding

from adc_api.scanners.docker_runner import docker_available, run_in_container
from adc_api.scanners.sarif import sarif_to_findings

_EXT = {"python": "py", "typescript": "ts", "java": "java"}


class SemgrepScanner:
    name = "semgrep"
    languages = {"python", "typescript", "java"}

    def __init__(self, timeout: int = 60, image: str = "semgrep/semgrep:latest") -> None:
        self._timeout = timeout
        self._image = image

    async def scan(self, code: str, language: str) -> list[Finding]:
        if language not in self.languages or not await docker_available():
            return []
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / f"snippet.{_EXT[language]}").write_text(code)
            try:
                # network="bridge": semgrep fetches its rule registry (--config auto) over the
                # network; the submitted code is mounted read-only and never executed.
                out = await run_in_container(
                    image=self._image,
                    cmd=["semgrep", "scan", "--sarif", "--quiet", "--config", "auto", "/src"],
                    host_dir=d, timeout=self._timeout, network="bridge",
                )
            except Exception:  # noqa: BLE001 — any scan failure degrades to no findings
                return []
        try:
            return sarif_to_findings(json.loads(out), self.name)
        except (ValueError, KeyError):
            return []
