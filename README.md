# AI Dev Companion

Intelligent, multi-step code review powered by GenAI. Submit code; get structured, categorized,
**source-cited** findings (security / performance / logic / style / syntax) with live progress.
Open-source and local-first — runs with **zero API keys** using a local model (Ollama).

> Built incrementally. This release includes **multi-file review** (whole-codebase ingestion, two-tier
> scan, coverage report, mark-and-re-run, History file browsing). See the
> [design spec](docs/superpowers/specs/2026-05-31-ai-dev-companion-design.md) for the full roadmap.

## Architecture
- **packages/core** — Findings schema, sanitization, tree-sitter syntax checks.
- **apps/api** — FastAPI job API + **LangGraph multi-agent engine** (6 specialists → aggregator). `POST /api/reviews` accepts a whole codebase (`files[]` + `marked[]`) or a multipart ZIP. `POST /api/reviews/zip` uploads a `.zip` directly. Reviews are persisted in **Postgres** and run by an **arq/Redis worker** (or in-process via `ADC_BACKEND=memory`) + external scanners (Semgrep/Bandit) whose SARIF findings merge into the same cited cards. Per-review corpus is stored under `ADC_WORK_ROOT`.
- **apps/web** — React + Monaco three-pane workspace (file tree | editor | per-file findings) + coverage banner + Re-run + History (click a row to reload the full review + browse its files) + Settings.

## How it works

A review is an **async job**: the API persists it (Postgres), writes the corpus to `ADC_WORK_ROOT/<id>/`,
enqueues it (arq/Redis), and a **worker** runs the two-tier `ReviewService` LangGraph. The **first tier**
runs Semgrep + Bandit once over the whole corpus dir (breadth pass). The **second tier** fans out the 6
LLM agents over a bounded subset — `marked` files ∪ scanner-hit files, capped at `ADC_AGENT_FILE_CAP`
(marks can push up to `ADC_AGENT_FILE_CEILING`). Every **source** — tree-sitter, the 6 agents, and the
SARIF scanners — dedupes/merges by `location + similar title` and **unions `sources[]`**. The result
includes a `coverage` report (filesTotal / filesAgentReviewed / per-file status). The **mark-and-re-run**
loop (`POST /api/reviews/{id}/rerun`) reuses the persisted corpus and creates a linked review
(`parentReviewId`). History rows are clickable → reload the full report and browse all files.

```mermaid
flowchart TB
  U["User drops folder / ZIP<br/>(or legacy single snippet)"] --> POST["POST /api/reviews\n(files[] + marked[])"]
  POST --> CORPUS["Write corpus to\nADC_WORK_ROOT/<id>/"]
  CORPUS --> Q["queue (arq/Redis) → worker\nstate persisted in Postgres"]
  Q --> SCAN["Tier 1: SARIF scanners (once over corpus dir)\nSemgrep · Bandit (sandboxed Docker)"]
  SCAN --> SELECT["Select agent subset\nmarked ∪ scanner-hit (≤ ADC_AGENT_FILE_CAP)"]
  SELECT --> RS["ReviewService — LangGraph fan-out"]

  RS -->|validating| TS["Source: tree-sitter\ndeterministic syntax check"]
  RS -->|analyzing| AG["6 specialist agents (per-file fan-out)\nsecurity · performance · logic · quality · docs · tests\nModelProvider — Ollama · OpenAI · Anthropic · BYO"]

  TS --> AGG["Aggregator\ndedupe + merge by location + similar title\n→ union sources[]"]
  AG --> AGG
  SCAN --> AGG

  AGG --> RESULT["ReviewResult.findings + coverage\ncategory · severity · location.file · sources[]"]
  RESULT --> GET["GET /api/reviews/:id (Postgres)"]
  GET --> CARDS["Three-pane UI\nfile tree (tri-state marks + badges) | Monaco | per-file findings\ncoverage banner · Re-run · History (click → reload)"]

  Q -.->|progress events (Redis pub/sub)| SSEUI["SSE stream → progress stepper"]
```

- **`tree-sitter`** (deterministic): real parse errors → `syntax` findings, no LLM needed.
- **Agents:** a LangGraph graph fans out to 6 concurrent specialist agents
  (`security / performance / logic / quality / docs / tests`), each with its own prompt + optional
  per-agent model; cloud providers run them truly in parallel (local Ollama serializes).
- **Two-tier scan:** scanners run once over the full corpus (breadth); agents deep-review only the
  bounded marked+hit subset — so large codebases are always bounded.
- **Coverage report:** `filesTotal`, `filesAgentReviewed`, per-file status (`marked` / `scanner-hit` /
  `fallback` / `not-flagged` / `over-cap`) returned in the result and surfaced as a banner.
- **SARIF scanners (Inc 5):** Semgrep + Bandit run as sandboxed Docker nodes; one SARIF→Findings mapper
  turns their results into `sources` that the aggregator merges into the matching finding as extra
  citations (each chip links to the rule). See **Scanners** below.

## Scanners (Inc 5)
Semgrep + Bandit run as Docker containers in parallel with the agents; their SARIF findings merge
into the same cards via the aggregator, so one issue cites the agent **and** the scanners (each chip
links to the rule). Bandit runs fully offline + sandboxed (`--network=none`, code mounted read-only);
Semgrep fetches its rule registry (network-enabled; the code is still mounted read-only and never
executed). Build the images once with `task scanners-build`. Configure via `ADC_SCANNERS` (default
`semgrep,bandit`; empty disables). Requires Docker; without it (or `ADC_SCANNERS=`) reviews run agent-only.

## Quick start
```bash
cp .env.example .env
task up            # postgres + redis + ollama
task migrate       # apply DB migrations (run again after pull to apply 0002: coverage + parent_review_id)
task pull-model    # qwen2.5-coder:7b  (or set ADC_MODEL_PROVIDER=openai/anthropic + a key)
task api           # http://localhost:8000
task worker        # arq worker (runs the reviews)
task web           # http://localhost:5173
```
> No Postgres/Redis? Run the lightweight in-process mode: set `ADC_BACKEND=memory` and skip `task migrate`/`task worker` — reviews run inside the API process (non-durable; good for a quick demo).
(No `task`/go-task? The Taskfile.yml commands are short; run them directly — e.g. `docker compose -f infra/compose/docker-compose.yml up -d`, `uv run uvicorn adc_api.main:app --port 8000` from `apps/api`, `pnpm --filter web dev`.)

## API
- `POST /api/reviews` `{ "files": [{path, content, language?}], "marked": [paths] }` (or legacy `{code, language}`) -> `202 { reviewId }`
- `POST /api/reviews/zip` multipart `.zip` upload (server-side unzip) -> `202 { reviewId }`
- `GET /api/reviews/{id}/events` -> SSE progress (`validating->analyzing->finalizing->done`)
- `GET /api/reviews/{id}` -> final `ReviewResult` (findings with `sources[]` + `coverage`)
- `GET /api/reviews/{id}/file?path=` -> raw file content from the persisted corpus (traversal-guarded)
- `POST /api/reviews/{id}/rerun` `{ "marked": [paths] }` -> `202 { reviewId }` (new linked review, reuses corpus)
- `GET /api/reviews` -> history list

## Testing
```bash
uv run pytest packages/core apps/api    # backend unit + API e2e (mock provider)
pnpm --filter web test -- --run         # frontend unit
pnpm --filter web e2e                   # Playwright (spins up mock-provider API + web)
```

## Design decisions & trade-offs
Local model default (zero keys, weaker output -> tests assert on schema not wording); stable Findings
contract with `sources[]` so later scanners (Semgrep/SonarQube) merge as citations; async job + SSE so
long multi-agent runs (Inc 2+) show progress. Full rationale in the design spec.

## Bring your own model
Set `ADC_MODEL_PROVIDER=openai`, `ADC_OPENAI_BASE_URL`, `ADC_OPENAI_API_KEY`, `ADC_MODEL` (any
OpenAI-compatible endpoint, including hosted Qwen). Anthropic adapter lands in Inc 2.

## Configuration
| Env var | Default | Purpose |
|---|---|---|
| `ADC_WORK_ROOT` | `.adc_work` | Root dir for per-review corpus dirs (must be a shared path/volume when API + worker run in separate processes) |
| `ADC_AGENT_FILE_CAP` | `25` | Max files sent to agents (hard cap) |
| `ADC_AGENT_FILE_CEILING` | `150` | Max files that marks can promote (soft ceiling) |
| `ADC_FILE_CONCURRENCY` | `4` | Parallel agent fan-out per file |
| `ADC_MAX_FILES` | `2000` | Max files accepted in a single review request |
| `ADC_MAX_TOTAL_BYTES` | `50000000` | Max total upload size (bytes) |
| `ADC_MAX_FILE_BYTES` | `512000` | Max size per individual file |
| `ADC_IGNORE_GLOBS` | — | Comma-separated glob denylist (e.g. `*.lock,dist/**`) |

## Known limitations
No auth yet (Inc 6); CORS is open (`*`) for local dev and must be restricted before deployment.
Work dirs under `ADC_WORK_ROOT` are not cleaned up automatically — see `docs/tech-debt.md`.
