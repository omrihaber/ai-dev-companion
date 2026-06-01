from __future__ import annotations

from typing import Protocol

from adc_core.models import Finding


class Scanner(Protocol):
    name: str
    languages: set[str]

    async def scan_path(self, work_dir: str) -> list[Finding]: ...


def build_scanners() -> list[Scanner]:
    """Build the enabled scanners from Settings.scanners (comma list; empty => none)."""
    from adc_api.scanners.bandit import BanditScanner
    from adc_api.scanners.semgrep import SemgrepScanner
    from adc_api.settings import settings

    registry = {
        "semgrep": lambda: SemgrepScanner(timeout=settings.scanner_timeout),
        "bandit": lambda: BanditScanner(timeout=settings.scanner_timeout),
    }
    scanners: list[Scanner] = []
    for name in (n.strip() for n in settings.scanners.split(",")):
        if name in registry:
            scanners.append(registry[name]())
    return scanners
