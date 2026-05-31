# Inc 2 — Multi-Agent LangGraph Review — Design Spec

**Date:** 2026-05-31
**Status:** Approved (brainstorm) — pending implementation plan
**Builds on:** Inc 0 + Inc 1 (merged to `main`)
**Repo:** https://github.com/omrihaber/ai-dev-companion

---

## 1. Overview

Replace Inc 1's single `core-reviewer` LLM call with a **LangGraph multi-agent graph**: a dispatch
node fans out to **6 specialist agents** that run concurrently, then an **aggregator** dedupes and
**citation-merges** their findings into the existing `Finding` schema. The public API, the Findings
contract, and the SSE progress mechanism are **unchanged** — Inc 2 swaps the engine behind
`ReviewService.run(...)`.

Execution stays on Inc 1's **in-memory** `JobManager` (asyncio gives concurrent agents). The
Postgres/Redis/arq state+queue migration is deferred to a later increment (decided: agents first).

### Guiding principles
- **Agents own prompts; providers own transport.** Clean separation, each unit testable in isolation.
- **The Findings schema + API contract do not change.** Inc 2 is an engine swap behind `ReviewService`.
- **The aggregator is the citation seam** reused by Inc 5 (external SARIF scanners).
- **TDD**, deterministic tests via `MockProvider` (no live LLM in CI).

---

## 2. Architecture

### 2.1 Provider/agent split
Inc 1's `ModelProvider.review(code, language)` has the review prompt baked in. Generalize it:

```python
class ModelProvider(Protocol):
    name: str
    model: str
    async def complete_structured(self, *, system: str, user: str, response_model: type[T]) -> T: ...
```

- Adapters: `OllamaProvider` (OpenAI-compatible, JSON mode — existing), **`AnthropicProvider`** (new,
  via `instructor`), `MockProvider` (deterministic; returns seeded output keyed by agent).
- `build_provider(model=None)` resolves provider kind from `ADC_MODEL_PROVIDER` and supports a
  per-call model override (for per-agent models). Adds an `anthropic` branch
  (`ADC_ANTHROPIC_API_KEY`).

### 2.2 Specialist agents
A `SpecialistAgent` is data + one method:

```python
@dataclass
class SpecialistAgent:
    name: str          # e.g. "security-agent"  -> Finding.sources[].name
    category: Category # "security" | "performance" | "logic" | "quality" | "docs" | "tests"
    system_prompt: str # focused prompt, seeded/adapted from awesome-reviewers (attributed in CREDITS)
    provider: ModelProvider
    async def analyze(self, code: str, language: str) -> list[RawFinding]: ...
```

`analyze` calls `provider.complete_structured(system=self.system_prompt, user=<code>, response_model=ReviewOutput)`
and forces each returned finding's `category = self.category`. The 6 agents:
`security · performance · logic · quality · docs · tests`. `quality` = style/maintainability/best-practices.

Per-agent model config: `ADC_AGENT_<NAME>_MODEL` (and optional `_PROVIDER`) overrides, falling back to
the global `ADC_MODEL`/`ADC_MODEL_PROVIDER`. A registry builds the 6 agents from config.

### 2.3 LangGraph graph
`StateGraph` with state:

```python
class ReviewState(TypedDict):
    code: str
    language: str
    findings: Annotated[list[Finding], operator.add]   # reducer: concurrent specialist nodes append safely
    result: list[Finding]                              # last-write-wins: the aggregator's deduped+ranked output
```

Topology: `START → dispatch → {security, performance, logic, quality, docs, tests} (concurrent)
→ aggregate → END`.

> **Implementation note:** the `dispatch` step is conceptual — the compiled graph wires
> `START → {specialists} → aggregate → END` directly, and `ReviewService` seeds the initial state
> (code, language, tree-sitter syntax findings) at invoke time. No separate `dispatch` node is needed.
- `dispatch` seeds state, **including the deterministic tree-sitter `syntax` findings** (computed by
  `ReviewService` and passed into the initial state) so the aggregator ranks everything together.
- Each specialist node runs `agent.analyze`, converts `RawFinding → Finding` (uuid, location,
  `sources=[Source(type="agent", name=agent.name)]`), and returns `{"findings": [...]}` — merged via
  the `operator.add` reducer (safe under concurrency).
- `aggregate` reads `findings`, runs the dedup/merge+rank (§2.4), and writes the result to the separate
  `result` key (no reducer → it *replaces* rather than appends). `ReviewService` reads `state["result"]`.

`ReviewService` builds the graph once, and in `run(...)` it: emits `validating` + runs tree-sitter
(unchanged), emits `analyzing` with per-agent `sub_status`, invokes the graph, then `finalizing`/`done`.
The `OnProgress` callback is passed so node entry/exit can emit per-agent SSE sub-status.

### 2.4 Aggregator (dedup + citation-merge)
Merge findings that describe the **same issue — overlapping line range AND similar title — across
categories** into one card: union `sources[]` (dedup by name), pick the **representative** (highest
severity, ties broken by category priority: security>logic>performance>quality>docs>tests), widen the
location to the union, then rank by severity (critical→info) then start line. Title similarity uses
token-containment (`|A∩B| / min(|A|,|B|) ≥ 0.6`) so "SQL Injection" and "Untested SQL Injection"
merge but unrelated same-line issues don't. tree-sitter `syntax` findings always pass through unmerged.

> **Why cross-category:** specialist agents (especially smaller local models) often flag the *same*
> underlying issue under different categories (e.g. SQL injection surfaced by both the security and
> quality agents). Merging by location+title collapses these into one card citing every agent, rather
> than N near-duplicate cards. This logic lives in a standalone, directly unit-tested function —
> **the seam Inc 5 reuses** to attach external-scanner findings as extra citations.

---

## 3. Performance & operational notes
- 6 agents = 6 LLM calls. Against a **single local Ollama model they serialize** (Ollama runs one
  request per model at a time), so a local multi-agent review can take minutes. **True parallelism
  needs a cloud provider** (Anthropic/OpenAI) — the practical multi-agent demo path. Per-agent model
  config lets you mix (e.g. strong security model + cheap style model). Documented in README.
- A graph-level timeout / per-agent error isolation: if one agent fails, its node returns `[]` and logs;
  the review still completes with the other agents' findings (don't fail the whole job on one agent).

---

## 4. API / UI impact (minimal)
- **API contract + Findings schema: unchanged.** `POST /api/reviews`, SSE, result shape identical.
- **SSE**: the `analyzing` stage now emits per-agent `subStatus` (`security-agent: running|done`, …);
  the existing `ProgressStepper` already renders `subStatus`, so it lights up with no rework.
- **Findings**: now cite agent sources (`security-agent`, etc.) instead of the single `core-reviewer`.
- No new frontend components required for Inc 2.

---

## 5. Testing
- **Unit**: each `SpecialistAgent.analyze` with `MockProvider` (deterministic seeded output); the
  aggregator dedup/merge/rank function (overlapping merge, source union, max severity, syntax
  passthrough); provider adapters (Anthropic mapping via recorded/mocked client); graph construction.
- **Graph e2e (mocked)**: run the full graph with mock-backed agents → assert findings from multiple
  categories, agent-named sources, ranked order.
- **API test**: unchanged `POST → SSE → GET` flow still green with the multi-agent engine (mock provider).
- **Frontend e2e (Playwright)**: unchanged selectors; mock provider yields a finding; per-agent
  sub-status visible. Determinism rule from Inc 1 still holds (assert schema/categories, not wording).

---

## 6. Out of scope (later increments)
- Postgres/Redis/arq state+queue migration (next increment — "infra later").
- External SARIF scanners (Inc 5) — the aggregator seam is ready for them.
- Retrieval/multi-file (Inc 3), git ingestion (Inc 4), auth (Inc 6), notifications (Inc 7),
  observability (Inc 8). See the [roadmap spec](2026-05-31-ai-dev-companion-design.md).

---

## 7. Known limitations
- Local multi-agent reviews are slow (serialized on a single Ollama model); cloud providers recommended
  for the multi-agent path.
- Per-agent model config is env-based (no in-app editor until Settings becomes editable — tech-debt).
- With one agent per category, cross-source dedup is mostly intra-category until Inc 5 adds scanners.
