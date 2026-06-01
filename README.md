# AI Dev Companion

Intelligent, multi-step code review powered by GenAI. Submit code; get structured, categorized,
**source-cited** findings (security / performance / logic / style / syntax) with live progress.
Open-source and local-first — runs with **zero API keys** using a local model (Ollama).

> Built incrementally. This release is **Inc 0 + Inc 1** (foundation + the complete single-snippet
> review app). See the [design spec](docs/superpowers/specs/2026-05-31-ai-dev-companion-design.md)
> for the full roadmap (multi-agent, retrieval, git ingestion, SARIF scanners, auth, notifications, observability).

## Architecture
- **packages/core** — Findings schema, sanitization, tree-sitter syntax checks.
- **apps/api** — FastAPI job API + **LangGraph multi-agent engine** (6 specialists → aggregator). `POST /api/reviews` -> SSE progress -> `ReviewResult`. Pluggable `ModelProvider` (Ollama/OpenAI/Anthropic). Reviews are persisted in **Postgres** and run by an **arq/Redis worker** (or in-process via `ADC_BACKEND=memory`) + external scanners (Semgrep/Bandit) whose SARIF findings merge into the same cited cards.
- **apps/web** — React + Monaco workspace (side-by-side editor/findings) + History + Settings.

## How it works

A review is an **async job**: the API persists it (Postgres), enqueues it (arq/Redis), and a **worker**
runs the `ReviewService` LangGraph. Every **source** — tree-sitter, the 6 LLM agents, and the SARIF
scanners — runs concurrently, then an **aggregator** dedupes/merges by `location + similar title`
(across categories) and **unions `sources[]`** — so one issue can **cite multiple sources** (e.g. the
`security-agent` *and* `semgrep` *and* `bandit`). The UI shows those as clickable citation chips.

```mermaid
flowchart TB
  U["User submits code<br/>(Monaco editor)"] --> POST["POST /api/reviews"]
  POST --> Q["queue (arq/Redis) → worker<br/>state persisted in Postgres"]
  Q --> RS["ReviewService — LangGraph fan-out"]

  RS -->|validating| TS["Source: tree-sitter<br/>deterministic syntax check"]
  RS -->|analyzing| AG["6 specialist agents (concurrent)<br/>security · performance · logic · quality · docs · tests<br/>ModelProvider — Ollama · OpenAI · Anthropic · BYO"]
  RS -->|analyzing| EXT["Sources: SARIF scanners (sandboxed Docker)<br/>Semgrep · Bandit<br/>(SonarQube · CodeRabbit pluggable later)"]

  TS --> AGG["Aggregator<br/>dedupe + merge by location + similar title<br/>→ union sources[]"]
  AG --> AGG
  EXT --> AGG

  AGG --> RESULT["ReviewResult.findings<br/>category · severity · location · recommendation · sources[]"]
  RESULT --> GET["GET /api/reviews/:id (Postgres)"]
  GET --> CARDS["Findings UI<br/>category groups · severity badges<br/>source citations · click → jump to line"]

  Q -.->|progress events (Redis pub/sub)| SSEUI["SSE stream → progress stepper"]
```

- **`tree-sitter`** (deterministic): real parse errors → `syntax` findings, no LLM needed.
- **Agents (Inc 2):** a LangGraph graph fans out to 6 concurrent specialist agents
  (`security / performance / logic / quality / docs / tests`), each with its own prompt + optional
  per-agent model; cloud providers run them truly in parallel (local Ollama serializes).
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
task migrate       # create the reviews table (alembic)
task pull-model    # qwen2.5-coder:7b  (or set ADC_MODEL_PROVIDER=openai/anthropic + a key)
task api           # http://localhost:8000
task worker        # arq worker (runs the reviews)
task web           # http://localhost:5173
```
> No Postgres/Redis? Run the lightweight in-process mode: set `ADC_BACKEND=memory` and skip `task migrate`/`task worker` — reviews run inside the API process (non-durable; good for a quick demo).
(No `task`/go-task? The Taskfile.yml commands are short; run them directly — e.g. `docker compose -f infra/compose/docker-compose.yml up -d`, `uv run uvicorn adc_api.main:app --port 8000` from `apps/api`, `pnpm --filter web dev`.)

## API
- `POST /api/reviews` `{ "language": "python", "code": "..." }` -> `202 { reviewId }`
- `GET /api/reviews/{id}/events` -> SSE progress (`validating->analyzing->finalizing->done`)
- `GET /api/reviews/{id}` -> final `ReviewResult` (findings with `sources[]`)
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

## Known limitations
Single snippet only (multi-file = Inc 3); in-memory job store (Redis = Inc 2+); no auth yet (Inc 6);
CORS is open (`*`) for local dev and must be restricted before deployment.
