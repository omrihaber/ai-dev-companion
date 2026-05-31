# Contributing (humans & agents)

## Architecture
Monorepo: `packages/core` (domain: Findings schema, sanitization, syntax), `apps/api` (FastAPI job API + agents), `apps/web` (React). See `docs/superpowers/specs/2026-05-31-ai-dev-companion-design.md`.

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
