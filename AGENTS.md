# Contributing (humans & agents)

## Architecture
Monorepo: `packages/core` (domain: Findings schema, sanitization, syntax), `apps/api` (FastAPI job API + agents), `apps/web` (React). See `docs/superpowers/specs/2026-05-31-ai-dev-companion-design.md`.

## Corpus pipeline (multi-file review)
`POST /api/reviews` (or `/zip`) writes all uploaded files to `ADC_WORK_ROOT/<review_id>/` on disk.
The arq worker picks up the job and:
1. Runs Semgrep + Bandit **once** over the corpus dir (breadth scan — all files).
2. Selects the agent subset: `marked` files ∪ scanner-hit files, capped at `ADC_AGENT_FILE_CAP`
   (marks can push up to `ADC_AGENT_FILE_CEILING`).
3. Fans out the 6 LLM agents per selected file (concurrency: `ADC_FILE_CONCURRENCY`).
4. Aggregates + returns `ReviewResult` with `coverage` (per-file status).

`POST /api/reviews/{id}/rerun` reuses the persisted corpus (no re-upload) and creates a new linked
review (`parentReviewId`). `GET /api/reviews/{id}/file?path=` serves raw file content (traversal-guarded).

**IMPORTANT — shared work root:** In the `infra` backend the API and arq worker are **separate
processes**. `ADC_WORK_ROOT` MUST point to a path/volume accessible by both (e.g. a named Docker
volume mounted at the same path in both services). If the worker can't read the corpus the API wrote,
jobs will fail.

**Migration 0002** adds `coverage` (JSONB) and `parent_review_id` columns. Run `task migrate` after
pulling if you use the `infra` backend.

## Invariants (do not break)
1. **The Findings schema (`adc_core.models.Finding`) is the contract.** Never change it without updating both the Pydantic model AND the generated TS types (`pnpm --filter web gen:types`) AND the tests.
2. **Add a language** only via the registry in `adc_core.sanitization.LANGUAGES` — see `skills/adding-a-language.md`.
3. **Add a model provider** only by implementing the `ModelProvider` protocol — see `skills/adding-a-model-provider.md`.
4. Backend tests never call a real LLM; use `MockProvider`.
5. API JSON is camelCase; Python is snake_case.

## Run / test
- `task up` then `task api` and `task web`
- `task test:py` / `task test:web`
- Commit style: Conventional Commits.
