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
- **Work-dir retention / disk growth.** Per-review corpus dirs under `ADC_WORK_ROOT` are retained
  to power History + Re-run; there is no TTL/cleanup job yet (disk grows unbounded). Acceptable for
  local/demo use; add a sweep job before any shared or production deployment.
- **Scanner finding categories.** Scanner findings (Semgrep/Bandit) are categorised as `security` by
  default; rule-tag-based category refinement (mapping rule tags → `performance`, `logic`, etc.) is
  deferred.

## Frontend
- **Adopt shadcn/ui + Tailwind.** The UI currently uses a hand-rolled dark theme (CSS variables in
  `apps/web/src/styles.css`) — clean and dependency-free, but a proper component system (shadcn/ui +
  Tailwind + Radix primitives) would give accessible, consistent components (dialogs, dropdowns,
  toasts, tabs for the input modes) as the surface grows in later increments. Deferred because it's a
  build/dependency change (Tailwind config, component generation) better scoped as its own increment.
- **Multi-tab SSE.** The per-review event queue is single-consumer; two tabs streaming the same
  review would split events. Acceptable for Inc 1; revisit if multi-tab/shared sessions matter.

## Product / UX backlog
- **History: open a past review (restore state).** Today the History page is a read-only list.
  Clicking a row should reopen that review — load its findings into the right pane and the original
  code into the editor — so you can revisit/inspect what was scanned. Needs the API to return the
  stored code (or a code reference) alongside the `ReviewResult`.
- **Settings: make it editable, not just informational.** The Settings page currently only displays
  the env-based config. It should let the user change the provider/model (and enter a BYO key) from
  the UI and have it take effect (persist per-user once auth lands in Inc 6; until then, a
  runtime-overridable server setting + restart-free provider rebuild).
- **Navbar: surface upcoming entry points ("coming soon").** Add nav items for the planned
  integrations — **CI / GitHub** (webhook + PR triggers, Inc 4), plus repo/branch/commit ingestion —
  shown as disabled "coming soon" links so the roadmap is visible in-product.
- **Scan scope: deltas vs. full version (needs replanning).** When reviewing a git ref / PR, let the
  user choose to scan **only the diff/deltas** or the **entire version**. This is non-trivial: it
  affects ingestion, the retrieval/context strategy (Inc 3), how findings map to changed lines, and
  the citation/location model. Flag for a dedicated design pass when Inc 4 (git ingestion + triggers)
  is planned — likely a first-class `scope: "delta" | "full"` option on the review request.
