# Tech Debt & CI Improvements

Known, deliberately-deferred items. Feature roadmap (Inc 2–8) lives in
[the design spec](superpowers/specs/2026-05-31-ai-dev-companion-design.md); this file tracks
smaller engineering/CI debt not tied to a whole increment.

## CI / GitHub Actions
- **Add Playwright e2e as a CI job.** Currently the full-stack e2e (`pnpm --filter web e2e`)
  runs locally only. Add a gated job that installs Chromium and runs it (it spins up the
  mock-provider API + web via Playwright's `webServer`). This is the only real automated-coverage gap.
- **Dedupe duplicate runs.** The trigger is `on: [push, pull_request]`, so a push to a PR branch
  fires two runs. Scope it (e.g. `push` on `main` + tags, `pull_request` for branches) to avoid the
  redundant run.
- **Bump deprecated Node-20 actions before 2026-06-16.** `astral-sh/setup-uv@v3`,
  `actions/checkout@v4`, `actions/setup-node@v4`, `pnpm/action-setup@v4` currently run on Node 20,
  which GitHub is deprecating. Move to the Node-24-compatible versions.

## Backend
- **Typed FastAPI `response_model`s.** Routes return plain `dict`s today; adding `response_model=`
  would enrich the OpenAPI schema and let `pnpm --filter web gen:types` auto-generate the TS types
  (replacing the hand-maintained `apps/web/src/api/types.ts` mirror).
- **Job store eviction.** The in-memory `JobManager` (`_results`, `_queues`) never evicts; fine for
  Inc 1, replaced by Redis/arq in Inc 2 (see spec). Until then, add TTL/cap if running long-lived.
- **Configurable CORS.** `allow_origins=["*"]` is local-dev only; make it env-driven before deploy.

## Frontend
- **Multi-tab SSE.** The per-review event queue is single-consumer; two tabs streaming the same
  review would split events. Acceptable for Inc 1; revisit if multi-tab/shared sessions matter.
