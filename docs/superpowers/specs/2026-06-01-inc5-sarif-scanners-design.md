# Inc 5 — SARIF Scanners + Multi-Source Citations — Design Spec

**Date:** 2026-06-01
**Status:** Approved (brainstorm) — pending implementation plan
**Builds on:** Inc 0–3 (merged to `main`)
**Repo:** https://github.com/omrihaber/ai-dev-companion

---

## 1. Overview

Add **external static-analysis scanners** (Semgrep + Bandit) that run alongside the LLM agents and feed
their findings into the **existing aggregator** (Inc 2). Because the aggregator already merges by
`location + similar title` across categories and unions `sources[]`, a scanner finding at the same lines
as an agent's finding collapses into **one card citing every source** — e.g. a SQL injection cited by
`security-agent` **+ `semgrep` + `bandit`**, each chip linking to the tool's rule docs.

Scanners run as **parallel nodes in the existing LangGraph fan-out** (alongside the 6 agents), each in its
**own Docker container** (the submitted code is scanned in an isolated, network-less container — never on
the host). The previously-reserved `enriching` status is now confirmed unused (scanners run under
`analyzing`) and is **removed** from the contract + UI.

### Guiding principles
- **Reuse the aggregator seam** — scanners are just another `sources[]` producer; no aggregator change.
- **Normalize on SARIF** — one `sarif_to_findings` mapper unlocks any SARIF-emitting tool later.
- **Graceful degradation** — a scanner that's unavailable/unsupported/errors returns `[]`; never sinks the review.
- **Sandboxed** — scan code in `docker run --rm --network=none` containers.
- **Injectable + testable** — scanners passed into the graph; tests use a `FakeScanner` (no Docker); a gated
  integration test exercises the real images.
- **Attribution** — Semgrep/Bandit credited in `CREDITS.md` and in each finding's `sources[]`.

---

## 2. Architecture

### 2.1 The `Scanner` seam
```python
class Scanner(Protocol):
    name: str                       # "semgrep" | "bandit"  -> Finding.sources[].name
    languages: set[str]             # which languages it supports
    async def scan(self, code: str, language: str) -> list[Finding]: ...
```
- `SemgrepScanner` (languages: python/typescript/java) and `BanditScanner` (languages: python).
- Each adapter:
  1. returns `[]` immediately if `language not in self.languages`;
  2. writes `code` to a temp dir (file named per language, e.g. `snippet.py`);
  3. runs its Docker image via the shared `run_in_container(...)` helper with SARIF output;
  4. parses the SARIF via the shared `sarif_to_findings(sarif, scanner_name)` mapper;
  5. on **any** failure (Docker missing, image pull fails, non-zero exit w/o SARIF, timeout) logs and
     returns `[]`.

### 2.2 Sandboxed Docker execution
A single helper `run_in_container(*, image, cmd, host_dir, timeout=60) -> str` (returns stdout):
`docker run --rm --network=none -v {host_dir}:/src:ro -w /src {image} {cmd}` via `asyncio.create_subprocess_exec`.
- `--network=none` + read-only mount sandbox the scan.
- Images: **Semgrep** `semgrep/semgrep` (official) → `semgrep scan --sarif --quiet --config p/default /src`
  (the `p/default` registry ruleset; no account, fetched at run — if the network blocks it, the scan
  degrades to `[]`). **Bandit**: a pinned small image — preferred public `ghcr.io/pycqa/bandit`; if none is
  reliable, an `infra/docker/bandit.Dockerfile` (`FROM python:3.12-slim; RUN pip install bandit[sarif]`)
  built locally — running `bandit -r /src -f sarif`.
- A scanner first checks Docker availability (`docker version` succeeds); if not, `scan` returns `[]`.

### 2.3 Graph placement
`build_graph(agents, scanners)` adds one node per scanner to the **existing** fan-out:
`START → {6 agents + N scanners} (concurrent) → aggregate → END`. Each scanner node runs `scanner.scan`
(wrapped in try/except → `[]`), returning `{"findings": [...]}` (merged via the `operator.add` reducer).
The existing `aggregate` node merges everything. `ReviewService(agents, scanners)` builds both and passes
them to `build_graph`. Per-source SSE sub-status now includes `semgrep`/`bandit`.

### 2.4 SARIF → Findings mapping
`sarif_to_findings(sarif: dict, scanner_name: str) -> list[Finding]` over `runs[].results[]`:
- **severity**: from `result.level` (`error→high`, `warning→medium`, `note/none→low`); if the rule carries a
  `security-severity` property (0–10), map ≥7→`critical`, ≥4→`high`, else `medium`.
- **location**: first `physicalLocation.region` → `Location(start_line, end_line, start_col?, end_col?)`.
- **title**: rule `shortDescription` or the result `message.text` (first line).
- **description**: `message.text`; **recommendation**: rule `help.text`/`fullDescription` if present, else a
  generic "Review and remediate per the rule." 
- **category**: default `security` (both tools are security-focused); refined from rule tags later.
- **sources**: `[Source(type="tool", name=scanner_name, rule_id=<ruleId>, url=<rule.helpUri>)]`.
- `id`: uuid4. Unmappable/locationless results are skipped.

---

## 3. Configuration
- `ADC_SCANNERS` (default `"semgrep,bandit"`): comma list of enabled scanners; **empty disables the layer**
  (used by the e2e/memory backend so it needs no Docker).
- `ADC_SCANNER_TIMEOUT` (default `60`) seconds per container run.
- `ReviewService` builds scanners from `ADC_SCANNERS`; unknown names are ignored with a log.

---

## 4. Contract / UI impact
- **Findings schema unchanged** (scanner findings use the existing `Source` fields `rule_id`/`url`).
- **`ReviewStatus` drops `enriching`** → `queued|validating|analyzing|finalizing|done|failed` (Pydantic
  `adc_core.models` + TS `apps/web/src/api/types.ts` in lockstep). `ProgressStepper` STAGES drop `enriching`.
  Remove the now-obsolete `enriching` comment in `review_service.py`.
- **Frontend otherwise unchanged**: `FindingCard` already renders `sources[]` with `url` as clickable chips,
  so scanner citations link to rule docs automatically. Per-agent/per-scanner sub-status shows in the stepper.

---

## 5. Testing
- **Unit**: `sarif_to_findings` against a recorded SARIF fixture (real Semgrep + real Bandit SARIF samples) →
  asserts severity/location/title/sources(rule_id,url) mapping; a `FakeScanner` (returns canned Findings)
  drives a graph test confirming scanner findings reach + merge in the aggregator; language gating
  (`BanditScanner.scan(code, "java")` → `[]`); availability skip (Docker-missing path → `[]`, monkeypatched).
- **Aggregator merge proof** (already covered by Inc 2 tests; add one): an agent SQLi + a `semgrep` SQLi at
  the same lines/similar title → one finding citing both sources.
- **API/e2e**: with `ADC_SCANNERS=""` (memory backend) the flow is unchanged and Docker-free → existing e2e
  stays green; update the e2e only for the dropped `enriching` stage if referenced (it isn't asserted).
- **Gated integration** (requires Docker): run the real Semgrep + Bandit images on a Python SQLi snippet →
  assert a finding with a `semgrep` and/or `bandit` source; self-skips if `docker version` fails.
- Determinism rule holds (assert schema/sources, not exact tool wording).

---

## 6. Out of scope (later)
- Multi-file/repo scanning (Inc: multi-file + retrieval) — scanners currently scan the single submitted
  snippet's temp file; a directory mount generalizes trivially when multi-file lands.
- SonarQube / CodeRabbit / PR-Agent adapters — the SARIF seam makes them additive later.
- Per-rule category refinement (mapping scanner findings to performance/logic/etc. via rule tags).
- Git ingestion (Inc 4), auth (Inc 6), notifications (Inc 7), observability (Inc 8).

---

## 7. Known limitations
- Semgrep fetches its ruleset (`p/default`) at run time (no account, but needs network); if blocked, Semgrep
  degrades to `[]` (Bandit is fully offline).
- Docker is required for the scanner layer; without it (or with `ADC_SCANNERS=""`), reviews run agent-only.
- Container cold-start adds latency to the first scan; acceptable for this increment.
- Scanner findings are categorized `security` by default (refinement deferred).
