# Inc 2: Multi-Agent LangGraph Review — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Inc 1's single `core-reviewer` LLM call with a LangGraph graph of 6 concurrent specialist agents feeding an aggregator that dedupes + citation-merges findings — behind the unchanged `ReviewService.run(...)` / API / Findings contract.

**Architecture:** Separate **agents** (prompt + category, own model) from **providers** (transport: `complete_structured`). A LangGraph `StateGraph` fans out `START → {6 specialists} → aggregate → END` using an `operator.add` reducer for concurrent appends + a separate `result` key the aggregator replaces. tree-sitter `syntax` findings are seeded into the graph. Execution stays on the in-memory `JobManager` (asyncio). Per-agent progress streamed via `graph.astream`.

**Tech Stack:** LangGraph, `instructor` (OpenAI + Anthropic), `anthropic` SDK, Pydantic v2, pytest. Frontend unchanged except the TS `Category` union.

**Conventions:** TDD; backend tests use `MockProvider` (no live LLM). Run Python via `uv` from repo root. Branch: `inc2-multi-agent` (already created off `main`). API JSON stays camelCase.

---

## File Structure

```
apps/api/
├─ pyproject.toml                      # + langgraph, anthropic
├─ src/adc_api/
│  ├─ providers.py        # MODIFY: complete_structured protocol; refactor Ollama/Mock; + Anthropic; build_provider(model,kind)
│  ├─ agent_prompts.py    # NEW: 6 focused system prompts (seeded/adapted from awesome-reviewers)
│  ├─ agents.py           # NEW: SpecialistAgent (+ analyze → list[Finding]); build_agents() registry + per-agent model env
│  ├─ aggregator.py       # NEW: dedupe + citation-merge + rank (standalone, the Inc 5 seam)
│  ├─ graph.py            # NEW: ReviewState, specialist/aggregate nodes, build_graph(agents)
│  └─ review_service.py   # MODIFY: run tree-sitter, drive graph via astream, per-agent SSE, read result
│  └─ tests/{test_providers,test_agents,test_aggregator,test_graph,test_review_service,test_api}.py
packages/core/src/adc_core/models.py   # MODIFY: Category += quality/docs/tests (replaces style)
apps/web/src/api/types.ts              # MODIFY: Category union to match
.env.example                          # MODIFY: per-agent model vars + anthropic
README.md, CREDITS.md                  # MODIFY: multi-agent flow + prompt attribution
```

---

### Task 1: Add LangGraph + Anthropic dependencies

**Files:** Modify `apps/api/pyproject.toml`

- [ ] **Step 1: Add deps to `apps/api/pyproject.toml`** — in the `dependencies` array add:

```toml
  "langgraph>=0.2.40",
  "anthropic>=0.39",
```

(Keep the existing `adc-core`, `fastapi`, `uvicorn[standard]`, `sse-starlette`, `pydantic-settings`, `instructor`, `openai`.)

- [ ] **Step 2: Sync + smoke-import**

Run:
```bash
uv sync --all-packages
uv run python -c "import langgraph; from langgraph.graph import StateGraph; import anthropic, instructor; print('ok', langgraph.__version__)"
```
Expected: prints `ok <version>`, no ImportError.

- [ ] **Step 3: Commit**

```bash
git add apps/api/pyproject.toml uv.lock
git commit -m "build(api): add langgraph + anthropic deps for Inc 2"
```

---

### Task 2: Extend the Category contract (quality/docs/tests)

**Files:** Modify `packages/core/src/adc_core/models.py`, `apps/api/src/adc_api/schemas.py`, `apps/web/src/api/types.ts`, `docs/test-cases/inc1-samples.md`; Test `packages/core/tests/test_models.py`

- [ ] **Step 1: Add a failing test in `packages/core/tests/test_models.py`** (append):

```python
import pytest
from pydantic import ValidationError


def test_category_supports_new_specialist_categories():
    for cat in ("quality", "docs", "tests"):
        f = Finding(
            id="x", category=cat, severity="low", title="t", description="d",
            recommendation="r", location=Location(start_line=1, end_line=1),
        )
        assert f.category == cat


def test_category_rejects_removed_style_value():
    with pytest.raises(ValidationError):
        Finding(
            id="x", category="style", severity="low", title="t", description="d",
            recommendation="r", location=Location(start_line=1, end_line=1),
        )
```

- [ ] **Step 2: Run → fails**

Run: `uv run pytest packages/core/tests/test_models.py -v`
Expected: FAIL (currently `style` is valid and `quality/docs/tests` are not).

- [ ] **Step 3: Update `Category` in `packages/core/src/adc_core/models.py`**

```python
Category = Literal["security", "performance", "logic", "quality", "docs", "tests", "syntax"]
```

- [ ] **Step 4: Run → passes**

Run: `uv run pytest packages/core/tests/test_models.py -v`
Expected: PASS.

- [ ] **Step 5: Update `RawFinding.category` in `apps/api/src/adc_api/schemas.py`**

```python
    category: Literal["security", "performance", "logic", "quality", "docs", "tests"]
```

- [ ] **Step 6: Update `Category` in `apps/web/src/api/types.ts`**

```ts
export type Category = "security" | "performance" | "logic" | "quality" | "docs" | "tests" | "syntax";
```

- [ ] **Step 7: Update the sample doc `docs/test-cases/inc1-samples.md`** — replace the two `Style/` labels with `Quality/` (Python case: `Quality/low — missing type hints & docstring`; TypeScript case: `Quality/medium — parameter id untyped`).

- [ ] **Step 8: Verify + commit**

Run: `uv run pytest packages/core apps/api -q` (all pass) and `pnpm --filter web exec tsc --noEmit` (clean).
```bash
git add packages/core/src/adc_core/models.py apps/api/src/adc_api/schemas.py apps/web/src/api/types.ts packages/core/tests/test_models.py docs/test-cases/inc1-samples.md
git commit -m "feat(core): extend Category (quality/docs/tests; replaces style) across schema + TS types"
```

---

### Task 3: Generalize ModelProvider (`complete_structured`)

**Files:** Modify `apps/api/src/adc_api/providers.py`, `apps/api/tests/test_providers.py`

- [ ] **Step 1: Replace `apps/api/tests/test_providers.py`** with tests for the new interface:

```python
import pytest
from pydantic import BaseModel
from adc_api.providers import MockProvider, build_provider
from adc_api.schemas import ReviewOutput


@pytest.mark.asyncio
async def test_mock_provider_returns_seeded_structured_output():
    provider = MockProvider(seed=[{
        "category": "security", "severity": "high", "title": "SQLi",
        "description": "d", "recommendation": "r", "start_line": 2, "end_line": 2,
    }])
    out = await provider.complete_structured(system="s", user="u", response_model=ReviewOutput)
    assert isinstance(out, ReviewOutput)
    assert out.findings[0].category == "security"


def test_build_provider_defaults_to_ollama():
    p = build_provider()
    assert p.model  # has a model string
    assert hasattr(p, "complete_structured")
```

- [ ] **Step 2: Run → fails**

Run: `uv run pytest apps/api/tests/test_providers.py -v`
Expected: FAIL (`complete_structured` / new MockProvider not present).

- [ ] **Step 3: Rewrite `apps/api/src/adc_api/providers.py`** (replace the whole file):

```python
from __future__ import annotations

import os
from typing import Protocol, TypeVar

from pydantic import BaseModel

from adc_api.schemas import ReviewOutput

T = TypeVar("T", bound=BaseModel)


class ModelProvider(Protocol):
    name: str
    model: str

    async def complete_structured(self, *, system: str, user: str, response_model: type[T]) -> T: ...


class MockProvider:
    """Deterministic provider for tests/CI (no network). Returns seeded findings."""

    name = "mock"
    model = "mock"

    def __init__(self, seed: list[dict] | None = None) -> None:
        self._seed = seed or []

    async def complete_structured(self, *, system: str, user: str, response_model: type[T]) -> T:
        return response_model.model_validate({"findings": self._seed})


class OllamaProvider:
    """OpenAI-compatible provider (Ollama default). JSON mode for reliable structured output."""

    name = "openai-compatible"

    def __init__(self, base_url: str, model: str, api_key: str = "ollama") -> None:
        import instructor
        from openai import AsyncOpenAI

        self.model = model
        self._client = instructor.from_openai(
            AsyncOpenAI(base_url=base_url, api_key=api_key), mode=instructor.Mode.JSON
        )

    async def complete_structured(self, *, system: str, user: str, response_model: type[T]) -> T:
        return await self._client.chat.completions.create(
            model=self.model,
            response_model=response_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )


class AnthropicProvider:
    """Native Anthropic provider via instructor."""

    name = "anthropic"

    def __init__(self, model: str, api_key: str, max_tokens: int = 2048) -> None:
        import instructor
        from anthropic import AsyncAnthropic

        self.model = model
        self._max_tokens = max_tokens
        self._client = instructor.from_anthropic(AsyncAnthropic(api_key=api_key))

    async def complete_structured(self, *, system: str, user: str, response_model: type[T]) -> T:
        return await self._client.messages.create(
            model=self.model,
            max_tokens=self._max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            response_model=response_model,
        )


def build_provider(model: str | None = None, kind: str | None = None) -> ModelProvider:
    kind = kind or os.getenv("ADC_MODEL_PROVIDER", "ollama")
    model = model or os.getenv("ADC_MODEL", "qwen2.5-coder:7b")
    if kind == "mock":
        return MockProvider(seed=[{
            "category": "security", "severity": "high", "title": "SQL injection vulnerability",
            "description": "User input concatenated into SQL string.",
            "recommendation": "Use parameterized queries.", "start_line": 2, "end_line": 2,
        }])
    if kind == "ollama":
        return OllamaProvider(os.getenv("ADC_OLLAMA_BASE_URL", "http://localhost:11434/v1"), model)
    if kind == "openai":
        return OllamaProvider(
            os.getenv("ADC_OPENAI_BASE_URL", "https://api.openai.com/v1"),
            model, api_key=os.environ["ADC_OPENAI_API_KEY"],
        )
    if kind == "anthropic":
        return AnthropicProvider(model, os.environ["ADC_ANTHROPIC_API_KEY"])
    raise ValueError(f"unknown provider: {kind}")
```

- [ ] **Step 4: Run → passes**

Run: `uv run pytest apps/api/tests/test_providers.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/adc_api/providers.py apps/api/tests/test_providers.py
git commit -m "refactor(api): ModelProvider.complete_structured + Anthropic adapter + model override"
```

---

### Task 4: Specialist agents + prompts

**Files:** Create `apps/api/src/adc_api/agent_prompts.py`, `apps/api/src/adc_api/agents.py`; Test `apps/api/tests/test_agents.py`

- [ ] **Step 1: Create `apps/api/src/adc_api/agent_prompts.py`** (concise focused prompts; lineage from awesome-reviewers noted in CREDITS):

```python
"""Specialist system prompts. Seeded/adapted from baz-scm/awesome-reviewers (Apache-2.0)."""

_BASE = (
    "You are a senior code reviewer specializing in {focus}. Review the {{language}} code and report "
    "ONLY real {focus} issues. For each issue give a short title, a clear description, an actionable "
    "recommendation, and the 1-based start/end line range. If there are no {focus} issues, return an "
    "empty list. Do not report issues outside {focus}."
)

SECURITY = _BASE.format(focus="security vulnerabilities (injection, authn/z, secrets, unsafe APIs)")
PERFORMANCE = _BASE.format(focus="performance and efficiency (complexity, allocations, N+1, blocking calls)")
LOGIC = _BASE.format(focus="logic errors, bugs, and edge cases (off-by-one, null/None, race conditions)")
QUALITY = _BASE.format(focus="code quality (naming, structure, maintainability, best practices)")
DOCS = _BASE.format(focus="documentation (missing/incorrect docstrings, comments, type hints)")
TESTS = _BASE.format(focus="testability and test coverage gaps (untested branches, hard-to-test design)")
```

- [ ] **Step 2: Write the failing test `apps/api/tests/test_agents.py`**

```python
import pytest
from adc_api.agents import SpecialistAgent, build_agents
from adc_api.providers import MockProvider


@pytest.mark.asyncio
async def test_agent_forces_its_category_and_sets_source():
    agent = SpecialistAgent(
        name="security-agent", category="security", system_prompt="s",
        provider=MockProvider(seed=[{
            "category": "logic", "severity": "high", "title": "SQLi",
            "description": "d", "recommendation": "r", "start_line": 2, "end_line": 2,
        }]),
    )
    findings = await agent.analyze("code", "python")
    assert len(findings) == 1
    f = findings[0]
    assert f.category == "security"            # forced to the agent's category (not the seed's "logic")
    assert f.sources[0].name == "security-agent"
    assert f.location.start_line == 2


def test_build_agents_returns_six_specialists():
    agents = build_agents()
    names = {a.name for a in agents}
    assert names == {
        "security-agent", "performance-agent", "logic-agent",
        "quality-agent", "docs-agent", "tests-agent",
    }
```

- [ ] **Step 3: Run → fails**

Run: `uv run pytest apps/api/tests/test_agents.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 4: Implement `apps/api/src/adc_api/agents.py`**

```python
from __future__ import annotations

import uuid
from dataclasses import dataclass

from adc_core.models import Category, Finding, Location, Source

from adc_api import agent_prompts
from adc_api.providers import ModelProvider, build_provider
from adc_api.schemas import ReviewOutput

# (name, category, prompt-attr, env-key)
_SPECS: list[tuple[str, Category, str, str]] = [
    ("security-agent", "security", "SECURITY", "SECURITY"),
    ("performance-agent", "performance", "PERFORMANCE", "PERFORMANCE"),
    ("logic-agent", "logic", "LOGIC", "LOGIC"),
    ("quality-agent", "quality", "QUALITY", "QUALITY"),
    ("docs-agent", "docs", "DOCS", "DOCS"),
    ("tests-agent", "tests", "TESTS", "TESTS"),
]


@dataclass
class SpecialistAgent:
    name: str
    category: Category
    system_prompt: str
    provider: ModelProvider

    async def analyze(self, code: str, language: str) -> list[Finding]:
        out: ReviewOutput = await self.provider.complete_structured(
            system=self.system_prompt.format(language=language),
            user=f"```{language}\n{code}\n```",
            response_model=ReviewOutput,
        )
        return [
            Finding(
                id=str(uuid.uuid4()),
                category=self.category,
                severity=raw.severity,
                title=raw.title,
                description=raw.description,
                recommendation=raw.recommendation,
                location=Location(start_line=raw.start_line, end_line=raw.end_line),
                sources=[Source(type="agent", name=self.name)],
            )
            for raw in out.findings
        ]


def build_agents(provider: ModelProvider | None = None) -> list[SpecialistAgent]:
    """Build the 6 specialists. If `provider` is given, all agents share it (used by
    tests/e2e to inject a MockProvider); otherwise each agent resolves its own provider
    from per-agent env (falling back to the global default)."""
    import os

    agents: list[SpecialistAgent] = []
    for name, category, prompt_attr, env_key in _SPECS:
        if provider is not None:
            p: ModelProvider = provider
        else:
            model = os.getenv(f"ADC_AGENT_{env_key}_MODEL")      # optional per-agent override
            kind = os.getenv(f"ADC_AGENT_{env_key}_PROVIDER")    # optional per-agent provider
            p = build_provider(model=model, kind=kind)
        agents.append(
            SpecialistAgent(
                name=name,
                category=category,
                system_prompt=getattr(agent_prompts, prompt_attr),
                provider=p,
            )
        )
    return agents
```

- [ ] **Step 5: Run → passes**

Run: `uv run pytest apps/api/tests/test_agents.py -v`
Expected: PASS (2 passed). NOTE: `build_agents()` calls `build_provider()` with the default `ollama` kind — it only constructs the client object (no network), so the test passes offline.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/adc_api/agent_prompts.py apps/api/src/adc_api/agents.py apps/api/tests/test_agents.py
git commit -m "feat(api): 6 specialist agents (focused prompts, per-agent model config)"
```

---

### Task 5: Aggregator (dedupe + citation-merge + rank)

**Files:** Create `apps/api/src/adc_api/aggregator.py`; Test `apps/api/tests/test_aggregator.py`

- [ ] **Step 1: Write the failing test `apps/api/tests/test_aggregator.py`**

```python
from adc_core.models import Finding, Location, Source
from adc_api.aggregator import aggregate


def _f(cat, sev, name, s, e, title="t"):
    return Finding(
        id=name + str(s), category=cat, severity=sev, title=title, description="d",
        recommendation="r", location=Location(start_line=s, end_line=e),
        sources=[Source(type="agent", name=name)],
    )


def test_merges_same_category_overlapping_lines_and_unions_sources():
    merged = aggregate([
        _f("security", "high", "security-agent", 2, 2),
        _f("security", "critical", "semgrep", 2, 3),
    ])
    assert len(merged) == 1
    names = {s.name for s in merged[0].sources}
    assert names == {"security-agent", "semgrep"}
    assert merged[0].severity == "critical"  # max severity wins


def test_keeps_distinct_categories_and_ranks_by_severity():
    out = aggregate([
        _f("quality", "low", "quality-agent", 1, 1),
        _f("security", "critical", "security-agent", 5, 5),
    ])
    assert [f.category for f in out] == ["security", "quality"]  # critical ranked first


def test_syntax_passthrough_not_merged_into_agent_categories():
    out = aggregate([
        _f("syntax", "high", "tree-sitter", 2, 2),
        _f("security", "high", "security-agent", 2, 2),
    ])
    assert len(out) == 2
```

- [ ] **Step 2: Run → fails**

Run: `uv run pytest apps/api/tests/test_aggregator.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implement `apps/api/src/adc_api/aggregator.py`**

```python
from __future__ import annotations

from adc_core.models import Finding, Location, Severity, Source

_SEV_RANK: dict[Severity, int] = {
    "critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1,
}


def _overlap(a: Location, b: Location) -> bool:
    return a.start_line <= b.end_line and b.start_line <= a.end_line


def _merge_sources(a: list[Source], b: list[Source]) -> list[Source]:
    by_name: dict[str, Source] = {s.name: s for s in a}
    for s in b:
        by_name.setdefault(s.name, s)
    return list(by_name.values())


def aggregate(findings: list[Finding]) -> list[Finding]:
    """Dedupe by (category, overlapping line range), union sources, keep max severity,
    keep the most-specific text, then rank by severity desc, then start line asc.

    The seam Inc 5 reuses: external-scanner findings merge into existing findings as extra
    citations. `syntax` findings never merge into other categories.
    """
    merged: list[Finding] = []
    for f in findings:
        hit = None
        for m in merged:
            if m.category == f.category and _overlap(m.location, f.location):
                hit = m
                break
        if hit is None:
            merged.append(f.model_copy(deep=True))
            continue
        # merge into hit
        hit.sources = _merge_sources(hit.sources, f.sources)
        if _SEV_RANK[f.severity] > _SEV_RANK[hit.severity]:
            hit.severity = f.severity
        if len(f.description) > len(hit.description):
            hit.title, hit.description, hit.recommendation = f.title, f.description, f.recommendation
        hit.location = Location(
            file=hit.location.file,
            start_line=min(hit.location.start_line, f.location.start_line),
            end_line=max(hit.location.end_line, f.location.end_line),
        )

    merged.sort(key=lambda x: (-_SEV_RANK[x.severity], x.location.start_line))
    return merged
```

- [ ] **Step 4: Run → passes**

Run: `uv run pytest apps/api/tests/test_aggregator.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/adc_api/aggregator.py apps/api/tests/test_aggregator.py
git commit -m "feat(api): aggregator (dedupe + citation-merge + rank) — the Inc 5 seam"
```

---
### Task 6: LangGraph graph (fan-out → aggregate)

**Files:** Create `apps/api/src/adc_api/graph.py`; Test `apps/api/tests/test_graph.py`

- [ ] **Step 1: Write the failing test `apps/api/tests/test_graph.py`**

```python
import pytest
from adc_core.models import Finding, Location, Source
from adc_api.agents import SpecialistAgent
from adc_api.graph import build_graph
from adc_api.providers import MockProvider


def _agent(name, cat, sev, provider=None):
    return SpecialistAgent(
        name=name, category=cat, system_prompt="s",
        provider=provider or MockProvider(seed=[{
            "category": cat, "severity": sev, "title": cat, "description": "d",
            "recommendation": "r", "start_line": 5, "end_line": 5,
        }]),
    )


def _syntax():
    return Finding(
        id="s", category="syntax", severity="high", title="Syntax error", description="d",
        recommendation="r", location=Location(start_line=1, end_line=1),
        sources=[Source(type="tool", name="tree-sitter")],
    )


@pytest.mark.asyncio
async def test_graph_runs_specialists_and_aggregates_with_syntax_seeded():
    graph = build_graph([_agent("security-agent", "security", "critical"),
                         _agent("quality-agent", "quality", "low")])
    out = await graph.ainvoke({"code": "x", "language": "python", "findings": [_syntax()], "result": []})
    res = out["result"]
    cats = [f.category for f in res]
    assert {"security", "quality", "syntax"} <= set(cats)
    assert cats[0] == "security"  # critical ranked first
    assert next(f for f in res if f.category == "security").sources[0].name == "security-agent"


@pytest.mark.asyncio
async def test_failing_agent_is_isolated_review_still_aggregates():
    class Boom(MockProvider):
        async def complete_structured(self, **kw):
            raise RuntimeError("agent down")
    graph = build_graph([_agent("security-agent", "security", "high", provider=Boom()),
                         _agent("quality-agent", "quality", "low")])
    out = await graph.ainvoke({"code": "x", "language": "python", "findings": [], "result": []})
    cats = [f.category for f in out["result"]]
    assert "quality" in cats and "security" not in cats  # failed agent contributed nothing
```

- [ ] **Step 2: Run → fails**

Run: `uv run pytest apps/api/tests/test_graph.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implement `apps/api/src/adc_api/graph.py`**

```python
from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from adc_core.models import Finding

from adc_api.agents import SpecialistAgent
from adc_api.aggregator import aggregate


class ReviewState(TypedDict):
    code: str
    language: str
    findings: Annotated[list[Finding], operator.add]  # concurrent specialist appends
    result: list[Finding]                             # aggregator output (last-write-wins)


def _specialist_node(agent: SpecialistAgent):
    async def node(state: ReviewState) -> dict:
        try:
            found = await agent.analyze(state["code"], state["language"])
        except Exception:  # noqa: BLE001 — isolate one agent's failure from the whole review
            found = []
        return {"findings": found}

    return node


async def _aggregate_node(state: ReviewState) -> dict:
    return {"result": aggregate(state["findings"])}


def build_graph(agents: list[SpecialistAgent]):
    """Compile START → {specialists concurrently} → aggregate → END."""
    g = StateGraph(ReviewState)
    g.add_node("aggregate", _aggregate_node)
    for agent in agents:
        g.add_node(agent.name, _specialist_node(agent))
    for agent in agents:
        g.add_edge(START, agent.name)
        g.add_edge(agent.name, "aggregate")
    g.add_edge("aggregate", END)
    return g.compile()
```

- [ ] **Step 4: Run → passes**

Run: `uv run pytest apps/api/tests/test_graph.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/adc_api/graph.py apps/api/tests/test_graph.py
git commit -m "feat(api): LangGraph fan-out graph (6 specialists -> aggregate) with per-agent isolation"
```

---

### Task 7: ReviewService drives the graph (per-agent SSE)

**Files:** Modify `apps/api/src/adc_api/review_service.py`; replace `apps/api/tests/test_review_service.py`

- [ ] **Step 1: Replace `apps/api/tests/test_review_service.py`**

```python
import pytest
from adc_api.agents import build_agents
from adc_api.providers import MockProvider
from adc_api.review_service import ReviewService


@pytest.mark.asyncio
async def test_run_produces_multi_category_findings_and_per_agent_progress():
    agents = build_agents(provider=MockProvider(seed=[{
        "category": "security", "severity": "high", "title": "issue",
        "description": "d", "recommendation": "r", "start_line": 1, "end_line": 1,
    }]))
    events: list[tuple[str, dict]] = []
    svc = ReviewService(agents=agents)
    result = await svc.run(
        review_id="r1", language="python", code="x = 1\n",
        on_progress=lambda e: events.append((e.stage, e.sub_status)),
    )
    assert result.status == "done"
    # each agent forces its own category -> all six categories present
    cats = {f.category for f in result.findings}
    assert {"security", "performance", "logic", "quality", "docs", "tests"} <= cats
    stages = [s for s, _ in events]
    assert "analyzing" in stages and "done" in stages
    # per-agent sub-status reached "done" for every agent
    final_sub = [sub for s, sub in events if s == "analyzing"][-1]
    assert all(v == "done" for v in final_sub.values())
```

- [ ] **Step 2: Run → fails**

Run: `uv run pytest apps/api/tests/test_review_service.py -v`
Expected: FAIL (`ReviewService(agents=...)` not supported yet).

- [ ] **Step 3: Replace `apps/api/src/adc_api/review_service.py`**

```python
from __future__ import annotations

import time
from collections.abc import Callable

from adc_core.models import Finding, ReviewResult, ReviewStatus
from adc_core.syntax import check_syntax

from adc_api.agents import SpecialistAgent, build_agents
from adc_api.graph import build_graph
from adc_api.schemas import ProgressEvent

OnProgress = Callable[[ProgressEvent], None]


def _summarize(findings: list[Finding]) -> str:
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.category] = counts.get(f.category, 0) + 1
    return ", ".join(f"{n} {c}" for c, n in sorted(counts.items())) or "no issues found"


class ReviewService:
    """Runs the multi-agent LangGraph review behind a stable run() signature."""

    def __init__(self, agents: list[SpecialistAgent] | None = None) -> None:
        self._agents = agents if agents is not None else build_agents()
        self._agent_names = {a.name for a in self._agents}
        self._graph = build_graph(self._agents)

    async def run(
        self, *, review_id: str, language: str, code: str, on_progress: OnProgress
    ) -> ReviewResult:
        started = time.monotonic()
        model_label = ",".join(sorted({a.provider.model for a in self._agents}))
        result = ReviewResult(id=review_id, language=language, model=model_label)

        def emit(stage: ReviewStatus, **kw) -> None:
            result.status = stage
            on_progress(ProgressEvent(review_id=review_id, stage=stage, **kw))

        try:
            emit("validating")
            syntax = check_syntax(language, code)

            sub = {name: "running" for name in self._agent_names}
            emit("analyzing", sub_status=dict(sub))

            aggregated: list[Finding] = []
            async for update in self._graph.astream(
                {"code": code, "language": language, "findings": syntax, "result": []},
                stream_mode="updates",
            ):
                for node_name, delta in update.items():
                    if node_name in sub:
                        sub[node_name] = "done"
                        emit("analyzing", sub_status=dict(sub))
                    if node_name == "aggregate":
                        aggregated = delta["result"]

            emit("finalizing")
            result.findings = aggregated
            result.summary = _summarize(aggregated)
            result.duration_ms = int((time.monotonic() - started) * 1000)
            emit("done")
        except Exception as exc:  # noqa: BLE001 — surfaced to the user as a failed job
            result.error = str(exc)
            result.duration_ms = int((time.monotonic() - started) * 1000)
            emit("failed", message=str(exc))
        return result
```

- [ ] **Step 4: Run → passes**

Run: `uv run pytest apps/api/tests/test_review_service.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/adc_api/review_service.py apps/api/tests/test_review_service.py
git commit -m "feat(api): ReviewService drives LangGraph graph with per-agent SSE sub-status"
```

---

### Task 8: Wire JobManager + create_app to agents (not a single provider)

**Files:** Modify `apps/api/src/adc_api/jobs.py`, `apps/api/src/adc_api/main.py`, `apps/api/tests/test_jobs.py`, `apps/api/tests/test_api.py`

- [ ] **Step 1: Update `apps/api/src/adc_api/jobs.py`** — change the factory from a provider to an agents factory.

Replace the imports + `__init__` + the `_run` line that builds the service:

```python
from collections.abc import AsyncIterator, Callable

from adc_core.models import ReviewResult
from adc_core.sanitization import validate_submission

from adc_api.agents import SpecialistAgent, build_agents
from adc_api.review_service import ReviewService
from adc_api.schemas import ProgressEvent
```

```python
    def __init__(self, agents_factory: Callable[[], list[SpecialistAgent]] = build_agents) -> None:
        self._agents_factory = agents_factory
        self._results: dict[str, ReviewResult] = {}
        self._queues: dict[str, asyncio.Queue[ProgressEvent | None]] = {}
        self._tasks: set[asyncio.Task[None]] = set()
```

And in `_run`, replace the service construction line:

```python
        svc = ReviewService(agents=self._agents_factory())
```

(Leave `create`, `stream`, `get`, `list_all`, and the task-ref handling unchanged.)

- [ ] **Step 2: Update `apps/api/src/adc_api/main.py`** — swap the injection point.

Replace the import of `build_provider`/`ModelProvider` with agents, and the signature + JobManager construction:

```python
from adc_api.agents import SpecialistAgent, build_agents
```

```python
def create_app(
    agents_factory: Callable[[], list[SpecialistAgent]] | None = None,
) -> FastAPI:
```

```python
    jm = JobManager(agents_factory=agents_factory or build_agents)
```

(Everything else in `main.py` — routes, SSE, error handling — stays the same.)

- [ ] **Step 3: Update `apps/api/tests/test_jobs.py`** — inject mock agents instead of a provider.

Replace the import and the two `JobManager(provider_factory=...)` constructions:

```python
from adc_api.agents import build_agents
from adc_api.providers import MockProvider
```

```python
    jm = JobManager(agents_factory=lambda: build_agents(provider=MockProvider(seed=[{
        "category": "style", "severity": "low", "title": "t",
        "description": "d", "recommendation": "r", "start_line": 1, "end_line": 1,
    }])))
```

(For `test_create_rejects_bad_submission`, use `JobManager(agents_factory=lambda: build_agents(provider=MockProvider()))`. NOTE: the seed's `category` is ignored — each agent forces its own — so any value is fine.)

- [ ] **Step 4: Update `apps/api/tests/test_api.py`** — `_app()` helper injects mock agents.

```python
from adc_api.agents import build_agents

def _app():
    return create_app(agents_factory=lambda: build_agents(provider=MockProvider(seed=[{
        "category": "security", "severity": "high", "title": "SQLi",
        "description": "concat", "recommendation": "params", "start_line": 2, "end_line": 2,
    }])))
```

(Keep all three test bodies; the assertions — 202, SSE drain, `status=="done"`, a `security` finding, list endpoint, 422 — remain valid.)

- [ ] **Step 5: Run the whole API + core suite**

Run: `uv run pytest packages/core apps/api -q`
Expected: all pass. Then `uv run ruff check .` → clean (fix import order in touched files if flagged).

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/adc_api/jobs.py apps/api/src/adc_api/main.py apps/api/tests/test_jobs.py apps/api/tests/test_api.py
git commit -m "refactor(api): JobManager/create_app build agents (multi-agent) instead of one provider"
```

---

### Task 9: Integration — e2e, env, docs, final verification

**Files:** Modify `apps/web/e2e/review.spec.ts`, `.env.example`, `README.md`, `CREDITS.md`

- [ ] **Step 1: Update the source assertion in `apps/web/e2e/review.spec.ts`** — Inc 2 sources are agent names, not `core-reviewer`. Change the citation assertion line:

```ts
  await expect(page.getByText(/security-agent/)).toBeVisible();
```

(Leave the rest: select python, click Review Code, wait for `review progress` to contain `done`, assert `SQL injection vulnerability` + `/security/i` `.first()`.)

- [ ] **Step 2: Add per-agent + Anthropic env to `.env.example`** — append:

```bash
# Anthropic (ADC_MODEL_PROVIDER=anthropic)
# ADC_ANTHROPIC_API_KEY=
# Per-agent model/provider overrides (default = global ADC_MODEL/ADC_MODEL_PROVIDER):
# ADC_AGENT_SECURITY_MODEL=
# ADC_AGENT_PERFORMANCE_MODEL=
# ADC_AGENT_LOGIC_MODEL=
# ADC_AGENT_QUALITY_MODEL=
# ADC_AGENT_DOCS_MODEL=
# ADC_AGENT_TESTS_MODEL=
```

- [ ] **Step 3: Update `README.md`** — (a) in **Architecture**, change the apps/api bullet to mention the multi-agent graph; (b) replace the Mermaid `analyzing` source node with the 6 agents. Replace the single `AG[...]` node line in the diagram with:

```
  RS -->|analyzing| AG["6 specialist agents (LangGraph, concurrent)<br/>security · performance · logic · quality · docs · tests<br/>ModelProvider — Ollama · OpenAI · Anthropic · BYO"]
```

And add a line under the diagram bullets:

```markdown
- **Multi-agent (Inc 2):** a LangGraph graph fans out to 6 concurrent specialist agents (each with its
  own focused prompt + optional per-agent model); the aggregator dedupes/merges their findings and
  ranks by severity. Local models serialize on one Ollama instance — use a cloud provider for true parallelism.
```

- [ ] **Step 4: Update `CREDITS.md`** — change the awesome-reviewers line to reflect it's now used:

```markdown
- [baz-scm/awesome-reviewers](https://github.com/baz-scm/awesome-reviewers) — Apache-2.0 — specialist-agent prompts in `apps/api/src/adc_api/agent_prompts.py` are seeded/adapted from this corpus.
```

- [ ] **Step 5: FULL verification** — run each, capture output:

```bash
uv run pytest packages/core apps/api -q          # all pass
uv run ruff check .                              # clean
pnpm --filter web test -- --run                  # 4 passed
pnpm --filter web exec tsc --noEmit              # clean
pnpm --filter web build                          # succeeds
```
Then confirm no stray artifacts: `find apps/web/src \( -name '*.js' -o -name '*.d.ts' \)` → empty.

**e2e note:** the Playwright e2e (`pnpm --filter web e2e`) spins up its own mock-backed API via `ADC_MODEL_PROVIDER=mock`. Run it **only when no dev server is already bound to :5173** (Playwright reuses an existing one). If a local dev server is running, stop it first, then run e2e; expect `1 passed`.

- [ ] **Step 6: Commit**

```bash
git add apps/web/e2e/review.spec.ts .env.example README.md CREDITS.md
git commit -m "docs+test(e2e): multi-agent README/diagram, per-agent env, e2e source assertion"
```

---

## Self-Review (completed)

**Spec coverage:** Provider/agent split + `complete_structured` + Anthropic (spec §2.1) → Tasks 3. Six specialists + per-agent models + awesome-reviewers prompts (§2.2) → Task 4, 9. LangGraph state w/ `operator.add` reducer + separate `result`, syntax seeded, START→specialists→aggregate→END (§2.3) → Task 6, 7. Aggregator dedupe/merge/rank seam (§2.4) → Task 5. Perf/error-isolation (§3) → Task 6 (node try/except), README note (§3) → Task 9. Unchanged API/Findings + per-agent SSE (§4) → Tasks 7, 8 (contract) ; Category contract growth required by docs/tests/quality → Task 2. Testing (§5) → Tasks 3–8 + e2e Task 9.

**Placeholder scan:** none — every code step is complete; commands have expected output.

**Type consistency:** `ModelProvider.complete_structured(system,user,response_model)->T` consistent across Tasks 3 (def), 4 (agent call), 6 (Boom override). `SpecialistAgent(name,category,system_prompt,provider)` + `.analyze()->list[Finding]` consistent Tasks 4,6,7. `build_agents(provider=None)->list[SpecialistAgent]` consistent Tasks 4,7,8. `build_graph(agents)` + `ReviewState{code,language,findings,result}` consistent Tasks 6,7. `aggregate(list[Finding])->list[Finding]` consistent Tasks 5,6. `ReviewService(agents=None).run(...)` + `JobManager(agents_factory=build_agents)` + `create_app(agents_factory=None)` consistent Tasks 7,8. `Category` includes quality/docs/tests/syntax across models.py/schemas.py/types.ts (Task 2) and is used by agents (Task 4) and tests.
