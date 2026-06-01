# Inc 5: SARIF Scanners + Multi-Source Citations — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run Semgrep + Bandit as sandboxed-Docker scanner nodes in the existing LangGraph fan-out so their SARIF findings merge into the same cited cards as the agents' (one issue → `security-agent` + `semgrep` + `bandit`), and drop the now-unused `enriching` status.

**Architecture:** A `Scanner` seam (`name`, `languages`, `async scan`) with `SemgrepScanner`/`BanditScanner` adapters that run their image via `docker run --rm --network=none`, parse SARIF through one shared `sarif_to_findings` mapper, and plug into `build_graph(agents, scanners)` as parallel nodes feeding the existing aggregator. Scanners are injectable (tests use a fake; gated integration uses real Docker) and degrade to `[]` when unavailable.

**Tech Stack:** Docker (Semgrep `semgrep/semgrep`, Bandit via a local `infra/docker/bandit.Dockerfile`), Python `asyncio` subprocess, SARIF, pytest. No new Python runtime deps (scanners run in containers).

**Conventions:** TDD; run Python via `uv` from repo root; branch `inc5-sarif-scanners` (already off `main`). API/Findings contract unchanged except `ReviewStatus` loses `enriching`.

---

## File Structure

```
apps/api/src/adc_api/
├─ settings.py                 # MODIFY: + scanners (default "semgrep,bandit") + scanner_timeout
├─ scanners/
│  ├─ __init__.py              # NEW: Scanner Protocol + build_scanners() registry
│  ├─ sarif.py                 # NEW: sarif_to_findings(sarif, scanner_name)
│  ├─ docker_runner.py         # NEW: docker_available() + run_in_container(...)
│  ├─ semgrep.py               # NEW: SemgrepScanner
│  └─ bandit.py                # NEW: BanditScanner
├─ graph.py                    # MODIFY: build_graph(agents, scanners=()) — add scanner nodes
└─ review_service.py           # MODIFY: ReviewService(agents, scanners); node sub-status incl scanners; drop enriching comment
packages/core/src/adc_core/models.py   # MODIFY: ReviewStatus drops "enriching"
apps/web/src/api/types.ts              # MODIFY: ReviewStatus drops "enriching"
apps/web/src/components/ProgressStepper.tsx  # MODIFY: STAGES drop "enriching"
apps/web/playwright.config.ts          # MODIFY: e2e api server sets ADC_SCANNERS=""
infra/docker/bandit.Dockerfile         # NEW: python:3.12-slim + bandit[sarif]
Taskfile.yml, README.md, CREDITS.md    # MODIFY: scanners-build task + docs + attribution
apps/api/tests/{test_sarif,test_scanners,test_graph,test_integration,...}.py
packages/core/tests/test_models.py     # MODIFY: assert enriching rejected
```

---

### Task 1: Drop the unused `enriching` status + add scanner Settings

**Files:** Modify `packages/core/src/adc_core/models.py`, `apps/web/src/api/types.ts`, `apps/web/src/components/ProgressStepper.tsx`, `apps/api/src/adc_api/review_service.py`, `apps/api/src/adc_api/settings.py`; Test `packages/core/tests/test_models.py`

- [ ] **Step 1: Add a failing test to `packages/core/tests/test_models.py`** (append):

```python
def test_review_status_no_longer_allows_enriching():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ReviewResult(id="r1", language="python", model="m", status="enriching")
```

- [ ] **Step 2: Run → fails** — `uv run pytest packages/core/tests/test_models.py::test_review_status_no_longer_allows_enriching -v` → FAIL (enriching still valid).

- [ ] **Step 3: Update `ReviewStatus` in `packages/core/src/adc_core/models.py`** — remove `"enriching"`:

```python
ReviewStatus = Literal[
    "queued", "validating", "analyzing", "finalizing", "done", "failed"
]
```

- [ ] **Step 4: Run → passes** — `uv run pytest packages/core/tests/test_models.py -v` → all pass.

- [ ] **Step 5: Update `ReviewStatus` in `apps/web/src/api/types.ts`** — remove `"enriching"`:

```ts
export type ReviewStatus =
  | "queued" | "validating" | "analyzing" | "finalizing" | "done" | "failed";
```

- [ ] **Step 6: Update `STAGES` in `apps/web/src/components/ProgressStepper.tsx`** — remove `"enriching"`:

```tsx
const STAGES = ["validating", "analyzing", "finalizing", "done"] as const;
```

- [ ] **Step 7: Remove the obsolete `enriching` comment in `apps/api/src/adc_api/review_service.py`** — delete the 3-line comment block that begins `# NOTE: the "enriching" stage` (just above `emit("finalizing")`). Leave the code.

- [ ] **Step 8: Add scanner config to `apps/api/src/adc_api/settings.py`** — add two fields to the `Settings` class (after `redis_url`):

```python
    scanners: str = "semgrep,bandit"   # comma list; empty disables the scanner layer
    scanner_timeout: int = 60          # seconds per container run
```

- [ ] **Step 9: Verify + commit**

Run: `uv run pytest packages/core apps/api -q` (all pass) and `pnpm --filter web exec tsc --noEmit` (clean) and `uv run ruff check .` (clean).
```bash
git add packages/core/src/adc_core/models.py apps/web/src/api/types.ts apps/web/src/components/ProgressStepper.tsx apps/api/src/adc_api/review_service.py apps/api/src/adc_api/settings.py packages/core/tests/test_models.py
git commit -m "feat: drop unused 'enriching' status; add ADC_SCANNERS/timeout settings"
```

---

### Task 2: SARIF → Findings mapper + Scanner Protocol

**Files:** Create `apps/api/src/adc_api/scanners/__init__.py`, `apps/api/src/adc_api/scanners/sarif.py`; Test `apps/api/tests/test_sarif.py`

- [ ] **Step 1: Write the failing test `apps/api/tests/test_sarif.py`**

```python
from adc_api.scanners.sarif import sarif_to_findings

SEMGREP_SARIF = {
    "runs": [{
        "tool": {"driver": {"name": "semgrep", "rules": [{
            "id": "python.sqli",
            "shortDescription": {"text": "SQL injection"},
            "helpUri": "https://semgrep.dev/r/python.sqli",
            "help": {"text": "Use parameterized queries."},
            "properties": {"security-severity": "8.0"},
        }]}},
        "results": [{
            "ruleId": "python.sqli",
            "level": "error",
            "message": {"text": "Detected SQL injection"},
            "locations": [{"physicalLocation": {
                "artifactLocation": {"uri": "snippet.py"},
                "region": {"startLine": 2, "endLine": 2, "startColumn": 5, "endColumn": 40},
            }}],
        }],
    }]
}

BANDIT_SARIF = {
    "runs": [{
        "tool": {"driver": {"name": "Bandit", "rules": [{
            "id": "B608", "name": "hardcoded_sql_expressions",
            "helpUri": "https://bandit.readthedocs.io/en/latest/plugins/b608.html",
        }]}},
        "results": [{
            "ruleId": "B608", "level": "warning",
            "message": {"text": "Possible SQL injection vector through string-based query construction."},
            "locations": [{"physicalLocation": {
                "artifactLocation": {"uri": "snippet.py"}, "region": {"startLine": 2, "endLine": 2},
            }}],
        }],
    }]
}


def test_maps_semgrep_result_with_sources_and_severity():
    findings = sarif_to_findings(SEMGREP_SARIF, "semgrep")
    assert len(findings) == 1
    f = findings[0]
    assert f.category == "security"
    assert f.severity == "high"               # security-severity 8.0 -> high
    assert f.location.start_line == 2
    assert "SQL injection" in f.title
    src = f.sources[0]
    assert src.type == "tool" and src.name == "semgrep"
    assert src.rule_id == "python.sqli"
    assert src.url == "https://semgrep.dev/r/python.sqli"


def test_maps_bandit_result_level_to_severity():
    findings = sarif_to_findings(BANDIT_SARIF, "bandit")
    assert len(findings) == 1
    f = findings[0]
    assert f.severity == "medium"             # level "warning" -> medium
    assert f.sources[0].name == "bandit" and f.sources[0].rule_id == "B608"


def test_skips_results_without_a_location():
    sarif = {"runs": [{"tool": {"driver": {"rules": []}},
                       "results": [{"ruleId": "x", "level": "error", "message": {"text": "no loc"}}]}]}
    assert sarif_to_findings(sarif, "semgrep") == []
```

- [ ] **Step 2: Run → fails** — `uv run pytest apps/api/tests/test_sarif.py -v` → FAIL (no module).

- [ ] **Step 3: Create `apps/api/src/adc_api/scanners/__init__.py`** (Scanner Protocol + build_scanners; build_scanners imports the adapters which don't exist until Task 3, so guard the import lazily):

```python
from __future__ import annotations

from typing import Protocol

from adc_core.models import Finding


class Scanner(Protocol):
    name: str
    languages: set[str]

    async def scan(self, code: str, language: str) -> list[Finding]: ...


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
```

- [ ] **Step 4: Implement `apps/api/src/adc_api/scanners/sarif.py`**

```python
from __future__ import annotations

import uuid

from adc_core.models import Finding, Location, Severity, Source

_LEVEL: dict[str, Severity] = {"error": "high", "warning": "medium", "note": "low", "none": "low"}


def _severity(result: dict, rule: dict) -> Severity:
    sec = rule.get("properties", {}).get("security-severity")
    if sec is not None:
        try:
            v = float(sec)
        except (TypeError, ValueError):
            v = None
        if v is not None:
            if v >= 9.0:
                return "critical"
            if v >= 7.0:
                return "high"
            if v >= 4.0:
                return "medium"
            return "low"
    return _LEVEL.get(result.get("level", "warning"), "medium")


def _region(result: dict) -> dict | None:
    for loc in result.get("locations", []):
        region = loc.get("physicalLocation", {}).get("region")
        if region and region.get("startLine"):
            return region
    return None


def sarif_to_findings(sarif: dict, scanner_name: str) -> list[Finding]:
    findings: list[Finding] = []
    for run in sarif.get("runs", []):
        rules = {
            r.get("id"): r
            for r in run.get("tool", {}).get("driver", {}).get("rules", [])
        }
        for result in run.get("results", []):
            region = _region(result)
            if region is None:
                continue
            rule = rules.get(result.get("ruleId"), {})
            message = (result.get("message", {}).get("text") or "").strip()
            title = (rule.get("shortDescription", {}).get("text") or message or "Scanner finding")
            recommendation = (
                rule.get("help", {}).get("text")
                or rule.get("fullDescription", {}).get("text")
                or "Review and remediate per the rule."
            )
            findings.append(
                Finding(
                    id=str(uuid.uuid4()),
                    category="security",
                    severity=_severity(result, rule),
                    title=title.split("\n")[0][:120],
                    description=message or title,
                    recommendation=recommendation,
                    location=Location(
                        start_line=region["startLine"],
                        end_line=region.get("endLine", region["startLine"]),
                        start_col=region.get("startColumn"),
                        end_col=region.get("endColumn"),
                    ),
                    sources=[Source(
                        type="tool",
                        name=scanner_name,
                        rule_id=result.get("ruleId"),
                        url=rule.get("helpUri"),
                    )],
                )
            )
    return findings
```

- [ ] **Step 5: Run → passes** — `uv run pytest apps/api/tests/test_sarif.py -v` → 3 passed. Then `uv run ruff check apps/api/src/adc_api/scanners apps/api/tests/test_sarif.py` (fix import order in touched files).

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/adc_api/scanners/__init__.py apps/api/src/adc_api/scanners/sarif.py apps/api/tests/test_sarif.py
git commit -m "feat(api): SARIF->Findings mapper + Scanner protocol/registry"
```

---
### Task 3: Docker runner + Semgrep/Bandit adapters

**Files:** Create `apps/api/src/adc_api/scanners/docker_runner.py`, `apps/api/src/adc_api/scanners/semgrep.py`, `apps/api/src/adc_api/scanners/bandit.py`, `infra/docker/bandit.Dockerfile`; Modify `Taskfile.yml`; Test `apps/api/tests/test_scanners.py`

- [ ] **Step 1: Implement `apps/api/src/adc_api/scanners/docker_runner.py`**

```python
from __future__ import annotations

import asyncio


async def docker_available() -> bool:
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "version",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        return proc.returncode == 0
    except (FileNotFoundError, OSError):
        return False


async def run_in_container(*, image: str, cmd: list[str], host_dir: str, timeout: int) -> str:
    """Run `image` with the host dir mounted read-only and no network; return stdout.

    Scanners write SARIF to stdout and may exit non-zero when findings exist, so the exit code
    is intentionally ignored — the caller parses stdout (and treats unparseable output as no findings).
    """
    args = [
        "docker", "run", "--rm", "--network=none",
        "-v", f"{host_dir}:/src:ro", "-w", "/src", image, *cmd,
    ]
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except (TimeoutError, asyncio.TimeoutError):
        proc.kill()
        raise
    return out.decode("utf-8", "replace")
```

- [ ] **Step 2: Implement `apps/api/src/adc_api/scanners/semgrep.py`**

```python
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
                out = await run_in_container(
                    image=self._image,
                    cmd=["semgrep", "scan", "--sarif", "--quiet", "--config", "p/default", "/src"],
                    host_dir=d, timeout=self._timeout,
                )
            except Exception:  # noqa: BLE001 — any scan failure degrades to no findings
                return []
        try:
            return sarif_to_findings(json.loads(out), self.name)
        except (ValueError, KeyError):
            return []
```

- [ ] **Step 3: Implement `apps/api/src/adc_api/scanners/bandit.py`**

```python
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
```

- [ ] **Step 4: Create `infra/docker/bandit.Dockerfile`** (no public-image dependency)

```dockerfile
FROM python:3.12-slim
RUN pip install --no-cache-dir "bandit[sarif]"
```

- [ ] **Step 5: Add a `scanners-build` task to `Taskfile.yml`** (under `tasks:`)

```yaml
  scanners-build: { desc: "Pull/build scanner images (semgrep + bandit)", cmds: ["docker pull semgrep/semgrep:latest", "docker build -t adc-bandit:latest -f infra/docker/bandit.Dockerfile infra/docker"] }
```

- [ ] **Step 6: Write the test `apps/api/tests/test_scanners.py`** (no Docker needed — gating + availability skip + registry)

```python
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
```

- [ ] **Step 7: Run → passes** — `uv run pytest apps/api/tests/test_scanners.py -v` → 4 passed. (These don't invoke Docker: language gating returns early; the availability test monkeypatches `docker_available`; registry tests just build objects.) Then `uv run ruff check apps/api/src/adc_api/scanners apps/api/tests/test_scanners.py` (fix import order; keep the `# noqa: BLE001`).

- [ ] **Step 8: Commit**

```bash
git add apps/api/src/adc_api/scanners/docker_runner.py apps/api/src/adc_api/scanners/semgrep.py apps/api/src/adc_api/scanners/bandit.py infra/docker/bandit.Dockerfile Taskfile.yml apps/api/tests/test_scanners.py
git commit -m "feat(api): Semgrep + Bandit scanner adapters (sandboxed docker) + scanners-build task"
```

---

### Task 4: Wire scanners into the graph + ReviewService (and keep unit tests Docker-free)

**Files:** Modify `apps/api/src/adc_api/graph.py`, `apps/api/src/adc_api/review_service.py`; Create `apps/api/tests/conftest.py`; Test `apps/api/tests/test_graph.py`

- [ ] **Step 1: Create `apps/api/tests/conftest.py`** — autouse fixture so ALL api unit tests run with scanners disabled (no Docker), deterministically:

```python
import pytest


@pytest.fixture(autouse=True)
def _disable_scanners(monkeypatch):
    """Unit/API tests never invoke real scanner containers. Tests that specifically exercise
    scanners override this (e.g. by injecting a fake scanner or re-setting settings.scanners)."""
    from adc_api.settings import settings
    monkeypatch.setattr(settings, "scanners", "")
```

- [ ] **Step 2: Write the failing test `apps/api/tests/test_graph.py`** (append a scanner-merge test):

```python
class _FakeScanner:
    name = "semgrep"
    languages = {"python"}

    def __init__(self, findings):
        self._findings = findings

    async def scan(self, code, language):
        return self._findings


@pytest.mark.asyncio
async def test_scanner_finding_merges_with_agent_finding_into_one_citation():
    from adc_api.agents import SpecialistAgent
    from adc_api.providers import MockProvider

    agent = SpecialistAgent(
        name="security-agent", category="security", system_prompt="s",
        provider=MockProvider(seed=[{
            "category": "security", "severity": "high", "title": "SQL Injection",
            "description": "d", "recommendation": "r", "start_line": 2, "end_line": 2,
        }]),
    )
    scanner_finding = Finding(
        id="sg", category="security", severity="critical", title="SQL Injection Vulnerability",
        description="d", recommendation="r", location=Location(start_line=2, end_line=2),
        sources=[Source(type="tool", name="semgrep", rule_id="python.sqli", url="https://x")],
    )
    graph = build_graph([agent], [_FakeScanner([scanner_finding])])
    out = await graph.ainvoke({"code": "q='..'+uid", "language": "python", "findings": [], "result": []})

    security = [f for f in out["result"] if f.category == "security"]
    assert len(security) == 1  # agent + scanner merged into ONE card
    assert {s.name for s in security[0].sources} == {"security-agent", "semgrep"}
    assert security[0].severity == "critical"  # max severity across merged sources
```

(The existing `test_graph.py` already imports `build_graph`, `Finding`, `Location`, `Source`, `pytest`; reuse them.)

- [ ] **Step 3: Run → fails** — `uv run pytest apps/api/tests/test_graph.py -v` → the new test FAILS (`build_graph` takes only `agents`).

- [ ] **Step 4: Update `build_graph` in `apps/api/src/adc_api/graph.py`** — accept scanners and add a node per scanner. Add a `Scanner`-agnostic node builder and extend the signature:

```python
def _scanner_node(scanner):
    async def node(state: ReviewState) -> dict:
        try:
            found = await scanner.scan(state["code"], state["language"])
        except Exception:  # noqa: BLE001 — isolate a scanner failure from the review
            found = []
        return {"findings": found}

    return node


def build_graph(agents: list[SpecialistAgent], scanners=()):
    """Compile START -> {specialists + scanners concurrently} -> aggregate -> END."""
    g = StateGraph(ReviewState)
    g.add_node("aggregate", _aggregate_node)
    for agent in agents:
        g.add_node(agent.name, _specialist_node(agent))
    for scanner in scanners:
        g.add_node(scanner.name, _scanner_node(scanner))
    for agent in agents:
        g.add_edge(START, agent.name)
        g.add_edge(agent.name, "aggregate")
    for scanner in scanners:
        g.add_edge(START, scanner.name)
        g.add_edge(scanner.name, "aggregate")
    g.add_edge("aggregate", END)
    return g.compile()
```

- [ ] **Step 5: Run → passes** — `uv run pytest apps/api/tests/test_graph.py -v` → all pass (incl. the merge test).

- [ ] **Step 6: Update `ReviewService` in `apps/api/src/adc_api/review_service.py`** — accept + build scanners, include them in the graph and the per-node sub-status.

Change the imports (add scanners):
```python
from adc_api.agents import SpecialistAgent, build_agents
from adc_api.graph import build_graph
from adc_api.scanners import Scanner, build_scanners
from adc_api.schemas import ProgressEvent
```

Change `__init__`:
```python
    def __init__(
        self,
        agents: list[SpecialistAgent] | None = None,
        scanners: list[Scanner] | None = None,
    ) -> None:
        self._agents = agents if agents is not None else build_agents()
        self._scanners = scanners if scanners is not None else build_scanners()
        self._node_names = {a.name for a in self._agents} | {s.name for s in self._scanners}
        self._graph = build_graph(self._agents, self._scanners)
```

In `run`, change the sub-status seed to use all node names (agents + scanners):
```python
            sub = {name: "running" for name in self._node_names}
```
(The `if node_name in sub` check in the astream loop already marks scanner nodes done.)

- [ ] **Step 7: Full suite + lint**

Run: `uv run pytest packages/core apps/api -q` → ALL pass (conftest disables scanners, so `ReviewService`/`run_review_core` build 0 scanners → no Docker; existing tests unaffected). Then `uv run ruff check .` → clean.

- [ ] **Step 8: Commit**

```bash
git add apps/api/src/adc_api/graph.py apps/api/src/adc_api/review_service.py apps/api/tests/conftest.py apps/api/tests/test_graph.py
git commit -m "feat(api): scanners as parallel graph nodes -> merged citations; tests scanner-free via conftest"
```

---

### Task 5: e2e (scanner-free) + gated Docker integration + docs + final verification

**Files:** Modify `apps/web/playwright.config.ts`, `CREDITS.md`, `README.md`; Create/append `apps/api/tests/test_integration.py`

- [ ] **Step 1: Disable scanners for the e2e mock API** — in `apps/web/playwright.config.ts`, add `ADC_SCANNERS=` to the API `webServer.command`:

```ts
      command: "ADC_MODEL_PROVIDER=mock ADC_BACKEND=memory ADC_SCANNERS= uv run --project ../../apps/api uvicorn adc_api.main:app --port 8001",
```

- [ ] **Step 2: Append a gated scanner integration test to `apps/api/tests/test_integration.py`** (self-skips without Docker; not run in default CI). Add at the end of the file:

```python
async def _docker_available() -> bool:
    from adc_api.scanners.docker_runner import docker_available
    return await docker_available()


@pytest.mark.asyncio
async def test_real_scanners_flag_sql_injection():
    if not await _docker_available():
        pytest.skip("Docker not available (run `task scanners-build` first)")

    from adc_api.scanners.bandit import BanditScanner
    from adc_api.scanners.semgrep import SemgrepScanner

    code = (
        "def get_user(uid):\n"
        "    q = \"SELECT * FROM users WHERE id = \" + str(uid)\n"
        "    cursor.execute(q)\n"
    )
    bandit = await BanditScanner().scan(code, "python")
    semgrep = await SemgrepScanner().scan(code, "python")
    all_findings = bandit + semgrep
    # at least one scanner should flag something, and findings must carry a tool source
    assert all_findings, "expected Semgrep and/or Bandit to report a finding"
    assert all(f.sources and f.sources[0].type == "tool" for f in all_findings)
    assert {f.sources[0].name for f in all_findings} <= {"bandit", "semgrep"}
```

NOTE: the autouse `_disable_scanners` conftest fixture only sets `settings.scanners`; it does NOT affect these tests (they instantiate `BanditScanner`/`SemgrepScanner` directly), so the integration test still exercises the real adapters.

- [ ] **Step 3: Update `CREDITS.md`** — change the Semgrep/Bandit line to reflect they're now used:

```markdown
- [Semgrep](https://semgrep.dev) (`semgrep/semgrep` image) + [Bandit](https://github.com/PyCQA/bandit) (`bandit[sarif]`) — Apache-2.0 — external SARIF scanners run as sandboxed-Docker nodes (Inc 5); each finding cites its tool + rule URL.
```

- [ ] **Step 4: Update `README.md`** — (a) Architecture `apps/api` bullet: add "+ external scanners (Semgrep/Bandit) whose findings merge into the same cited cards"; (b) add a short section after "How it works":

```markdown
## Scanners (Inc 5)
Semgrep + Bandit run as sandboxed Docker containers (`docker run --network=none`, code mounted
read-only) in parallel with the agents; their SARIF findings merge into the same cards via the
aggregator, so one issue cites the agent **and** the scanners (each chip links to the rule). Build the
images once with `task scanners-build`. Configure with `ADC_SCANNERS` (default `semgrep,bandit`; set
empty to disable). Requires Docker; without it (or `ADC_SCANNERS=`) reviews run agent-only.
```

- [ ] **Step 5: FULL verification**

```bash
uv run pytest packages/core apps/api -q          # all pass; scanner integration self-skips if no Docker images
uv run ruff check .                              # clean
pnpm --filter web test -- --run                  # 4 passed
pnpm --filter web exec tsc --noEmit              # clean (ReviewStatus change)
pnpm --filter web build                          # succeeds
find apps/web/src \( -name '*.js' -o -name '*.d.ts' \)   # empty
```
Then the e2e (free ports first, then run — uses ADC_SCANNERS= so it stays Docker-free):
```bash
for p in 5173 8001; do lsof -ti tcp:$p | xargs kill -9 2>/dev/null; done; sleep 1
pnpm --filter web e2e   # 1 passed
rm -rf apps/web/test-results
```
If any step fails, STOP and report verbatim.

- [ ] **Step 6: Commit**

```bash
git add apps/web/playwright.config.ts apps/api/tests/test_integration.py CREDITS.md README.md
git commit -m "test+docs(inc5): scanner-free e2e, gated real-scanner integration, CREDITS + README"
```

---

## Self-Review (completed)

**Spec coverage:** §2.1 Scanner seam + adapters → Tasks 2 (Protocol/registry) + 3 (Semgrep/Bandit). §2.2 sandboxed Docker exec → Task 3 (`docker_runner`, `--network=none`, ro mount, bandit Dockerfile, `scanners-build`). §2.3 graph placement (parallel nodes → existing aggregator) → Task 4. §2.4 SARIF mapper → Task 2. §3 config (`ADC_SCANNERS`/timeout) → Task 1 (settings) + used in Task 3/4. §4 contract (drop `enriching`, `sources`/chips, frontend otherwise unchanged) → Task 1 + (FindingCard already renders url chips). §5 testing (SARIF fixtures, fake-scanner merge, gating, availability skip, scanner-free e2e, gated integration) → Tasks 2/3/4/5. Attribution → Task 5 (CREDITS).

**Placeholder scan:** none — complete code in each step; commands have expected output.

**Type consistency:** `Scanner` (name/languages/`async scan(code,language)->list[Finding]`) consistent across Task 2 Protocol, Task 3 adapters, Task 4 `_FakeScanner` + nodes. `sarif_to_findings(sarif, scanner_name)` consistent Tasks 2→3. `run_in_container(*, image, cmd, host_dir, timeout)` + `docker_available()` consistent Tasks 3→3/5. `build_scanners()->list[Scanner]` consistent Tasks 2→4. `build_graph(agents, scanners=())` + `ReviewService(agents=None, scanners=None)` consistent Tasks 4→(worker reuses run() unchanged). `ReviewStatus` minus `enriching` consistent across models.py/types.ts/ProgressStepper (Task 1). `Source(type="tool", name, rule_id, url)` matches the Inc 1 schema.
