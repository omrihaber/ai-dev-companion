# AI Dev Companion — Design Spec

**Date:** 2026-05-31
**Status:** Approved (brainstorm) — pending implementation plan
**Repo:** https://github.com/omrihaber/ai-dev-companion
**Origin:** Cellebrite "AI Code Review Assistant" technical assignment + extended product vision

---

## 1. Overview

A full-stack, GenAI-powered code review system. A user submits code (snippet, files, or a git ref);
a multi-agent pipeline plus open-source scanners analyze it and return **structured, categorized,
source-cited findings** (security / performance / logic / style / syntax), with live progress and
click-to-highlight in the editor.

The product is built **incrementally**: each increment leaves a coherent, demoable, documented product.
The assignment's required functionality is delivered first (Inc 0–1); the extended vision follows in
dependency order (Inc 2–8). Anything not built within the 3-day window is **architected via interfaces,
stubbed, and documented as roadmap** — never left broken.

### Guiding principles
- **Open-source & local-first.** Runs with zero API keys by default (local models via Ollama; OSS scanners).
- **Architect for the vision, implement a vertical slice, document the roadmap.**
- **One stable contract** (the Findings schema) makes every later feature additive, not a rewrite.
- **Attribution everywhere.** Reused OSS is credited in docs *and* propagated into finding citations.
- **No regressions.** Invariants captured in `AGENTS.md`/`CLAUDE.md` + project `skills/`.

---

## 2. Stack Decisions

| Concern | Decision | Rationale |
|---|---|---|
| Backend | Python + FastAPI | Required; async-friendly for SSE + job orchestration |
| Frontend | React + TypeScript + Vite + Monaco | Required; Monaco gives editor + syntax highlighting + line highlight |
| Default LLM | **Local (Ollama / Qwen)** | Zero-API-key open-source demo; provider is pluggable |
| Model interface | OpenAI-compatible dialect + Anthropic adapter | Ollama/OpenAI/BYO all speak it; Claude via native tool-use |
| Multi-agent | **LangChain + LangGraph** | Graph orchestration, parallel specialists, per-node progress events |
| Vector store | **Postgres + pgvector** | One datastore for app data + vectors; minimal infra; prod-grade |
| External scanners | **SARIF-normalized adapters; Semgrep + Bandit default** | Local OSS, no account; SonarQube/CodeRabbit/PR-Agent optional adapters |
| Auth | **FastAPI-Users** | Email/password + Google OAuth + admin seeding, self-hosted |
| Notifications | **Channel interface + Novu adapter** | Ships even if full Novu self-host is cut; email/Slack channels |
| Progress transport | **SSE + polling fallback** | One-way server→client; FastAPI-friendly; feeds Novu later |
| Async execution | Inc 1: FastAPI `BackgroundTasks`; Inc 2+: **arq + Redis** | Start simple, scale to true parallel agents without API change |
| Observability | **OpenTelemetry** → local Grafana stack *or* Datadog (OTLP) | One env switch; dashboards provisioned on deploy |
| Monorepo | pnpm + Turborepo (JS), `uv` (Python), root Taskfile + Docker Compose | Polyglot orchestration; one-command local |

---

## 3. Architecture

### 3.1 Monorepo layout
```
ai-dev-companion/
├─ apps/
│  ├─ api/                # FastAPI backend (uv)
│  └─ web/                # React + TS + Vite + Monaco
├─ packages/
│  ├─ agents/             # LangGraph graphs, specialist agents, ModelProvider interface (Python)
│  ├─ core/               # domain models (Findings schema), sanitization, syntax (tree-sitter), SARIF mapper
│  └─ shared-types/       # OpenAPI-generated TS types for the frontend
├─ infra/
│  ├─ compose/            # docker-compose: api, web, postgres+pgvector, ollama, otel-collector, grafana, novu*
│  └─ observability/      # otel config, provisioned grafana dashboards
├─ docs/
│  ├─ superpowers/specs/  # this design spec
│  └─ design/             # per-increment design docs + assumptions (the presentable trail)
├─ skills/                # project skills for future agents (no-regression playbooks)
├─ e2e/                   # Playwright (frontend-driven) + API e2e
├─ AGENTS.md / CLAUDE.md  # agent contribution guide (".contribute for agents")
├─ CREDITS.md             # OSS attribution
└─ Taskfile.yml, pnpm-workspace.yaml, turbo.json, pyproject.toml
```

### 3.2 Job-based review flow (async, with progress)
```
POST /api/reviews {language, code|files|gitRef}  →  { reviewId, status: "queued" }
GET  /api/reviews/{id}/events   (SSE: live progress)
GET  /api/reviews/{id}          (snapshot / polling fallback / final result)
```
Progress stages map 1:1 to LangGraph nodes (emitting them is ~free):
```
queued → validating → analyzing (per-agent sub-status) → enriching (tools) → finalizing (aggregate/dedupe) → done | failed
```
Status payload carries `stage`, optional `percent`, and per-agent/per-tool sub-status. The same events are
what Inc 7 publishes to Novu — notifications subscribe to a stream we already emit.

### 3.3 The Findings schema (the keystone contract)
Stable from Inc 1, citation-ready from day one:
```jsonc
Finding {
  id, category: "security"|"performance"|"logic"|"style"|"syntax",
  severity: "info"|"low"|"medium"|"high"|"critical",
  title, description, recommendation,
  location: { file?, startLine, endLine, startCol?, endCol? },
  sources: [ { type: "agent"|"tool", name, confidence?, ruleId?, url? } ],  // citation backbone
  codeSnippet?
}
ReviewResult { id, status, language, model, findings[], summary, createdAt, durationMs }
```
`sources[]` is why external tools (Inc 5) are additive: they append sources, and we **dedupe/merge by
`location + category`**. A SQL-injection flagged by our agent + Semgrep + SonarQube becomes one finding
citing all three, each linking to the code section (preserving each tool's `ruleId`/`helpUri`).

---

## 4. Increments (dependency-ordered; each leaves a working product)

> Priority (user-confirmed): **Inc 0–1 first (the assignment)**, then 2→8 in order.
> Unfinished work = architect + stub + document. Every increment ships its own `docs/design/NN-name.md`.

### Inc 0 — Foundation
Monorepo scaffold (pnpm+Turborepo, `uv`, Taskfile), Docker Compose for local infra, formatting/lint
(ruff/black/eslint/prettier) + pre-commit, CI skeleton, `AGENTS.md`/`CLAUDE.md`, `skills/`, `.gitignore`
(incl. `.superpowers/`), `CREDITS.md`. **Leaves:** clean runnable scaffold.

### Inc 1 — Core review (the assignment) ✅ baseline that passes
- **API:** `POST /api/reviews`; Pydantic validation + sanitization (language allowlist Python/TS/Java via a
  registry, max LOC/byte caps, reject binary/control chars); deterministic **tree-sitter** syntax findings;
  `ReviewService` = one structured model call (constrained output via `instructor` / Anthropic tool-use,
  repair-retry on malformed JSON); findings tagged `sources:[{type:"agent", name:"core-reviewer"}]`.
- **Error handling:** model timeout / connection failure (Ollama down → actionable error) / malformed output
  → bounded retries → graceful `failed` with reason surfaced in UI.
- **Frontend (3 screens):** Review Workspace (side-by-side), Review History list, Settings (model provider UI).
- **Deliverables:** 3 sample test cases with documented expected outputs, README.

### Inc 2 — Multi-agent + model abstraction (headline differentiator)
LangGraph: `[validate+syntax] → [dispatch] → {security, performance, logic, quality} parallel → [aggregate/dedupe/rank] → done`.
Each specialist = focused agent (own prompt seeded/adapted from **awesome-reviewers**, own model override),
emits source-tagged findings + SSE sub-status. Aggregator = the citation-merge logic reused by Inc 5.
`ModelProvider` protocol (`chat`, `structured_output`, `embeddings`) with Ollama/Anthropic/OpenAI-compatible
adapters; BYO = env config. **Same API/schema/frontend as Inc 1.**

### Inc 3 — Multi-file + retrieval
Multi-file/zip upload; chunking + embeddings + **pgvector**; retrieval + context compaction feeding agents.
**Leaves:** codebase-level review.

### Inc 4 — Git ingestion + triggers
Ingest from git URL / repo+branch / commit hash; webhook endpoint for push → review (CI hook).
**Leaves:** review real repos + CI trigger.

### Inc 5 — External scanners + unified citations (high priority)
SARIF-normalized **scanner-adapter interface**; **Semgrep + Bandit** as local OSS default (Dockerized,
no account, SARIF output); one **SARIF→Findings mapper** unlocks many tools (gosec/CodeQL/Brakeman/…).
SonarQube / CodeRabbit / PR-Agent as optional adapters. Run in parallel with our agents; merge + cite all
sources with links to the code section. Attribution preserved in findings + `CREDITS.md`.

### Inc 6 — Auth
FastAPI-Users: email/password + Google OAuth + **preconfigured admin** (seeded via `task seed`); per-user reviews.

### Inc 7 — Notifications
Notification-channel abstraction (email via SMTP/Resend, Slack webhook) with **Novu** as the center behind it;
subscribes to review progress/completion events ("review complete", "critical finding").

### Inc 8 — Observability + production-readiness
OpenTelemetry (FastAPI + per-agent/per-tool spans + frontend web-vitals); exporter switch (local Grafana
stack: Loki/Tempo/Prometheus + provisioned dashboards — *or* Datadog via OTLP); `k6` load test against
mocked model; full Playwright + API e2e.

---

## 5. UI Design

**Layout:** side-by-side Review Workspace — editor left, categorized findings right; stacks vertically below ~900px.

**Inc 1 screens:** Review Workspace, Review History list, Settings (model provider UI).
**Deferred:** Report/Export view (bonus), Auth screens (Inc 6), Notifications inbox (Inc 7).
Observability dashboards are external (Grafana/Datadog), linked out — not in-app.

**Review Workspace (Inc 1):**
- Top nav: logo · New Review · History · Settings · 🔔 (later) · user menu (later).
- Left pane: input-mode tabs (Paste now; Upload=Inc3, Git=Inc4) + language dropdown + Monaco editor
  (syntax highlighting) + **Review Code** button (loading state).
- Right pane: **progress stepper** (Validating→Analyzing→Enriching→Finalizing→Done) with per-agent/per-tool
  sub-status from SSE; **findings list** grouped/filterable by category, sortable by severity. Each finding
  card shows severity badge, location (clickable `↗`), description, recommendation, and **source citations**
  (agent + tools). Clicking a finding scrolls + highlights the line(s) in Monaco. Summary bar with counts.
- Responsive: panes stack; progress collapses to a compact bar.

---

## 6. Testing Strategy

- **Unit** (per package): sanitization, tree-sitter syntax, SARIF→Findings mapper, aggregation/dedupe,
  provider adapters (mocked). Python `pytest` + coverage gate; JS `vitest`.
- **Contract:** Findings schema validated both sides (Pydantic ⇄ generated TS types) — no frontend/backend drift.
- **API e2e:** API + Postgres in Compose; drive `POST /reviews` → SSE → final result with mocked model
  (deterministic) and a recorded-local-model path.
- **Frontend-driven e2e:** **Playwright** drives the real browser (paste → Review → watch progress →
  assert categorized findings + click-to-highlight) against the full stack.
- **Determinism rule:** assertions target **schema + expected categories/locations**, not exact LLM wording;
  documented sample outputs use a capable model.
- CI: unit + contract + API-e2e on every push; Playwright e2e as a gated job.

---

## 7. Reused OSS (credited in `CREDITS.md` + in finding citations)

| Project | License | Use |
|---|---|---|
| [baz-scm/awesome-reviewers](https://github.com/baz-scm/awesome-reviewers) | Apache-2.0 | Seed/adapt specialist-agent prompts (Inc 2) |
| [Semgrep](https://semgrep.dev) | OSS | Default external scanner (Inc 5), SARIF |
| [Bandit](https://github.com/PyCQA/bandit) | Apache-2.0 | Python security scanner (Inc 5), SARIF |
| [Qodo PR-Agent](https://github.com/qodo-ai/pr-agent) | Apache-2.0 | Optional scanner adapter / reference (Inc 5) |
| SonarQube / CodeRabbit | — | Optional adapters (Inc 5) |

Attribution is propagated into the Findings model: a Semgrep-derived finding cites Semgrep + its rule URL;
a prompt-seeded agent records its lineage. The SARIF mapper preserves each tool's `ruleId`/`helpUri`.

---

## 8. No-Regression Tooling for Future Agents

- **`AGENTS.md` + `CLAUDE.md`:** architecture map + invariants (never change the Findings contract without
  updating both schemas + tests; add scanners only via SARIF adapter; add languages via the registry),
  run/test/commit conventions.
- **`skills/`:** project playbooks — `adding-a-scanner-adapter`, `adding-a-language`,
  `adding-a-model-provider`, `adding-a-specialist-agent`.

---

## 9. Known Limitations / Future Improvements

- Local-model default produces weaker/nondeterministic reviews; reviewers can drop in an Anthropic/OpenAI key
  via Settings/env for full quality. Sample expected outputs are generated with a capable model.
- 3-day window means Inc 3–8 may ship as interfaces + stubs + docs rather than fully built; the roadmap
  above defines the intended completion path.
- Full Novu self-host may be reduced to the channel abstraction + email if time-constrained.
- SonarQube/CodeRabbit adapters may be documented-only if not reached.
```
