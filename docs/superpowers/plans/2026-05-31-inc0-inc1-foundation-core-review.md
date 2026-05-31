# Inc 0 + Inc 1: Foundation + Core Review — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the monorepo foundation and a complete, working single-snippet AI code-review app (FastAPI + React) that returns structured, categorized, source-cited findings with live progress — the full assignment, end-to-end.

**Architecture:** Polyglot monorepo (pnpm+Turborepo for JS, `uv` for Python, root Taskfile + Docker Compose). The backend exposes an async **job-based** review API (`POST /api/reviews` → SSE progress → final `ReviewResult`). A `ReviewService` runs deterministic tree-sitter syntax checks + one structured LLM call through a pluggable `ModelProvider` (Ollama default, mockable for tests). All output conforms to a stable **Findings schema** with a `sources[]` citation array. The React frontend (Monaco workspace + history + settings) consumes the API via generated types and an SSE hook.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, `sse-starlette`, `instructor` + OpenAI client (Ollama), `tree-sitter` + `tree-sitter-language-pack`, pytest + pytest-asyncio + httpx; React + TS + Vite, `@monaco-editor/react`, TanStack Query, `openapi-typescript`, vitest + Testing Library, Playwright; Docker Compose (Postgres+pgvector, Ollama).

**Conventions:**
- API JSON is **camelCase** (Pydantic `alias_generator=to_camel`, `populate_by_name=True`); Python code is snake_case.
- TDD: write the failing test, watch it fail, minimal implementation, watch it pass, commit.
- Backend tests never call a real LLM — they use `MockProvider`.

---

## File Structure

```
ai-dev-companion/
├─ pnpm-workspace.yaml, turbo.json, package.json, Taskfile.yml, pyproject.toml, .env.example
├─ AGENTS.md, CLAUDE.md, CREDITS.md
├─ .github/workflows/ci.yml
├─ infra/compose/docker-compose.yml
├─ skills/                         # adding-a-language, adding-a-model-provider (stubs)
├─ packages/
│  └─ core/  (Python pkg `adc_core`)
│     ├─ pyproject.toml
│     ├─ src/adc_core/__init__.py
│     ├─ src/adc_core/models.py          # Findings schema (Pydantic)
│     ├─ src/adc_core/sanitization.py    # language registry + validate_submission
│     ├─ src/adc_core/syntax.py          # tree-sitter syntax checker
│     └─ tests/{test_models,test_sanitization,test_syntax}.py
├─ apps/
│  ├─ api/  (Python pkg `adc_api`)
│  │  ├─ pyproject.toml
│  │  ├─ src/adc_api/main.py             # FastAPI app + routes
│  │  ├─ src/adc_api/providers.py        # ModelProvider protocol + Ollama + Mock
│  │  ├─ src/adc_api/review_service.py   # orchestration
│  │  ├─ src/adc_api/jobs.py             # ReviewStore + EventBus + run_review
│  │  ├─ src/adc_api/schemas.py          # request/response/progress models
│  │  └─ tests/{test_review_service,test_jobs,test_api}.py
│  └─ web/  (React app)
│     ├─ package.json, vite.config.ts, tsconfig.json, playwright.config.ts
│     ├─ src/api/{client.ts,types.gen.ts}
│     ├─ src/hooks/useReviewStream.ts
│     ├─ src/components/{Workspace,FindingCard,ProgressStepper}.tsx
│     ├─ src/pages/{HistoryPage,SettingsPage}.tsx
│     ├─ src/App.tsx, src/main.tsx
│     └─ tests/ + e2e/
└─ docs/test-cases/inc1-samples.md
```

---

# PHASE A — Inc 0: Foundation

### Task 1: Repo skeleton + Taskfile + workspace manifests

**Files:**
- Create: `pnpm-workspace.yaml`, `turbo.json`, `package.json`, `Taskfile.yml`, `pyproject.toml`

- [ ] **Step 1: Create `pnpm-workspace.yaml`**

```yaml
packages:
  - "apps/web"
```

- [ ] **Step 2: Create root `package.json`**

```json
{
  "name": "ai-dev-companion",
  "private": true,
  "packageManager": "pnpm@9.12.0",
  "devDependencies": { "turbo": "^2.1.0", "prettier": "^3.3.0" },
  "scripts": {
    "format": "prettier --write \"apps/web/**/*.{ts,tsx,css}\"",
    "lint": "turbo run lint",
    "test": "turbo run test"
  }
}
```

- [ ] **Step 3: Create `turbo.json`**

```json
{
  "$schema": "https://turbo.build/schema.json",
  "tasks": {
    "build": { "outputs": ["dist/**"] },
    "lint": {},
    "test": { "dependsOn": ["^build"] }
  }
}
```

- [ ] **Step 4: Create root `pyproject.toml` (uv workspace + tooling)**

```toml
[tool.uv.workspace]
members = ["packages/core", "apps/api"]

[tool.ruff]
line-length = 100
target-version = "py312"
[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.black]
line-length = 100

[tool.pytest.ini_options]
asyncio_mode = "auto"
addopts = "-q"
```

- [ ] **Step 5: Create `Taskfile.yml`**

```yaml
version: "3"
tasks:
  up: { desc: "Start local infra", cmds: ["docker compose -f infra/compose/docker-compose.yml up -d"] }
  down: { cmds: ["docker compose -f infra/compose/docker-compose.yml down"] }
  api: { dir: apps/api, cmds: ["uv run uvicorn adc_api.main:app --reload --port 8000"] }
  web: { dir: apps/web, cmds: ["pnpm dev"] }
  test:py: { cmds: ["uv run pytest packages/core apps/api"] }
  test:web: { dir: apps/web, cmds: ["pnpm test"] }
  pull-model: { cmds: ["docker compose -f infra/compose/docker-compose.yml exec ollama ollama pull qwen2.5-coder:7b"] }
```

- [ ] **Step 6: Commit**

```bash
git add pnpm-workspace.yaml turbo.json package.json Taskfile.yml pyproject.toml
git commit -m "chore: monorepo skeleton (pnpm+turbo, uv workspace, Taskfile)"
```

### Task 2: Docker Compose (Postgres+pgvector, Ollama) + .env.example

**Files:**
- Create: `infra/compose/docker-compose.yml`, `.env.example`

- [ ] **Step 1: Create `infra/compose/docker-compose.yml`**

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: adc
      POSTGRES_PASSWORD: adc
      POSTGRES_DB: adc
    ports: ["5432:5432"]
    volumes: ["pgdata:/var/lib/postgresql/data"]
  ollama:
    image: ollama/ollama:latest
    ports: ["11434:11434"]
    volumes: ["ollama:/root/.ollama"]
volumes:
  pgdata:
  ollama:
```

- [ ] **Step 2: Create `.env.example`**

```bash
# Model provider: "ollama" (default) | "anthropic" | "openai"
ADC_MODEL_PROVIDER=ollama
ADC_MODEL=qwen2.5-coder:7b
ADC_OLLAMA_BASE_URL=http://localhost:11434/v1
# For BYO/cloud:
# ADC_ANTHROPIC_API_KEY=
# ADC_OPENAI_API_KEY=
# ADC_OPENAI_BASE_URL=
ADC_DATABASE_URL=postgresql://adc:adc@localhost:5432/adc
ADC_MAX_CODE_BYTES=100000
ADC_MAX_CODE_LINES=2000
VITE_API_BASE_URL=http://localhost:8000
```

- [ ] **Step 3: Verify compose config parses**

Run: `docker compose -f infra/compose/docker-compose.yml config -q`
Expected: no output, exit 0.

- [ ] **Step 4: Commit**

```bash
git add infra/compose/docker-compose.yml .env.example
git commit -m "chore: local infra compose (pgvector, ollama) + env template"
```

### Task 3: Agent docs, credits, skills stubs, CI skeleton

**Files:**
- Create: `AGENTS.md`, `CLAUDE.md`, `CREDITS.md`, `skills/adding-a-language.md`, `skills/adding-a-model-provider.md`, `.github/workflows/ci.yml`

- [ ] **Step 1: Create `AGENTS.md`**

```markdown
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
```

- [ ] **Step 2: Create `CLAUDE.md`**

```markdown
See AGENTS.md for architecture, invariants, and run/test instructions. This file exists so Claude Code auto-loads the same guidance.
```

- [ ] **Step 3: Create `CREDITS.md`**

```markdown
# Credits & Attribution

This project reuses open-source work (attribution also propagated into finding `sources[]` where applicable):

- [baz-scm/awesome-reviewers](https://github.com/baz-scm/awesome-reviewers) — Apache-2.0 — seeds specialist-agent prompts (Inc 2).
- [Semgrep](https://semgrep.dev), [Bandit](https://github.com/PyCQA/bandit) — default external scanners (Inc 5).
- [Qodo PR-Agent](https://github.com/qodo-ai/pr-agent) — Apache-2.0 — optional scanner adapter (Inc 5).
```

- [ ] **Step 4: Create `skills/adding-a-language.md`**

```markdown
# Skill: Adding a language
1. Add an entry to `LANGUAGES` in `packages/core/src/adc_core/sanitization.py` mapping the language id to its tree-sitter grammar name.
2. Add a fixture + test in `packages/core/tests/test_syntax.py` asserting a known syntax error is detected.
3. Add the language to the frontend dropdown in `apps/web/src/components/Workspace.tsx`.
4. Run `task test:py` and `task test:web`.
```

- [ ] **Step 5: Create `skills/adding-a-model-provider.md`**

```markdown
# Skill: Adding a model provider
1. Implement the `ModelProvider` protocol (`name`, `model`, `async review(code, language) -> list[RawFinding]`) in `apps/api/src/adc_api/providers.py`.
2. Register it in `build_provider()` keyed by `ADC_MODEL_PROVIDER`.
3. Add a unit test using recorded output (never a live call).
```

- [ ] **Step 6: Create `.github/workflows/ci.yml`**

```yaml
name: CI
on: [push, pull_request]
jobs:
  python:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv python install 3.12
      - run: uv sync
      - run: uv run ruff check .
      - run: uv run pytest packages/core apps/api
  web:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v4
        with: { version: 9 }
      - uses: actions/setup-node@v4
        with: { node-version: 20, cache: pnpm }
      - run: pnpm install --frozen-lockfile
      - run: pnpm --filter web lint
      - run: pnpm --filter web test -- --run
```

- [ ] **Step 7: Commit**

```bash
git add AGENTS.md CLAUDE.md CREDITS.md skills .github/workflows/ci.yml
git commit -m "docs+ci: agent contribution guide, credits, skills stubs, CI skeleton"
```

---

# PHASE B — Inc 1: Backend (`packages/core` + `apps/api`)

### Task 4: `adc_core` package + Findings schema

**Files:**
- Create: `packages/core/pyproject.toml`, `packages/core/src/adc_core/__init__.py`, `packages/core/src/adc_core/models.py`
- Test: `packages/core/tests/test_models.py`

- [ ] **Step 1: Create `packages/core/pyproject.toml`**

```toml
[project]
name = "adc-core"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["pydantic>=2.7", "tree-sitter>=0.23", "tree-sitter-language-pack>=0.7"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/adc_core"]

[dependency-groups]
dev = ["pytest>=8", "pytest-asyncio>=0.24"]
```

- [ ] **Step 2: Write the failing test `packages/core/tests/test_models.py`**

```python
from adc_core.models import Finding, Location, Source, ReviewResult

def test_finding_serializes_to_camelcase_with_sources():
    f = Finding(
        id="f1", category="security", severity="high",
        title="SQL injection", description="String concat in query",
        recommendation="Use parameterized queries",
        location=Location(start_line=2, end_line=2),
        sources=[Source(type="agent", name="core-reviewer")],
    )
    data = f.model_dump(by_alias=True)
    assert data["location"]["startLine"] == 2
    assert data["sources"][0]["name"] == "core-reviewer"

def test_review_result_defaults_status_and_findings():
    r = ReviewResult(id="r1", language="python", model="mock")
    assert r.status == "queued"
    assert r.findings == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest packages/core/tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'adc_core'`.

- [ ] **Step 4: Create `packages/core/src/adc_core/__init__.py`** (empty file)

- [ ] **Step 5: Implement `packages/core/src/adc_core/models.py`**

```python
from __future__ import annotations
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

Category = Literal["security", "performance", "logic", "style", "syntax"]
Severity = Literal["info", "low", "medium", "high", "critical"]
ReviewStatus = Literal[
    "queued", "validating", "analyzing", "enriching", "finalizing", "done", "failed"
]

class _Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

class Location(_Camel):
    file: str | None = None
    start_line: int
    end_line: int
    start_col: int | None = None
    end_col: int | None = None

class Source(_Camel):
    type: Literal["agent", "tool"]
    name: str
    confidence: float | None = None
    rule_id: str | None = None
    url: str | None = None

class Finding(_Camel):
    id: str
    category: Category
    severity: Severity
    title: str
    description: str
    recommendation: str
    location: Location
    sources: list[Source] = Field(default_factory=list)
    code_snippet: str | None = None

class ReviewResult(_Camel):
    id: str
    status: ReviewStatus = "queued"
    language: str
    model: str
    findings: list[Finding] = Field(default_factory=list)
    summary: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    duration_ms: int | None = None
    error: str | None = None
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest packages/core/tests/test_models.py -v`
Expected: PASS (2 passed).

- [ ] **Step 7: Commit**

```bash
git add packages/core
git commit -m "feat(core): Findings schema (camelCase, citation-ready)"
```

### Task 5: Sanitization + language registry

**Files:**
- Create: `packages/core/src/adc_core/sanitization.py`
- Test: `packages/core/tests/test_sanitization.py`

- [ ] **Step 1: Write the failing test `packages/core/tests/test_sanitization.py`**

```python
import pytest
from adc_core.sanitization import validate_submission, SubmissionError, LANGUAGES

def test_accepts_supported_language_and_returns_code():
    code = "print('hi')\n"
    assert validate_submission("python", code, max_bytes=1000, max_lines=100) == code

def test_rejects_unknown_language():
    with pytest.raises(SubmissionError, match="unsupported language"):
        validate_submission("brainfuck", "x", max_bytes=1000, max_lines=100)

def test_rejects_oversized_code():
    with pytest.raises(SubmissionError, match="too large"):
        validate_submission("python", "a" * 2000, max_bytes=1000, max_lines=100)

def test_rejects_binary_null_bytes():
    with pytest.raises(SubmissionError, match="binary"):
        validate_submission("python", "ok\x00bad", max_bytes=1000, max_lines=100)

def test_registry_has_required_languages():
    assert {"python", "typescript", "java"} <= set(LANGUAGES)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/core/tests/test_sanitization.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `packages/core/src/adc_core/sanitization.py`**

```python
from __future__ import annotations

# language id -> tree-sitter grammar name (see tree_sitter_language_pack)
LANGUAGES: dict[str, str] = {
    "python": "python",
    "typescript": "typescript",
    "java": "java",
}

class SubmissionError(ValueError):
    """Raised when a code submission fails validation/sanitization."""

def validate_submission(language: str, code: str, *, max_bytes: int, max_lines: int) -> str:
    if language not in LANGUAGES:
        raise SubmissionError(f"unsupported language: {language!r}")
    if not code.strip():
        raise SubmissionError("empty code submission")
    if "\x00" in code:
        raise SubmissionError("binary or non-text content detected")
    if len(code.encode("utf-8")) > max_bytes:
        raise SubmissionError(f"code too large (> {max_bytes} bytes)")
    if code.count("\n") + 1 > max_lines:
        raise SubmissionError(f"too many lines (> {max_lines})")
    return code
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/core/tests/test_sanitization.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/adc_core/sanitization.py packages/core/tests/test_sanitization.py
git commit -m "feat(core): input sanitization + language registry"
```

### Task 6: Tree-sitter syntax checker

**Files:**
- Create: `packages/core/src/adc_core/syntax.py`
- Test: `packages/core/tests/test_syntax.py`

- [ ] **Step 1: Write the failing test `packages/core/tests/test_syntax.py`**

```python
from adc_core.syntax import check_syntax

def test_valid_python_has_no_syntax_findings():
    assert check_syntax("python", "x = 1\n") == []

def test_invalid_python_reports_syntax_finding_with_location():
    findings = check_syntax("python", "def f(:\n    pass\n")
    assert len(findings) >= 1
    f = findings[0]
    assert f.category == "syntax"
    assert f.location.start_line >= 1
    assert f.sources[0].name == "tree-sitter"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/core/tests/test_syntax.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `packages/core/src/adc_core/syntax.py`**

```python
from __future__ import annotations
import uuid
from tree_sitter_language_pack import get_parser
from adc_core.models import Finding, Location, Source
from adc_core.sanitization import LANGUAGES

def check_syntax(language: str, code: str) -> list[Finding]:
    """Deterministic parse-error detection via tree-sitter. Returns syntax findings."""
    grammar = LANGUAGES.get(language)
    if grammar is None:
        return []
    parser = get_parser(grammar)
    tree = parser.parse(code.encode("utf-8"))
    findings: list[Finding] = []
    cursor = tree.walk()

    def visit(node) -> None:
        if node.is_error or node.is_missing:
            findings.append(
                Finding(
                    id=str(uuid.uuid4()),
                    category="syntax",
                    severity="high",
                    title="Syntax error",
                    description=f"Parser could not parse this region ({node.type}).",
                    recommendation="Fix the syntax error so the code parses.",
                    location=Location(
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        start_col=node.start_point[1],
                        end_col=node.end_point[1],
                    ),
                    sources=[Source(type="tool", name="tree-sitter")],
                )
            )
        for child in node.children:
            visit(child)

    visit(cursor.node)
    return findings
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/core/tests/test_syntax.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/adc_core/syntax.py packages/core/tests/test_syntax.py
git commit -m "feat(core): tree-sitter syntax validation -> syntax findings"
```

### Task 7: `adc_api` package + schemas + ModelProvider (Mock + Ollama)

**Files:**
- Create: `apps/api/pyproject.toml`, `apps/api/src/adc_api/__init__.py`, `apps/api/src/adc_api/schemas.py`, `apps/api/src/adc_api/providers.py`
- Test: `apps/api/tests/test_providers.py`

- [ ] **Step 1: Create `apps/api/pyproject.toml`**

```toml
[project]
name = "adc-api"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "adc-core",
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "sse-starlette>=2.1",
  "pydantic-settings>=2.4",
  "instructor>=1.5",
  "openai>=1.40",
]

[tool.uv.sources]
adc-core = { workspace = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/adc_api"]

[dependency-groups]
dev = ["pytest>=8", "pytest-asyncio>=0.24", "httpx>=0.27"]
```

- [ ] **Step 2: Create `apps/api/src/adc_api/__init__.py`** (empty file)

- [ ] **Step 3: Create `apps/api/src/adc_api/schemas.py`**

```python
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from adc_core.models import ReviewStatus

class _Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

class ReviewRequest(_Camel):
    language: str
    code: str

class RawFinding(_Camel):
    """Shape the LLM returns; ReviewService converts these into Findings."""
    category: Literal["security", "performance", "logic", "style"]
    severity: Literal["info", "low", "medium", "high", "critical"]
    title: str
    description: str
    recommendation: str
    start_line: int = 1
    end_line: int = 1

class ReviewOutput(_Camel):
    findings: list[RawFinding] = Field(default_factory=list)

class ProgressEvent(_Camel):
    review_id: str
    stage: ReviewStatus
    percent: int | None = None
    sub_status: dict[str, str] = Field(default_factory=dict)
    message: str | None = None
```

- [ ] **Step 4: Write the failing test `apps/api/tests/test_providers.py`**

```python
import pytest
from adc_api.providers import MockProvider

@pytest.mark.asyncio
async def test_mock_provider_returns_seeded_findings():
    provider = MockProvider(seed=[{
        "category": "security", "severity": "high", "title": "SQLi",
        "description": "d", "recommendation": "r", "start_line": 2, "end_line": 2,
    }])
    out = await provider.review("code", "python")
    assert out[0].category == "security"
    assert provider.name == "core-reviewer"
```

- [ ] **Step 5: Run test to verify it fails**

Run: `uv run pytest apps/api/tests/test_providers.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 6: Implement `apps/api/src/adc_api/providers.py`**

```python
from __future__ import annotations
import os
from typing import Protocol
from adc_api.schemas import RawFinding, ReviewOutput

REVIEW_SYSTEM_PROMPT = (
    "You are a senior code reviewer. Analyze the {language} code and report concrete "
    "issues across security, performance, logic, and style. For each issue give a short "
    "title, a clear description, an actionable recommendation, and the 1-based line range. "
    "Only report real issues."
)

class ModelProvider(Protocol):
    name: str
    model: str
    async def review(self, code: str, language: str) -> list[RawFinding]: ...

class MockProvider:
    """Deterministic provider for tests/CI (no network)."""
    name = "core-reviewer"
    model = "mock"

    def __init__(self, seed: list[dict] | None = None) -> None:
        self._seed = seed or []

    async def review(self, code: str, language: str) -> list[RawFinding]:
        return [RawFinding(**item) for item in self._seed]

class OllamaProvider:
    """OpenAI-compatible provider (Ollama by default; works for any OpenAI-compatible endpoint)."""
    name = "core-reviewer"

    def __init__(self, base_url: str, model: str, api_key: str = "ollama") -> None:
        import instructor
        from openai import AsyncOpenAI
        self.model = model
        self._client = instructor.from_openai(AsyncOpenAI(base_url=base_url, api_key=api_key))

    async def review(self, code: str, language: str) -> list[RawFinding]:
        out: ReviewOutput = await self._client.chat.completions.create(
            model=self.model,
            response_model=ReviewOutput,
            messages=[
                {"role": "system", "content": REVIEW_SYSTEM_PROMPT.format(language=language)},
                {"role": "user", "content": f"```{language}\n{code}\n```"},
            ],
        )
        return out.findings

def build_provider() -> ModelProvider:
    kind = os.getenv("ADC_MODEL_PROVIDER", "ollama")
    model = os.getenv("ADC_MODEL", "qwen2.5-coder:7b")
    if kind == "ollama":
        return OllamaProvider(os.getenv("ADC_OLLAMA_BASE_URL", "http://localhost:11434/v1"), model)
    if kind == "openai":
        return OllamaProvider(
            os.getenv("ADC_OPENAI_BASE_URL", "https://api.openai.com/v1"),
            model, api_key=os.environ["ADC_OPENAI_API_KEY"],
        )
    raise ValueError(f"unknown provider: {kind}")
```

- [ ] **Step 7: Run test to verify it passes**

Run: `uv run pytest apps/api/tests/test_providers.py -v`
Expected: PASS (1 passed).

- [ ] **Step 8: Commit**

```bash
git add apps/api/pyproject.toml apps/api/src/adc_api/__init__.py apps/api/src/adc_api/schemas.py apps/api/src/adc_api/providers.py apps/api/tests/test_providers.py
git commit -m "feat(api): schemas + ModelProvider protocol (Mock + Ollama/OpenAI-compatible)"
```

### Task 8: ReviewService (orchestration + progress)

**Files:**
- Create: `apps/api/src/adc_api/review_service.py`
- Test: `apps/api/tests/test_review_service.py`

- [ ] **Step 1: Write the failing test `apps/api/tests/test_review_service.py`**

```python
import pytest
from adc_api.providers import MockProvider
from adc_api.review_service import ReviewService

@pytest.mark.asyncio
async def test_run_merges_syntax_and_agent_findings_and_emits_progress():
    provider = MockProvider(seed=[{
        "category": "security", "severity": "high", "title": "SQLi",
        "description": "concat", "recommendation": "params", "start_line": 2, "end_line": 2,
    }])
    stages: list[str] = []
    svc = ReviewService(provider=provider)
    result = await svc.run(
        review_id="r1", language="python",
        code="def f(uid):\n    q = 'SELECT ' + uid\n",
        on_progress=lambda e: stages.append(e.stage),
    )
    assert result.status == "done"
    cats = {f.category for f in result.findings}
    assert "security" in cats
    assert result.findings[0].sources  # citation present
    assert "analyzing" in stages and "done" in stages

@pytest.mark.asyncio
async def test_run_marks_failed_on_provider_error():
    class Boom(MockProvider):
        async def review(self, code, language):
            raise RuntimeError("model down")
    svc = ReviewService(provider=Boom())
    result = await svc.run(review_id="r2", language="python", code="x=1\n", on_progress=lambda e: None)
    assert result.status == "failed"
    assert "model down" in (result.error or "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest apps/api/tests/test_review_service.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `apps/api/src/adc_api/review_service.py`**

```python
from __future__ import annotations
import time
import uuid
from collections.abc import Callable
from adc_core.models import Finding, Location, ReviewResult, Source
from adc_core.syntax import check_syntax
from adc_api.providers import ModelProvider
from adc_api.schemas import ProgressEvent, RawFinding

OnProgress = Callable[[ProgressEvent], None]

def _to_finding(raw: RawFinding, provider_name: str) -> Finding:
    return Finding(
        id=str(uuid.uuid4()),
        category=raw.category,
        severity=raw.severity,
        title=raw.title,
        description=raw.description,
        recommendation=raw.recommendation,
        location=Location(start_line=raw.start_line, end_line=raw.end_line),
        sources=[Source(type="agent", name=provider_name)],
    )

def _summarize(findings: list[Finding]) -> str:
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.category] = counts.get(f.category, 0) + 1
    return ", ".join(f"{n} {c}" for c, n in sorted(counts.items())) or "no issues found"

class ReviewService:
    def __init__(self, provider: ModelProvider) -> None:
        self._provider = provider

    async def run(self, *, review_id: str, language: str, code: str, on_progress: OnProgress) -> ReviewResult:
        started = time.monotonic()
        result = ReviewResult(id=review_id, language=language, model=self._provider.model)

        def emit(stage, **kw):
            result.status = stage
            on_progress(ProgressEvent(review_id=review_id, stage=stage, **kw))

        try:
            emit("validating")
            findings = check_syntax(language, code)

            emit("analyzing", sub_status={"core-reviewer": "running"})
            raw = await self._provider.review(code, language)
            findings += [_to_finding(r, self._provider.name) for r in raw]

            emit("finalizing")
            result.findings = findings
            result.summary = _summarize(findings)
            result.duration_ms = int((time.monotonic() - started) * 1000)
            emit("done")
        except Exception as exc:  # noqa: BLE001 — surfaced to the user as a failed job
            result.error = str(exc)
            result.duration_ms = int((time.monotonic() - started) * 1000)
            emit("failed", message=str(exc))
        return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest apps/api/tests/test_review_service.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/adc_api/review_service.py apps/api/tests/test_review_service.py
git commit -m "feat(api): ReviewService orchestration (syntax + agent merge, progress, failure)"
```

### Task 9: Job store + event bus (async fan-out for SSE)

**Files:**
- Create: `apps/api/src/adc_api/jobs.py`
- Test: `apps/api/tests/test_jobs.py`

- [ ] **Step 1: Write the failing test `apps/api/tests/test_jobs.py`**

```python
import asyncio
import pytest
from adc_api.jobs import JobManager
from adc_api.providers import MockProvider

@pytest.mark.asyncio
async def test_create_runs_review_and_streams_until_terminal():
    jm = JobManager(provider_factory=lambda: MockProvider(seed=[{
        "category": "style", "severity": "low", "title": "t",
        "description": "d", "recommendation": "r", "start_line": 1, "end_line": 1,
    }]))
    review_id = jm.create(language="python", code="x=1\n", max_bytes=1000, max_lines=100)
    stages = []
    async for event in jm.stream(review_id):
        stages.append(event.stage)
    assert stages[-1] == "done"
    result = jm.get(review_id)
    assert result.status == "done" and len(result.findings) == 1

@pytest.mark.asyncio
async def test_create_rejects_bad_submission():
    jm = JobManager(provider_factory=lambda: MockProvider())
    with pytest.raises(Exception):
        jm.create(language="cobol", code="x", max_bytes=1000, max_lines=100)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest apps/api/tests/test_jobs.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `apps/api/src/adc_api/jobs.py`**

```python
from __future__ import annotations
import asyncio
import uuid
from collections.abc import AsyncIterator, Callable
from adc_core.models import ReviewResult
from adc_core.sanitization import validate_submission
from adc_api.providers import ModelProvider
from adc_api.review_service import ReviewService
from adc_api.schemas import ProgressEvent

_TERMINAL = {"done", "failed"}

class JobManager:
    """In-memory job store + per-review async event bus (Inc 1). Swappable for arq+Redis in Inc 2+."""

    def __init__(self, provider_factory: Callable[[], ModelProvider]) -> None:
        self._provider_factory = provider_factory
        self._results: dict[str, ReviewResult] = {}
        self._queues: dict[str, asyncio.Queue[ProgressEvent | None]] = {}

    def create(self, *, language: str, code: str, max_bytes: int, max_lines: int) -> str:
        code = validate_submission(language, code, max_bytes=max_bytes, max_lines=max_lines)
        review_id = str(uuid.uuid4())
        self._results[review_id] = ReviewResult(id=review_id, language=language, model="pending")
        self._queues[review_id] = asyncio.Queue()
        asyncio.create_task(self._run(review_id, language, code))
        return review_id

    async def _run(self, review_id: str, language: str, code: str) -> None:
        queue = self._queues[review_id]

        def on_progress(event: ProgressEvent) -> None:
            queue.put_nowait(event)

        svc = ReviewService(provider=self._provider_factory())
        result = await svc.run(review_id=review_id, language=language, code=code, on_progress=on_progress)
        self._results[review_id] = result
        queue.put_nowait(None)  # sentinel: stream complete

    async def stream(self, review_id: str) -> AsyncIterator[ProgressEvent]:
        queue = self._queues[review_id]
        while True:
            event = await queue.get()
            if event is None:
                return
            yield event

    def get(self, review_id: str) -> ReviewResult | None:
        return self._results.get(review_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest apps/api/tests/test_jobs.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/adc_api/jobs.py apps/api/tests/test_jobs.py
git commit -m "feat(api): in-memory job manager + async event bus for SSE"
```

### Task 10: FastAPI app — routes + SSE + error handling

**Files:**
- Create: `apps/api/src/adc_api/main.py`
- Test: `apps/api/tests/test_api.py`

- [ ] **Step 1: Write the failing test `apps/api/tests/test_api.py`**

```python
import pytest
from httpx import ASGITransport, AsyncClient
from adc_api.main import create_app
from adc_api.providers import MockProvider

def _app():
    return create_app(provider_factory=lambda: MockProvider(seed=[{
        "category": "security", "severity": "high", "title": "SQLi",
        "description": "concat", "recommendation": "params", "start_line": 2, "end_line": 2,
    }]))

@pytest.mark.asyncio
async def test_post_review_then_get_result():
    transport = ASGITransport(app=_app())
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/api/reviews", json={"language": "python", "code": "x=1\n"})
        assert r.status_code == 202
        review_id = r.json()["reviewId"]
        # drain SSE so the job completes
        async with c.stream("GET", f"/api/reviews/{review_id}/events") as s:
            async for _ in s.aiter_lines():
                pass
        result = (await c.get(f"/api/reviews/{review_id}")).json()
        assert result["status"] == "done"
        assert any(f["category"] == "security" for f in result["findings"])

@pytest.mark.asyncio
async def test_post_review_rejects_unsupported_language():
    transport = ASGITransport(app=_app())
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/api/reviews", json={"language": "cobol", "code": "x"})
        assert r.status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest apps/api/tests/test_api.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `apps/api/src/adc_api/main.py`**

```python
from __future__ import annotations
import json
import os
from collections.abc import Callable
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
from adc_core.sanitization import SubmissionError
from adc_api.jobs import JobManager
from adc_api.providers import ModelProvider, build_provider
from adc_api.schemas import ReviewRequest

def create_app(provider_factory: Callable[[], ModelProvider] | None = None) -> FastAPI:
    app = FastAPI(title="AI Dev Companion API")
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )
    jm = JobManager(provider_factory=provider_factory or build_provider)
    max_bytes = int(os.getenv("ADC_MAX_CODE_BYTES", "100000"))
    max_lines = int(os.getenv("ADC_MAX_CODE_LINES", "2000"))

    @app.post("/api/reviews", status_code=202)
    async def create_review(req: ReviewRequest) -> dict:
        try:
            review_id = jm.create(
                language=req.language, code=req.code, max_bytes=max_bytes, max_lines=max_lines
            )
        except SubmissionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"reviewId": review_id, "status": "queued"}

    @app.get("/api/reviews/{review_id}/events")
    async def review_events(review_id: str) -> EventSourceResponse:
        if jm.get(review_id) is None:
            raise HTTPException(status_code=404, detail="review not found")

        async def gen():
            async for event in jm.stream(review_id):
                yield {"event": "progress", "data": json.dumps(event.model_dump(by_alias=True), default=str)}
            yield {"event": "complete", "data": "{}"}

        return EventSourceResponse(gen())

    @app.get("/api/reviews/{review_id}")
    async def get_review(review_id: str) -> dict:
        result = jm.get(review_id)
        if result is None:
            raise HTTPException(status_code=404, detail="review not found")
        return result.model_dump(by_alias=True, mode="json")

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app

app = create_app()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest apps/api/tests/test_api.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Run the whole Python suite + lint**

Run: `uv run pytest packages/core apps/api && uv run ruff check .`
Expected: all pass, ruff clean.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/adc_api/main.py apps/api/tests/test_api.py
git commit -m "feat(api): FastAPI routes (POST /reviews, SSE events, GET result) + error handling"
```

---

# PHASE C — Inc 1: Frontend (`apps/web`)

### Task 11: Vite React TS scaffold + config

**Files:**
- Create: `apps/web/package.json`, `apps/web/vite.config.ts`, `apps/web/tsconfig.json`, `apps/web/index.html`, `apps/web/src/main.tsx`, `apps/web/src/App.tsx`, `apps/web/.eslintrc.cjs`

- [ ] **Step 1: Create `apps/web/package.json`**

```json
{
  "name": "web",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview --port 5173",
    "lint": "eslint src --ext ts,tsx",
    "test": "vitest",
    "gen:types": "openapi-typescript http://localhost:8000/openapi.json -o src/api/types.gen.ts",
    "e2e": "playwright test"
  },
  "dependencies": {
    "@monaco-editor/react": "^4.6.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.26.0"
  },
  "devDependencies": {
    "@playwright/test": "^1.47.0",
    "@testing-library/jest-dom": "^6.5.0",
    "@testing-library/react": "^16.0.0",
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "@typescript-eslint/eslint-plugin": "^8.0.0",
    "@typescript-eslint/parser": "^8.0.0",
    "@vitejs/plugin-react": "^4.3.0",
    "eslint": "^8.57.0",
    "jsdom": "^25.0.0",
    "openapi-typescript": "^7.4.0",
    "typescript": "^5.5.0",
    "vite": "^5.4.0",
    "vitest": "^2.1.0"
  }
}
```

- [ ] **Step 2: Create `apps/web/vite.config.ts`**

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: { environment: "jsdom", globals: true, setupFiles: "./src/test-setup.ts" },
});
```

- [ ] **Step 3: Create `apps/web/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022", "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext", "moduleResolution": "bundler", "jsx": "react-jsx",
    "strict": true, "noUnusedLocals": true, "skipLibCheck": true,
    "types": ["vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src"]
}
```

- [ ] **Step 4: Create `apps/web/.eslintrc.cjs`**

```js
module.exports = {
  root: true,
  parser: "@typescript-eslint/parser",
  plugins: ["@typescript-eslint"],
  extends: ["eslint:recommended", "plugin:@typescript-eslint/recommended"],
  env: { browser: true, es2022: true },
  rules: { "@typescript-eslint/no-explicit-any": "off" },
};
```

- [ ] **Step 5: Create `apps/web/index.html`**

```html
<!doctype html>
<html lang="en">
  <head><meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1.0" /><title>AI Dev Companion</title></head>
  <body><div id="root"></div><script type="module" src="/src/main.tsx"></script></body>
</html>
```

- [ ] **Step 6: Create `apps/web/src/test-setup.ts`**

```ts
import "@testing-library/jest-dom";
```

- [ ] **Step 7: Create `apps/web/src/App.tsx`**

```tsx
import { Link, Route, Routes } from "react-router-dom";
import { Workspace } from "./components/Workspace";
import { HistoryPage } from "./pages/HistoryPage";
import { SettingsPage } from "./pages/SettingsPage";

export default function App() {
  return (
    <div className="app">
      <nav className="topnav">
        <span className="logo">⬡ AI Dev Companion</span>
        <Link to="/">New Review</Link>
        <Link to="/history">History</Link>
        <Link to="/settings">Settings</Link>
      </nav>
      <Routes>
        <Route path="/" element={<Workspace />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Routes>
    </div>
  );
}
```

- [ ] **Step 8: Create `apps/web/src/main.tsx`**

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter><App /></BrowserRouter>
  </React.StrictMode>
);
```

- [ ] **Step 9: Install + commit**

Run: `pnpm install`
Then:
```bash
git add apps/web pnpm-lock.yaml
git commit -m "chore(web): Vite + React + TS scaffold, routing, eslint"
```

### Task 12: API types + client (TDD)

**Files:**
- Create: `apps/web/src/api/types.ts`, `apps/web/src/api/client.ts`
- Test: `apps/web/src/api/client.test.ts`

- [ ] **Step 1: Create `apps/web/src/api/types.ts`** (hand-written contract; `pnpm gen:types` regenerates `types.gen.ts` from the live OpenAPI when the API is running)

```ts
export type Category = "security" | "performance" | "logic" | "style" | "syntax";
export type Severity = "info" | "low" | "medium" | "high" | "critical";
export type ReviewStatus =
  | "queued" | "validating" | "analyzing" | "enriching" | "finalizing" | "done" | "failed";

export interface Location { file?: string; startLine: number; endLine: number; startCol?: number; endCol?: number; }
export interface Source { type: "agent" | "tool"; name: string; confidence?: number; ruleId?: string; url?: string; }
export interface Finding {
  id: string; category: Category; severity: Severity; title: string;
  description: string; recommendation: string; location: Location; sources: Source[]; codeSnippet?: string;
}
export interface ReviewResult {
  id: string; status: ReviewStatus; language: string; model: string;
  findings: Finding[]; summary: string; createdAt: string; durationMs?: number; error?: string;
}
export interface ProgressEvent {
  reviewId: string; stage: ReviewStatus; percent?: number; subStatus: Record<string, string>; message?: string;
}
```

- [ ] **Step 2: Write the failing test `apps/web/src/api/client.test.ts`**

```ts
import { describe, expect, it, vi, beforeEach } from "vitest";
import { createReview, getReview } from "./client";

beforeEach(() => { vi.restoreAllMocks(); });

describe("api client", () => {
  it("createReview posts code and returns reviewId", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      JSON.stringify({ reviewId: "r1", status: "queued" }), { status: 202 })));
    const id = await createReview("python", "x=1");
    expect(id).toBe("r1");
  });

  it("getReview throws on 404", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("nope", { status: 404 })));
    await expect(getReview("missing")).rejects.toThrow();
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pnpm --filter web test -- --run`
Expected: FAIL — cannot resolve `./client`.

- [ ] **Step 4: Implement `apps/web/src/api/client.ts`**

```ts
import type { ReviewResult } from "./types";

const BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export async function createReview(language: string, code: string): Promise<string> {
  const res = await fetch(`${BASE}/api/reviews`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ language, code }),
  });
  if (!res.ok) throw new Error(`createReview failed: ${res.status} ${await res.text()}`);
  return (await res.json()).reviewId as string;
}

export async function getReview(id: string): Promise<ReviewResult> {
  const res = await fetch(`${BASE}/api/reviews/${id}`);
  if (!res.ok) throw new Error(`getReview failed: ${res.status}`);
  return (await res.json()) as ReviewResult;
}

export function eventsUrl(id: string): string {
  return `${BASE}/api/reviews/${id}/events`;
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pnpm --filter web test -- --run`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/api
git commit -m "feat(web): API types + client (createReview/getReview/eventsUrl)"
```

### Task 13: SSE hook (`useReviewStream`)

**Files:**
- Create: `apps/web/src/hooks/useReviewStream.ts`

- [ ] **Step 1: Implement `apps/web/src/hooks/useReviewStream.ts`** (no unit test — covered by Playwright e2e against the real SSE stream; jsdom lacks `EventSource`)

```ts
import { useCallback, useRef, useState } from "react";
import { createReview, eventsUrl, getReview } from "../api/client";
import type { ProgressEvent, ReviewResult } from "../api/types";

const TERMINAL = new Set(["done", "failed"]);

export function useReviewStream() {
  const [progress, setProgress] = useState<ProgressEvent | null>(null);
  const [result, setResult] = useState<ReviewResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const esRef = useRef<EventSource | null>(null);

  const start = useCallback(async (language: string, code: string) => {
    setProgress(null); setResult(null); setError(null); setRunning(true);
    try {
      const id = await createReview(language, code);
      const es = new EventSource(eventsUrl(id));
      esRef.current = es;
      es.addEventListener("progress", (e) => {
        const ev = JSON.parse((e as MessageEvent).data) as ProgressEvent;
        setProgress(ev);
      });
      es.addEventListener("complete", async () => {
        es.close();
        const r = await getReview(id);
        setResult(r); setRunning(false);
        if (r.status === "failed") setError(r.error ?? "review failed");
      });
      es.onerror = () => { es.close(); setRunning(false); setError("connection lost"); };
    } catch (err) {
      setRunning(false); setError(err instanceof Error ? err.message : "unknown error");
    }
  }, []);

  return { start, progress, result, running, error };
}
```

- [ ] **Step 2: Type-check + commit**

Run: `pnpm --filter web exec tsc -b --noEmit`
Expected: no type errors.
```bash
git add apps/web/src/hooks/useReviewStream.ts
git commit -m "feat(web): useReviewStream hook (SSE progress + final fetch)"
```

### Task 14: ProgressStepper + FindingCard components (TDD on FindingCard)

**Files:**
- Create: `apps/web/src/components/ProgressStepper.tsx`, `apps/web/src/components/FindingCard.tsx`
- Test: `apps/web/src/components/FindingCard.test.tsx`

- [ ] **Step 1: Write the failing test `apps/web/src/components/FindingCard.test.tsx`**

```tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { FindingCard } from "./FindingCard";
import type { Finding } from "../api/types";

const finding: Finding = {
  id: "f1", category: "security", severity: "high", title: "SQL injection",
  description: "String concat", recommendation: "Use params",
  location: { startLine: 2, endLine: 2 },
  sources: [{ type: "agent", name: "core-reviewer" }, { type: "tool", name: "semgrep", url: "http://x" }],
};

describe("FindingCard", () => {
  it("renders category, severity, location, recommendation and source citations", () => {
    render(<FindingCard finding={finding} onJump={() => {}} />);
    expect(screen.getByText(/SQL injection/)).toBeInTheDocument();
    expect(screen.getByText(/security/i)).toBeInTheDocument();
    expect(screen.getByText(/line 2/i)).toBeInTheDocument();
    expect(screen.getByText(/core-reviewer/)).toBeInTheDocument();
    expect(screen.getByText(/semgrep/)).toBeInTheDocument();
  });

  it("calls onJump with the start line when location clicked", () => {
    const onJump = vi.fn();
    render(<FindingCard finding={finding} onJump={onJump} />);
    fireEvent.click(screen.getByText(/line 2/i));
    expect(onJump).toHaveBeenCalledWith(2);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --filter web test -- --run FindingCard`
Expected: FAIL — cannot resolve `./FindingCard`.

- [ ] **Step 3: Implement `apps/web/src/components/FindingCard.tsx`**

```tsx
import type { Finding } from "../api/types";

const SEV_COLOR: Record<string, string> = {
  critical: "#b00020", high: "#d33", medium: "#da0", low: "#0a7", info: "#789",
};

export function FindingCard({ finding, onJump }: { finding: Finding; onJump: (line: number) => void }) {
  return (
    <div className="finding-card" style={{ borderLeft: `4px solid ${SEV_COLOR[finding.severity]}` }}>
      <div className="finding-head">
        <span className="badge">{finding.category}</span>
        <span className="sev">{finding.severity}</span>
        <button className="loc" onClick={() => onJump(finding.location.startLine)}>
          line {finding.location.startLine} ↗
        </button>
      </div>
      <h4>{finding.title}</h4>
      <p>{finding.description}</p>
      <p className="reco">→ {finding.recommendation}</p>
      <div className="sources">
        sources:{" "}
        {finding.sources.map((s) =>
          s.url ? (
            <a key={s.name} href={s.url} target="_blank" rel="noreferrer" className="chip">◆ {s.name}</a>
          ) : (
            <span key={s.name} className="chip">◆ {s.name}</span>
          )
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm --filter web test -- --run FindingCard`
Expected: PASS (2 passed).

- [ ] **Step 5: Implement `apps/web/src/components/ProgressStepper.tsx`**

```tsx
import type { ProgressEvent } from "../api/types";

const STAGES = ["validating", "analyzing", "enriching", "finalizing", "done"] as const;

export function ProgressStepper({ progress }: { progress: ProgressEvent | null }) {
  const current = progress?.stage ?? "queued";
  const idx = STAGES.indexOf(current as (typeof STAGES)[number]);
  return (
    <div className="stepper" role="status" aria-label="review progress">
      {STAGES.map((s, i) => (
        <span key={s} className={`step ${i <= idx ? "active" : ""}`}>
          {i < idx || current === "done" ? "✔" : i === idx ? "⟳" : "·"} {s}
        </span>
      ))}
      {progress && Object.keys(progress.subStatus).length > 0 && (
        <div className="substatus">
          {Object.entries(progress.subStatus).map(([k, v]) => (
            <span key={k} className="chip">{k}: {v}</span>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/components/FindingCard.tsx apps/web/src/components/FindingCard.test.tsx apps/web/src/components/ProgressStepper.tsx
git commit -m "feat(web): FindingCard (with citations + jump) and ProgressStepper"
```

### Task 15: Workspace (Monaco + dropdown + submit + click-to-highlight) + styles

**Files:**
- Create: `apps/web/src/components/Workspace.tsx`, `apps/web/src/styles.css`

- [ ] **Step 1: Implement `apps/web/src/components/Workspace.tsx`**

```tsx
import { useRef, useState } from "react";
import Editor, { type OnMount } from "@monaco-editor/react";
import { useReviewStream } from "../hooks/useReviewStream";
import { ProgressStepper } from "./ProgressStepper";
import { FindingCard } from "./FindingCard";

const LANGUAGES = ["python", "typescript", "java"];
const SAMPLE = `def get_user_data(user_id):\n    query = "SELECT * FROM users WHERE id = " + str(user_id)\n    cursor.execute(query)\n    return cursor.fetchall()\n`;

export function Workspace() {
  const [language, setLanguage] = useState("python");
  const [code, setCode] = useState(SAMPLE);
  const editorRef = useRef<Parameters<OnMount>[0] | null>(null);
  const { start, progress, result, running, error } = useReviewStream();

  const onMount: OnMount = (editor) => { editorRef.current = editor; };
  const jumpTo = (line: number) => {
    const ed = editorRef.current;
    if (!ed) return;
    ed.revealLineInCenter(line);
    ed.setPosition({ lineNumber: line, column: 1 });
    ed.focus();
  };

  return (
    <div className="workspace">
      <section className="pane editor-pane">
        <div className="controls">
          <select value={language} onChange={(e) => setLanguage(e.target.value)} aria-label="language">
            {LANGUAGES.map((l) => <option key={l} value={l}>{l}</option>)}
          </select>
        </div>
        <Editor height="60vh" language={language} value={code} onMount={onMount}
          onChange={(v) => setCode(v ?? "")} options={{ minimap: { enabled: false } }} />
        <button className="review-btn" disabled={running} onClick={() => start(language, code)}>
          {running ? "Reviewing…" : "Review Code ▶"}
        </button>
      </section>

      <section className="pane findings-pane">
        <ProgressStepper progress={progress} />
        {error && <div className="error" role="alert">{error}</div>}
        {result && (
          <>
            <div className="summary">{result.summary}</div>
            {result.findings.length === 0 && <p>No issues found 🎉</p>}
            {result.findings.map((f) => <FindingCard key={f.id} finding={f} onJump={jumpTo} />)}
          </>
        )}
      </section>
    </div>
  );
}
```

- [ ] **Step 2: Implement `apps/web/src/styles.css`** (responsive: panes stack below 900px)

```css
* { box-sizing: border-box; }
body { margin: 0; font-family: system-ui, sans-serif; }
.topnav { display: flex; gap: 16px; align-items: center; padding: 10px 16px; border-bottom: 1px solid #ddd; }
.topnav .logo { font-weight: 700; margin-right: auto; }
.workspace { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; padding: 12px; }
.pane { border: 1px solid #e3e3e3; border-radius: 8px; padding: 10px; min-height: 70vh; }
.controls { margin-bottom: 8px; }
.review-btn { margin-top: 8px; padding: 8px 16px; font-weight: 600; cursor: pointer; }
.stepper { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
.step { opacity: .5; } .step.active { opacity: 1; font-weight: 600; }
.substatus, .sources { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 6px; }
.chip { border: 1px solid #bbb; border-radius: 10px; padding: 1px 8px; font-size: 12px; text-decoration: none; }
.finding-card { padding: 8px 10px; margin: 8px 0; background: #fafafa; border-radius: 6px; }
.finding-head { display: flex; gap: 10px; align-items: center; font-size: 12px; }
.badge { text-transform: uppercase; font-weight: 700; }
.loc { background: none; border: none; color: #06c; cursor: pointer; padding: 0; margin-left: auto; }
.reco { color: #060; } .error { color: #b00020; }
@media (max-width: 900px) { .workspace { grid-template-columns: 1fr; } }
```

- [ ] **Step 3: Manually verify the workspace renders**

Run (in two terminals): `task up && task pull-model`, then `task api`, then `pnpm --filter web dev`.
Open http://localhost:5173 — confirm editor, dropdown, and Review button render. (Full review verified by e2e in Phase D.)

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/components/Workspace.tsx apps/web/src/styles.css
git commit -m "feat(web): Review Workspace (Monaco, language dropdown, submit, click-to-highlight)"
```

### Task 16: History + Settings pages

**Files:**
- Create: `apps/web/src/pages/HistoryPage.tsx`, `apps/web/src/pages/SettingsPage.tsx`
- Modify: `apps/api/src/adc_api/main.py` (add `GET /api/reviews` list), `apps/api/src/adc_api/jobs.py` (add `list_all`)

- [ ] **Step 1: Add `list_all` to `JobManager` in `apps/api/src/adc_api/jobs.py`** (insert after `get`)

```python
    def list_all(self) -> list[ReviewResult]:
        return list(self._results.values())
```

- [ ] **Step 2: Add list route to `apps/api/src/adc_api/main.py`** (insert before `get_review`)

```python
    @app.get("/api/reviews")
    async def list_reviews() -> list[dict]:
        return [r.model_dump(by_alias=True, mode="json") for r in jm.list_all()]
```

- [ ] **Step 3: Add list-route test to `apps/api/tests/test_api.py`**

```python
@pytest.mark.asyncio
async def test_list_reviews_returns_created_review():
    transport = ASGITransport(app=_app())
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        await c.post("/api/reviews", json={"language": "python", "code": "x=1\n"})
        listing = (await c.get("/api/reviews")).json()
        assert isinstance(listing, list) and len(listing) >= 1
```

- [ ] **Step 4: Run API tests**

Run: `uv run pytest apps/api/tests/test_api.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Implement `apps/web/src/pages/HistoryPage.tsx`**

```tsx
import { useEffect, useState } from "react";
import type { ReviewResult } from "../api/types";

const BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export function HistoryPage() {
  const [items, setItems] = useState<ReviewResult[]>([]);
  useEffect(() => {
    fetch(`${BASE}/api/reviews`).then((r) => r.json()).then(setItems).catch(() => setItems([]));
  }, []);
  return (
    <div style={{ padding: 16 }}>
      <h2>Review History</h2>
      <table>
        <thead><tr><th>Language</th><th>Status</th><th>Findings</th><th>Summary</th></tr></thead>
        <tbody>
          {items.map((r) => (
            <tr key={r.id}>
              <td>{r.language}</td><td>{r.status}</td><td>{r.findings.length}</td><td>{r.summary}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {items.length === 0 && <p>No reviews yet.</p>}
    </div>
  );
}
```

- [ ] **Step 6: Implement `apps/web/src/pages/SettingsPage.tsx`** (Inc 1: read-only display of active provider; editable BYO UI lands in Inc 2)

```tsx
const BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export function SettingsPage() {
  return (
    <div style={{ padding: 16 }}>
      <h2>Settings — Model Provider</h2>
      <p>The active model provider is configured via environment variables (see <code>.env.example</code>):</p>
      <ul>
        <li><code>ADC_MODEL_PROVIDER</code> — <code>ollama</code> (default) | <code>openai</code> | <code>anthropic</code></li>
        <li><code>ADC_MODEL</code> — e.g. <code>qwen2.5-coder:7b</code></li>
        <li>BYO: set <code>ADC_OPENAI_BASE_URL</code> + <code>ADC_OPENAI_API_KEY</code></li>
      </ul>
      <p>API base: <code>{BASE}</code>. An in-app editable form arrives in Inc 2 (model abstraction).</p>
    </div>
  );
}
```

- [ ] **Step 7: Commit**

```bash
git add apps/api/src/adc_api/jobs.py apps/api/src/adc_api/main.py apps/api/tests/test_api.py apps/web/src/pages
git commit -m "feat: review history list (API + page) + settings page"
```

---

# PHASE D — e2e, load test, deliverables

### Task 17: Playwright frontend-driven e2e

**Files:**
- Create: `apps/web/playwright.config.ts`, `apps/web/e2e/review.spec.ts`

- [ ] **Step 1: Create `apps/web/playwright.config.ts`** (uses a deterministic mock-provider API on port 8001)

```ts
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  use: { baseURL: "http://localhost:5173" },
  webServer: [
    {
      command: "ADC_MODEL_PROVIDER=mock uv run --project ../../apps/api uvicorn adc_api.main:app --port 8001",
      url: "http://localhost:8001/api/health",
      reuseExistingServer: !process.env.CI,
    },
    {
      command: "VITE_API_BASE_URL=http://localhost:8001 pnpm dev --port 5173",
      url: "http://localhost:5173",
      reuseExistingServer: !process.env.CI,
    },
  ],
});
```

- [ ] **Step 2: Add a `mock` branch to `build_provider()` in `apps/api/src/adc_api/providers.py`** (so e2e is deterministic; insert before the `ollama` branch)

```python
    if kind == "mock":
        return MockProvider(seed=[{
            "category": "security", "severity": "high", "title": "SQL injection vulnerability",
            "description": "User input concatenated into SQL string.",
            "recommendation": "Use parameterized queries.", "start_line": 2, "end_line": 2,
        }])
```

- [ ] **Step 3: Write the e2e test `apps/web/e2e/review.spec.ts`**

```ts
import { expect, test } from "@playwright/test";

test("submit code, watch progress, see categorized cited findings, jump to line", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("language").selectOption("python");
  await page.getByRole("button", { name: /Review Code/ }).click();

  // progress stepper advances to done
  await expect(page.getByRole("status", { name: /review progress/ })).toContainText("done", { timeout: 30000 });

  // categorized + cited finding appears
  await expect(page.getByText("SQL injection vulnerability")).toBeVisible();
  await expect(page.getByText(/security/i)).toBeVisible();
  await expect(page.getByText(/core-reviewer/)).toBeVisible();

  // click-to-jump does not error
  await page.getByRole("button", { name: /line 2/ }).click();
});
```

- [ ] **Step 4: Run the e2e**

Run: `pnpm --filter web exec playwright install --with-deps chromium && pnpm --filter web e2e`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/web/playwright.config.ts apps/web/e2e apps/api/src/adc_api/providers.py
git commit -m "test(e2e): Playwright review flow (progress, categorized cited findings, jump)"
```

### Task 18: k6 load test (smoke)

**Files:**
- Create: `infra/load/review-smoke.js`

- [ ] **Step 1: Create `infra/load/review-smoke.js`** (run against the mock-provider API to measure orchestration throughput, not model latency)

```js
import http from "k6/http";
import { check, sleep } from "k6";

export const options = { vus: 10, duration: "30s" };

export default function () {
  const res = http.post("http://localhost:8001/api/reviews",
    JSON.stringify({ language: "python", code: "x=1\n" }),
    { headers: { "Content-Type": "application/json" } });
  check(res, { "status 202": (r) => r.status === 202 });
  sleep(1);
}
```

- [ ] **Step 2: Document the run + commit** (k6 optional locally; documented for CI/ops)

Run (optional, requires k6): `k6 run infra/load/review-smoke.js`
```bash
git add infra/load/review-smoke.js
git commit -m "test(load): k6 smoke for /reviews orchestration throughput"
```

### Task 19: Sample test cases doc (assignment deliverable)

**Files:**
- Create: `docs/test-cases/inc1-samples.md`

- [ ] **Step 1: Create `docs/test-cases/inc1-samples.md`** (3 snippets + expected categorized output)

```markdown
# Inc 1 — Sample Test Cases & Expected Output

> Expected outputs describe the *categories and key findings* a capable model returns.
> Exact wording varies (especially with the local default model); tests assert on schema + categories, not phrasing.

## 1. Python — SQL injection (from the assignment)
\`\`\`python
def get_user_data(user_id):
    query = "SELECT * FROM users WHERE id = " + str(user_id)
    cursor.execute(query)
    return cursor.fetchall()
\`\`\`
**Expected:** Security/high — SQL injection (use parameterized queries) · Style/low — missing type hints & docstring · Performance/low — use `fetchone()` if a single row is expected.

## 2. TypeScript — unsafe any + missing await
\`\`\`typescript
async function load(id) {
  const res = fetch("/api/users/" + id);
  return res.json();
}
\`\`\`
**Expected:** Logic/high — missing `await` on `fetch` (`res` is a Promise) · Style/medium — parameter `id` untyped · Security/low — unsanitized id in URL.

## 3. Java — resource leak
\`\`\`java
public String read(String path) throws Exception {
  BufferedReader r = new BufferedReader(new FileReader(path));
  return r.readLine();
}
\`\`\`
**Expected:** Logic/high — reader never closed (use try-with-resources) · Style/low — broad `throws Exception` · Security/low — path not validated (path traversal).
```

- [ ] **Step 2: Commit**

```bash
git add docs/test-cases/inc1-samples.md
git commit -m "docs: Inc 1 sample test cases with expected categorized output"
```

### Task 20: README (assignment deliverable)

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace `README.md`**

```markdown
# AI Dev Companion

Intelligent, multi-step code review powered by GenAI. Submit code; get structured, categorized,
**source-cited** findings (security / performance / logic / style / syntax) with live progress.
Open-source and local-first — runs with **zero API keys** using a local model (Ollama).

> Built incrementally. This release is **Inc 0 + Inc 1** (foundation + the complete single-snippet
> review app). See the [design spec](docs/superpowers/specs/2026-05-31-ai-dev-companion-design.md)
> for the full roadmap (multi-agent, retrieval, git ingestion, SARIF scanners, auth, notifications, observability).

## Architecture
- **packages/core** — Findings schema, sanitization, tree-sitter syntax checks.
- **apps/api** — FastAPI job API: `POST /api/reviews` → SSE progress → `ReviewResult`. Pluggable `ModelProvider`.
- **apps/web** — React + Monaco workspace (side-by-side editor/findings) + History + Settings.

## Quick start
\`\`\`bash
cp .env.example .env
task up            # postgres + ollama
task pull-model    # pull qwen2.5-coder:7b (or set ADC_MODEL_PROVIDER=openai + a key)
task api           # http://localhost:8000
task web           # http://localhost:5173
\`\`\`

## API
- `POST /api/reviews` `{ "language": "python", "code": "..." }` → `202 { reviewId }`
- `GET /api/reviews/{id}/events` → SSE progress (`validating→analyzing→finalizing→done`)
- `GET /api/reviews/{id}` → final `ReviewResult` (findings with `sources[]`)
- `GET /api/reviews` → history list

## Testing
\`\`\`bash
task test:py                      # backend unit + API e2e (mock provider)
pnpm --filter web test -- --run   # frontend unit
pnpm --filter web e2e             # Playwright (spins up mock-provider API + web)
\`\`\`

## Design decisions & trade-offs
Local model default (zero keys, weaker output → tests assert on schema not wording); stable Findings
contract with `sources[]` so later scanners (Semgrep/SonarQube) merge as citations; async job + SSE so
long multi-agent runs (Inc 2+) show progress. Full rationale in the design spec.

## Bring your own model
Set `ADC_MODEL_PROVIDER=openai`, `ADC_OPENAI_BASE_URL`, `ADC_OPENAI_API_KEY`, `ADC_MODEL` (any
OpenAI-compatible endpoint, including hosted Qwen). Anthropic adapter lands in Inc 2.

## Known limitations
Single snippet only (multi-file = Inc 3); in-memory job store (Redis = Inc 2+); no auth yet (Inc 6).
```

- [ ] **Step 2: Final full verification**

Run: `uv run pytest packages/core apps/api && uv run ruff check . && pnpm --filter web test -- --run && pnpm --filter web exec tsc -b --noEmit`
Expected: all green.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: README (overview, setup, API, testing, design decisions, limitations)"
```

---

## Self-Review (completed)

**Spec coverage:** Assignment core (submission endpoint, multi-language Py/TS/Java, structured feedback, syntax validation, sanitization, error handling) → Tasks 4–10, 15. React/Monaco/dropdown/loading/categorized/responsive → Tasks 11–16. Multi-step analysis (syntax + categorized agent findings) → Tasks 6, 8. Spec §3 job+SSE → Tasks 9–10, 13. §3.3 Findings schema → Task 4. §5 UI (workspace/history/settings, side-by-side, responsive) → Tasks 15–16. §6 testing (unit/contract-via-types/API-e2e/Playwright) → Tasks 4–16 + 17. Inc 0 foundation/monorepo/CI/agent-docs/skills/credits → Tasks 1–3. Deliverables (README, samples, deps) → Tasks 19–20 + per-package manifests. Syntax-highlighting + export bonus: highlighting via Monaco (Task 15); export deferred (documented). Load test → Task 18.

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every command has expected output.

**Type consistency:** `Finding`/`Location`/`Source`/`ReviewResult` identical across backend (Task 4) and frontend `types.ts` (Task 12), camelCase on the wire. `RawFinding`/`ReviewOutput`/`ProgressEvent` (Task 7) used consistently in Tasks 8–10, 13–14. `ModelProvider.review(code, language) -> list[RawFinding]` and `build_provider()` consistent across Tasks 7–10, 17. `useReviewStream` shape consistent with Workspace (Tasks 13, 15).

