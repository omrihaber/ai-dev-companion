# Multi-File Review (Piece A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generalize review from a single snippet to a whole codebase with a two-tier strategy — scanners cover every file (breadth); the 6 LLM agents deep-review a bounded, prioritized subset (marked ∪ scanner-hit); skipped files are surfaced for a mark-and-re-run loop; History reloads past reviews.

**Architecture:** Every input (JSON `files[]`, server `.zip`, or legacy `{code,language}`) normalizes to a `Corpus` persisted on disk per review. Scanners run once over the corpus dir; agents run per-file via the existing LangGraph fan-out under a concurrency semaphore; a file-aware aggregator merges findings per file so multi-source citations still collapse to one card. Findings carry `location.file`; the result carries a coverage report.

**Tech Stack:** FastAPI, Pydantic v2 (camelCase), SQLAlchemy 2.0 async + Alembic, LangGraph, arq/Redis, Docker scanners (Semgrep/Bandit), React + TS + Vite + Monaco, JSZip (browser unzip), Playwright/vitest.

**Spec:** `docs/superpowers/specs/2026-06-01-multi-file-review-design.md`

**Conventions (read before starting):**
- Run backend tests with `uv run pytest packages/core apps/api -q` (hermetic; scanners disabled by `conftest.py`). Lint: `uv run ruff check .` (line-length 100).
- Models are camelCase over the wire via `_Camel` (alias_generator=to_camel, populate_by_name). Always `model_dump(by_alias=True, mode="json")` on output.
- Commit trailer on every commit: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Frontend: `pnpm --filter web test` (vitest), `pnpm --filter web exec tsc --noEmit`, `pnpm --filter web build`. Code references in any docs use markdown links.

---

## File Structure

**New backend files**
- `apps/api/src/adc_api/corpus.py` — ingestion (`ingest_files`, `ingest_zip`), `CorpusFile`, `IngestError`, and the disk-backed `CorpusStore` (write/read/list/copy with a path-traversal guard).
- `apps/api/src/adc_api/selection.py` — `select_agent_files(...)` → (agent paths, per-file coverage).
- `apps/api/migrations/versions/0002_corpus_columns.py` — add `coverage` + `parent_review_id` columns.
- Tests: `apps/api/tests/test_corpus.py`, `test_selection.py`.

**Modified backend files**
- `packages/core/src/adc_core/models.py` — `FileCoverage`, `Coverage`, `ReviewResult.coverage`/`parent_review_id`.
- `apps/api/src/adc_api/scanners/sarif.py` — populate `location.file` from the SARIF artifact uri.
- `apps/api/src/adc_api/scanners/__init__.py`, `semgrep.py`, `bandit.py` — `Scanner.scan_path(work_dir)` (scan a directory, not a snippet).
- `apps/api/src/adc_api/agents.py` — `analyze(code, language, file=None)` sets `location.file`.
- `apps/api/src/adc_api/graph.py` — `ReviewState.file`; pass file into specialist nodes.
- `apps/api/src/adc_api/aggregator.py` — merge only within the same `location.file`.
- `apps/api/src/adc_api/review_service.py` — corpus pipeline (scanners-once + per-file agent fan-out + final aggregate + coverage).
- `apps/api/src/adc_api/schemas.py` — `FileInput`; `ReviewRequest.files`/`marked`.
- `apps/api/src/adc_api/worker.py`, `queue.py` — corpus-based job signature (`review_id`, `marked`).
- `apps/api/src/adc_api/repository.py`, `db/models.py` — persist coverage + parent id; `fileCount` in list.
- `apps/api/src/adc_api/settings.py` — new caps/concurrency/ignore/work-root config.
- `apps/api/src/adc_api/main.py` — `files[]`/`zip`/`rerun`/`file?path=` endpoints; wire `CorpusStore`.

**Frontend**
- `apps/web/src/api/types.ts`, `client.ts` — new shapes + calls.
- `apps/web/src/components/FileTree.tsx` (new) — tri-state tree with select-all / dir-toggle / badges / skipped tags.
- `apps/web/src/components/Workspace.tsx` — three-pane layout, multi-file, coverage banner, Re-run.
- `apps/web/src/hooks/useReviewStream.ts` — submit files/marked; expose loading a past review.
- `apps/web/src/pages/HistoryPage.tsx`, `App.tsx` — clickable history → review view.
- `apps/web/e2e/multifile.spec.ts` (new) — Playwright flow.

---

## Task 1: Core models — coverage + parent id

**Files:**
- Modify: `packages/core/src/adc_core/models.py`
- Test: `packages/core/tests/test_models.py`

- [ ] **Step 1: Write the failing test**

Append to `packages/core/tests/test_models.py`:

```python
def test_review_result_carries_coverage_and_parent_camelcase():
    from adc_core.models import Coverage, FileCoverage, ReviewResult

    cov = Coverage(
        files_total=3,
        files_agent_reviewed=1,
        files=[
            FileCoverage(path="a.py", agent_reviewed=True, reason="marked"),
            FileCoverage(path="b.py", agent_reviewed=False, reason="not-flagged"),
        ],
    )
    r = ReviewResult(id="x", language="python", model="m", coverage=cov, parent_review_id="p")
    dumped = r.model_dump(by_alias=True)
    assert dumped["coverage"]["filesTotal"] == 3
    assert dumped["coverage"]["files"][0]["agentReviewed"] is True
    assert dumped["coverage"]["files"][0]["reason"] == "marked"
    assert dumped["parentReviewId"] == "p"
    # default: no coverage / parent
    assert ReviewResult(id="y", language="python", model="m").coverage is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/core/tests/test_models.py::test_review_result_carries_coverage_and_parent_camelcase -v`
Expected: FAIL (`ImportError: cannot import name 'Coverage'`).

- [ ] **Step 3: Implement**

In `packages/core/src/adc_core/models.py`, add after the `Finding` class and before `ReviewResult`:

```python
CoverageReason = Literal["marked", "scanner-hit", "fallback", "not-flagged", "over-cap"]

class FileCoverage(_Camel):
    path: str
    agent_reviewed: bool
    reason: CoverageReason

class Coverage(_Camel):
    files_total: int = 0
    files_agent_reviewed: int = 0
    files: list[FileCoverage] = Field(default_factory=list)
```

Add two fields to `ReviewResult`:

```python
    coverage: Coverage | None = None
    parent_review_id: str | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/core/tests/test_models.py -q`
Expected: PASS (all existing + new).

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/adc_core/models.py packages/core/tests/test_models.py
git commit -m "feat(core): add Coverage/FileCoverage + ReviewResult.coverage/parentReviewId

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Settings — caps, concurrency, ignore globs, work root

**Files:**
- Modify: `apps/api/src/adc_api/settings.py`
- Test: `apps/api/tests/test_settings.py`

- [ ] **Step 1: Write the failing test**

Append to `apps/api/tests/test_settings.py`:

```python
def test_multifile_settings_defaults():
    from adc_api.settings import Settings

    s = Settings()
    assert s.agent_file_cap == 25
    assert s.agent_file_ceiling == 150
    assert s.file_concurrency == 4
    assert s.max_files == 2000
    assert s.max_total_bytes == 50_000_000
    assert s.max_file_bytes == 512_000
    assert "node_modules" in s.ignore_globs
    assert s.work_root  # non-empty default path
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest apps/api/tests/test_settings.py::test_multifile_settings_defaults -v`
Expected: FAIL (`AttributeError: ... 'agent_file_cap'`).

- [ ] **Step 3: Implement**

In `apps/api/src/adc_api/settings.py`, add fields to `Settings` (after `max_code_lines`):

```python
    # Multi-file review
    agent_file_cap: int = 25          # default size of the agent deep-review set
    agent_file_ceiling: int = 150     # hard max even when files are explicitly marked
    file_concurrency: int = 4         # files reviewed by agents in parallel
    max_files: int = 2000             # ingestion cap (file count)
    max_total_bytes: int = 50_000_000 # ingestion cap (total uncompressed bytes)
    max_file_bytes: int = 512_000     # ingestion cap (per file)
    # Comma list of path globs dropped before review (dependencies, VCS, build output, binaries).
    ignore_globs: str = (
        ".git/*,node_modules/*,dist/*,build/*,vendor/*,__pycache__/*,"
        "*.lock,*.min.js,*.map,*.png,*.jpg,*.jpeg,*.gif,*.pdf,*.zip,*.so,*.dll,*.exe,*.bin"
    )
    work_root: str = ".adc_work"      # base dir for per-review corpus work dirs
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest apps/api/tests/test_settings.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/adc_api/settings.py apps/api/tests/test_settings.py
git commit -m "feat(api): multi-file settings (caps, concurrency, ignore globs, work root)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Ingestion — `ingest_files` / `ingest_zip` / `CorpusFile` / `IngestError`

**Files:**
- Create: `apps/api/src/adc_api/corpus.py`
- Test: `apps/api/tests/test_corpus.py`

Normalize any transport to a list of `CorpusFile`, applying the ignore denylist, caps, language inference, and (for zip) path-traversal + zip-bomb defenses.

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/test_corpus.py`:

```python
import io
import zipfile

import pytest
from adc_api.corpus import CorpusFile, IngestError, ingest_files, ingest_zip


def test_ingest_files_infers_language_and_drops_ignored():
    files = [
        {"path": "app/main.py", "content": "x = 1\n"},
        {"path": "web/app.ts", "content": "const x = 1\n"},
        {"path": "node_modules/dep/index.js", "content": "junk"},
        {"path": "poetry.lock", "content": "lock"},
    ]
    out = ingest_files(files)
    paths = {f.path: f for f in out}
    assert set(paths) == {"app/main.py", "web/app.ts"}        # ignored dropped
    assert paths["app/main.py"].language == "python"
    assert paths["web/app.ts"].language == "typescript"


def test_ingest_files_rejects_over_file_count():
    files = [{"path": f"f{i}.py", "content": "x=1"} for i in range(3)]
    with pytest.raises(IngestError):
        ingest_files(files, max_files=2)


def test_ingest_files_rejects_over_total_bytes():
    files = [{"path": "big.py", "content": "x" * 100}]
    with pytest.raises(IngestError):
        ingest_files(files, max_total_bytes=10)


def test_ingest_files_skips_non_utf8_binary():
    files = [{"path": "a.py", "content": "ok"}, {"path": "weird.py", "content": "\udce4bad"}]
    out = ingest_files(files)
    assert [f.path for f in out] == ["a.py"]


def _zip_bytes(members: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_ingest_zip_normalizes_like_files():
    data = _zip_bytes({"src/a.py": "x=1\n", "node_modules/b.js": "junk"})
    out = ingest_zip(data)
    assert [f.path for f in out] == ["src/a.py"]


def test_ingest_zip_rejects_path_traversal():
    data = _zip_bytes({"../escape.py": "x=1"})
    with pytest.raises(IngestError):
        ingest_zip(data)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest apps/api/tests/test_corpus.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'adc_api.corpus'`).

- [ ] **Step 3: Implement**

Create `apps/api/src/adc_api/corpus.py`:

```python
from __future__ import annotations

import fnmatch
import io
import zipfile
from dataclasses import dataclass

from adc_api.settings import settings

# extension -> language (kept in sync with the syntax/scanner language map)
_LANG_BY_EXT = {
    "py": "python", "ts": "typescript", "tsx": "typescript",
    "js": "javascript", "jsx": "javascript", "java": "java",
    "go": "go", "rb": "ruby", "rs": "rust", "c": "c", "h": "c",
    "cpp": "cpp", "cc": "cpp", "cs": "csharp", "php": "php", "kt": "kotlin",
}


class IngestError(ValueError):
    """Raised when a submission violates an ingestion cap or safety rule."""


@dataclass(frozen=True)
class CorpusFile:
    path: str
    content: str
    language: str | None


def _language_for(path: str) -> str | None:
    return _LANG_BY_EXT.get(path.rsplit(".", 1)[-1].lower()) if "." in path else None


def _ignored(path: str, globs: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, g) or fnmatch.fnmatch(path.split("/")[-1], g)
               for g in globs)


def _normalize(
    raw: list[tuple[str, str]],  # (path, content)
    *, max_files: int, max_total_bytes: int, max_file_bytes: int, ignore_globs: list[str],
) -> list[CorpusFile]:
    out: list[CorpusFile] = []
    total = 0
    for path, content in raw:
        path = path.lstrip("./").replace("\\", "/")
        if not path or _ignored(path, ignore_globs):
            continue
        size = len(content.encode("utf-8", "surrogatepass"))
        if size > max_file_bytes:
            continue  # oversized single file: skip, don't sink the whole batch
        # drop non-UTF-8 / binary content (surrogate escapes mean it wasn't clean text)
        try:
            content.encode("utf-8")
        except UnicodeEncodeError:
            continue
        total += size
        if total > max_total_bytes:
            raise IngestError(
                f"submission exceeds {max_total_bytes} bytes (total source too large)"
            )
        out.append(CorpusFile(path=path, content=content, language=_language_for(path)))
    if len(out) > max_files:
        raise IngestError(f"submission has {len(out)} files; max is {max_files}")
    if not out:
        raise IngestError("no reviewable files after applying the ignore rules")
    return out


def _caps(max_files, max_total_bytes, max_file_bytes, ignore_globs):
    return dict(
        max_files=max_files if max_files is not None else settings.max_files,
        max_total_bytes=max_total_bytes if max_total_bytes is not None else settings.max_total_bytes,
        max_file_bytes=max_file_bytes if max_file_bytes is not None else settings.max_file_bytes,
        ignore_globs=[g.strip() for g in (ignore_globs or settings.ignore_globs).split(",") if g.strip()],
    )


def ingest_files(
    files: list[dict], *, max_files=None, max_total_bytes=None, max_file_bytes=None,
    ignore_globs=None,
) -> list[CorpusFile]:
    raw = [(f["path"], f.get("content", "")) for f in files]
    return _normalize(raw, **_caps(max_files, max_total_bytes, max_file_bytes, ignore_globs))


def ingest_zip(
    data: bytes, *, max_files=None, max_total_bytes=None, max_file_bytes=None, ignore_globs=None,
) -> list[CorpusFile]:
    raw: list[tuple[str, str]] = []
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise IngestError("not a valid zip archive") from exc
    with zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename
            if name.startswith("/") or ".." in name.replace("\\", "/").split("/"):
                raise IngestError(f"zip entry escapes the archive root: {name!r}")
            # zip-bomb guard: trust the declared uncompressed size before reading
            if info.file_size > (max_file_bytes or settings.max_file_bytes) * 8:
                raise IngestError(f"zip entry too large: {name!r}")
            try:
                content = zf.read(info).decode("utf-8")
            except (UnicodeDecodeError, OSError):
                continue  # binary / unreadable: skip
            raw.append((name, content))
    return _normalize(raw, **_caps(max_files, max_total_bytes, max_file_bytes, ignore_globs))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest apps/api/tests/test_corpus.py -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/adc_api/corpus.py apps/api/tests/test_corpus.py
git commit -m "feat(api): corpus ingestion (files[]/zip) with ignore globs, caps, traversal guard

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: `CorpusStore` — persist + read corpus on disk

**Files:**
- Modify: `apps/api/src/adc_api/corpus.py`
- Test: `apps/api/tests/test_corpus.py`

Per-review work dir on disk. Powers scanners, the file endpoint, History, and re-runs.

- [ ] **Step 1: Write the failing test**

Append to `apps/api/tests/test_corpus.py`:

```python
def test_corpus_store_write_list_read_roundtrip(tmp_path):
    from adc_api.corpus import CorpusStore

    store = CorpusStore(str(tmp_path))
    files = ingest_files([
        {"path": "app/main.py", "content": "print(1)\n"},
        {"path": "app/util.py", "content": "x = 2\n"},
    ])
    work = store.write("rev1", files)
    assert (work / "app/main.py").read_text() == "print(1)\n"

    listed = {f.path: f for f in store.list_files("rev1")}
    assert set(listed) == {"app/main.py", "app/util.py"}
    assert listed["app/main.py"].language == "python"
    assert store.read_file("rev1", "app/util.py") == "x = 2\n"


def test_corpus_store_read_file_blocks_traversal(tmp_path):
    from adc_api.corpus import CorpusStore

    store = CorpusStore(str(tmp_path))
    store.write("rev1", ingest_files([{"path": "a.py", "content": "x=1"}]))
    with pytest.raises(IngestError):
        store.read_file("rev1", "../../etc/passwd")


def test_corpus_store_copy_for_rerun(tmp_path):
    from adc_api.corpus import CorpusStore

    store = CorpusStore(str(tmp_path))
    store.write("rev1", ingest_files([{"path": "a.py", "content": "x=1"}]))
    store.copy("rev1", "rev2")
    assert store.read_file("rev2", "a.py") == "x=1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest apps/api/tests/test_corpus.py -k store -q`
Expected: FAIL (`ImportError: cannot import name 'CorpusStore'`).

- [ ] **Step 3: Implement**

Append to `apps/api/src/adc_api/corpus.py`:

```python
import shutil
from pathlib import Path


class CorpusStore:
    """Disk-backed per-review corpus. Files live under <root>/<review_id>/<path>."""

    def __init__(self, root: str) -> None:
        self._root = Path(root)

    def path(self, review_id: str) -> Path:
        return self._root / review_id

    def write(self, review_id: str, files: list[CorpusFile]) -> Path:
        base = self.path(review_id)
        base.mkdir(parents=True, exist_ok=True)
        for f in files:
            dest = (base / f.path).resolve()
            if base.resolve() not in dest.parents and dest != base.resolve():
                raise IngestError(f"path escapes work dir: {f.path!r}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(f.content, encoding="utf-8")
        return base

    def list_files(self, review_id: str) -> list[CorpusFile]:
        base = self.path(review_id).resolve()
        out: list[CorpusFile] = []
        if not base.exists():
            return out
        for p in sorted(base.rglob("*")):
            if p.is_file():
                rel = p.relative_to(base).as_posix()
                out.append(CorpusFile(rel, p.read_text("utf-8", "replace"), _language_for(rel)))
        return out

    def read_file(self, review_id: str, rel_path: str) -> str:
        base = self.path(review_id).resolve()
        target = (base / rel_path).resolve()
        if base != target and base not in target.parents:
            raise IngestError(f"path escapes work dir: {rel_path!r}")
        if not target.is_file():
            raise IngestError(f"file not found: {rel_path!r}")
        return target.read_text("utf-8", "replace")

    def copy(self, src_review_id: str, dst_review_id: str) -> Path:
        dst = self.path(dst_review_id)
        shutil.copytree(self.path(src_review_id), dst, dirs_exist_ok=True)
        return dst
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest apps/api/tests/test_corpus.py -q`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/adc_api/corpus.py apps/api/tests/test_corpus.py
git commit -m "feat(api): CorpusStore — disk work dir (write/list/read-guarded/copy)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: SARIF → `location.file` + Scanner directory API

**Files:**
- Modify: `apps/api/src/adc_api/scanners/sarif.py`
- Modify: `apps/api/src/adc_api/scanners/__init__.py`, `semgrep.py`, `bandit.py`
- Test: `apps/api/tests/test_sarif.py`, `apps/api/tests/test_scanners.py`

Scanners now scan a whole directory (the corpus work dir) and findings carry their file path.

- [ ] **Step 1: Write the failing tests**

In `apps/api/tests/test_sarif.py`, add `"uri"` assertions. Replace the two existing mapping tests' tail asserts by appending these new tests:

```python
def test_maps_artifact_uri_to_location_file():
    findings = sarif_to_findings(SEMGREP_SARIF, "semgrep")
    assert findings[0].location.file == "snippet.py"


def test_strips_leading_dot_slash_from_file():
    sarif = {
        "runs": [{
            "tool": {"driver": {"rules": []}},
            "results": [{
                "ruleId": "x", "level": "error", "message": {"text": "bad"},
                "locations": [{"physicalLocation": {
                    "artifactLocation": {"uri": "./app/db.py"},
                    "region": {"startLine": 3, "endLine": 3},
                }}],
            }],
        }]
    }
    assert sarif_to_findings(sarif, "bandit")[0].location.file == "app/db.py"
```

In `apps/api/tests/test_scanners.py`, add (a FakeScanner-style dir test — read the existing file first to match its imports/helpers; this test asserts the new `scan_path` contract using a monkeypatched runner):

```python
import pytest
from adc_api.scanners.semgrep import SemgrepScanner


@pytest.mark.asyncio
async def test_semgrep_scan_path_returns_findings_with_files(monkeypatch, tmp_path):
    sarif = {
        "runs": [{
            "tool": {"driver": {"rules": []}},
            "results": [{
                "ruleId": "python.sqli", "level": "error",
                "message": {"text": "SQL injection"},
                "locations": [{"physicalLocation": {
                    "artifactLocation": {"uri": "app/auth.py"},
                    "region": {"startLine": 2, "endLine": 2},
                }}],
            }],
        }]
    }
    import json as _json
    monkeypatch.setattr("adc_api.scanners.semgrep.docker_available", lambda: _true())
    monkeypatch.setattr(
        "adc_api.scanners.semgrep.run_in_container",
        lambda **kw: _ret(_json.dumps(sarif)),
    )
    out = await SemgrepScanner().scan_path(str(tmp_path))
    assert out and out[0].location.file == "app/auth.py"


async def _true():
    return True


async def _ret(v):
    return v
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest apps/api/tests/test_sarif.py apps/api/tests/test_scanners.py -q`
Expected: FAIL (`location.file` is `None`; `SemgrepScanner` has no `scan_path`).

- [ ] **Step 3: Implement**

In `apps/api/src/adc_api/scanners/sarif.py`, change `_region` to also yield the uri, and set `file`:

Replace `_region`:

```python
def _physical(result: dict) -> tuple[str | None, dict] | None:
    for loc in result.get("locations", []):
        phys = loc.get("physicalLocation", {})
        region = phys.get("region")
        if region and region.get("startLine"):
            uri = (phys.get("artifactLocation", {}).get("uri") or "").lstrip("./") or None
            return uri, region
    return None
```

In `sarif_to_findings`, replace the region lookup + Location construction:

```python
        physical = _physical(result)
        if physical is None:
            continue
        file_path, region = physical
```

and in the `Location(...)` add `file=file_path,` as the first arg.

In `apps/api/src/adc_api/scanners/__init__.py`, change the protocol:

```python
class Scanner(Protocol):
    name: str
    languages: set[str]

    async def scan_path(self, work_dir: str) -> list[Finding]: ...
```

In `apps/api/src/adc_api/scanners/semgrep.py`, replace `scan` with `scan_path` (drop the temp-file write — the dir already holds the corpus):

```python
    async def scan_path(self, work_dir: str) -> list[Finding]:
        if not await docker_available():
            return []
        try:
            out = await run_in_container(
                image=self._image,
                cmd=["semgrep", "scan", "--sarif", "--quiet", "--config", "auto", "/src"],
                host_dir=work_dir, timeout=self._timeout, network="bridge",
            )
        except Exception:  # noqa: BLE001 — any scan failure degrades to no findings
            return []
        try:
            return sarif_to_findings(json.loads(out), self.name)
        except (ValueError, KeyError):
            return []
```

(Remove the now-unused `tempfile`, `Path`, `_EXT` imports/constants.)

In `apps/api/src/adc_api/scanners/bandit.py`, replace `scan` with `scan_path`:

```python
    async def scan_path(self, work_dir: str) -> list[Finding]:
        if not await docker_available():
            return []
        try:
            out = await run_in_container(
                image=self._image,
                cmd=["bandit", "-r", "/src", "-f", "sarif"],
                host_dir=work_dir, timeout=self._timeout,
            )
        except Exception:  # noqa: BLE001
            return []
        try:
            return sarif_to_findings(json.loads(out), self.name)
        except (ValueError, KeyError):
            return []
```

(Remove the now-unused `tempfile`, `Path` imports.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest apps/api/tests/test_sarif.py apps/api/tests/test_scanners.py -q`
Expected: PASS. (If `test_scanners.py` had tests calling the old `scan(code, language)`, update them to `scan_path` + the monkeypatched runner pattern above — read the file and adapt; do not leave references to the removed method.)

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/adc_api/scanners apps/api/tests/test_sarif.py apps/api/tests/test_scanners.py
git commit -m "feat(api): scanners scan a directory (scan_path); SARIF maps artifact uri -> location.file

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Agent file attribution + graph `file` channel

**Files:**
- Modify: `apps/api/src/adc_api/agents.py`, `apps/api/src/adc_api/graph.py`
- Test: `apps/api/tests/test_agents.py`, `apps/api/tests/test_graph.py`

- [ ] **Step 1: Write the failing test**

Append to `apps/api/tests/test_agents.py` (read the file first for its `MockProvider` import pattern; this matches the existing style):

```python
import pytest
from adc_api.agents import build_agents
from adc_api.providers import MockProvider


@pytest.mark.asyncio
async def test_agent_sets_location_file_when_given():
    agents = build_agents(provider=MockProvider(seed=[{
        "category": "security", "severity": "high", "title": "SQLi",
        "description": "d", "recommendation": "r", "start_line": 1, "end_line": 1,
    }]))
    findings = await agents[0].analyze("x = 1\n", "python", file="app/auth.py")
    assert findings[0].location.file == "app/auth.py"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest apps/api/tests/test_agents.py::test_agent_sets_location_file_when_given -v`
Expected: FAIL (`analyze() got an unexpected keyword argument 'file'`).

- [ ] **Step 3: Implement**

In `apps/api/src/adc_api/agents.py`, change `analyze`'s signature + the `Location`:

```python
    async def analyze(
        self, code: str, language: str, file: str | None = None
    ) -> list[Finding]:
```

and in the `Location(...)`:

```python
                location=Location(file=file, start_line=raw.start_line, end_line=raw.end_line),
```

In `apps/api/src/adc_api/graph.py`, add `file` to `ReviewState` and pass it through:

```python
class ReviewState(TypedDict):
    code: str
    language: str
    file: str | None
    findings: Annotated[list[Finding], operator.add]
    failures: Annotated[list[str], operator.add]
    result: list[Finding]
```

and in `_specialist_node`:

```python
            found = await agent.analyze(state["code"], state["language"], state.get("file"))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest apps/api/tests/test_agents.py apps/api/tests/test_graph.py -q`
Expected: PASS. (If `test_graph.py` builds initial state without `file`, `state.get("file")` tolerates its absence — confirm those tests still pass; add `"file": None` to any initial state dict only if a test asserts on it.)

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/adc_api/agents.py apps/api/src/adc_api/graph.py apps/api/tests/test_agents.py
git commit -m "feat(api): agents attribute findings to a file; graph carries the file channel

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: File-aware aggregation

**Files:**
- Modify: `apps/api/src/adc_api/aggregator.py`
- Test: `apps/api/tests/test_aggregator.py`

- [ ] **Step 1: Write the failing test**

Append to `apps/api/tests/test_aggregator.py` (read the file first for its `Finding`/`Location`/`Source` construction helpers; match them):

```python
def test_same_issue_in_two_files_does_not_merge():
    from adc_core.models import Finding, Location, Source
    from adc_api.aggregator import aggregate

    def mk(file):
        return Finding(
            id=file, category="security", severity="high", title="SQL injection",
            description="d", recommendation="r",
            location=Location(file=file, start_line=2, end_line=2),
            sources=[Source(type="agent", name="security-agent")],
        )

    out = aggregate([mk("auth.py"), mk("db.py")])
    assert len(out) == 2
    assert {f.location.file for f in out} == {"auth.py", "db.py"}


def test_same_file_two_sources_merge_into_one_card():
    from adc_core.models import Finding, Location, Source
    from adc_api.aggregator import aggregate

    agent = Finding(
        id="a", category="security", severity="high", title="SQL injection",
        description="d", recommendation="r",
        location=Location(file="auth.py", start_line=2, end_line=2),
        sources=[Source(type="agent", name="security-agent")],
    )
    tool = Finding(
        id="b", category="security", severity="high", title="SQL injection vector",
        description="d", recommendation="r",
        location=Location(file="auth.py", start_line=2, end_line=2),
        sources=[Source(type="tool", name="bandit")],
    )
    out = aggregate([agent, tool])
    assert len(out) == 1
    assert {s.name for s in out[0].sources} == {"security-agent", "bandit"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest apps/api/tests/test_aggregator.py::test_same_issue_in_two_files_does_not_merge -v`
Expected: FAIL (currently merges across files — returns 1, expected 2).

- [ ] **Step 3: Implement**

In `apps/api/src/adc_api/aggregator.py`, make `_mergeable` file-aware:

```python
def _mergeable(head: Finding, f: Finding) -> bool:
    # `syntax` findings (deterministic parse errors) never merge with agent findings.
    if head.category == "syntax" or f.category == "syntax":
        return False
    if head.location.file != f.location.file:   # findings only merge within the same file
        return False
    return _overlap(head.location, f.location) and _similar_title(head.title, f.title)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest apps/api/tests/test_aggregator.py -q`
Expected: PASS (existing single-file tests still pass — they use `file=None` on both sides, which compares equal).

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/adc_api/aggregator.py apps/api/tests/test_aggregator.py
git commit -m "feat(api): aggregate findings per file (no cross-file merging)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: Selection — build the agent deep-review set + coverage

**Files:**
- Create: `apps/api/src/adc_api/selection.py`
- Test: `apps/api/tests/test_selection.py`

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/test_selection.py`:

```python
import pytest
from adc_api.corpus import CorpusFile
from adc_api.selection import SelectionError, select_agent_files
from adc_core.models import Finding, Location, Source


def _files(*paths):
    return [CorpusFile(p, "x=1\n", "python") for p in paths]


def _hit(file, severity="high"):
    return Finding(
        id=file, category="security", severity=severity, title="t", description="d",
        recommendation="r", location=Location(file=file, start_line=1, end_line=1),
        sources=[Source(type="tool", name="bandit")],
    )


def test_marked_and_scanner_hits_are_reviewed():
    files = _files("a.py", "b.py", "c.py")
    paths, coverage = select_agent_files(
        files, marked={"a.py"}, scanner_findings=[_hit("b.py")], cap=25, ceiling=150,
    )
    assert set(paths) == {"a.py", "b.py"}
    by = {c.path: c for c in coverage}
    assert by["a.py"].reason == "marked" and by["a.py"].agent_reviewed
    assert by["b.py"].reason == "scanner-hit" and by["b.py"].agent_reviewed
    assert by["c.py"].reason == "not-flagged" and not by["c.py"].agent_reviewed


def test_cap_limits_scanner_hits_by_severity_marks_always_kept():
    files = _files("m.py", "lo.py", "hi.py")
    paths, coverage = select_agent_files(
        files, marked={"m.py"},
        scanner_findings=[_hit("lo.py", "low"), _hit("hi.py", "critical")],
        cap=2, ceiling=150,
    )
    # cap=2: the mark is always kept; among scanner hits the critical wins the last slot
    assert set(paths) == {"m.py", "hi.py"}
    by = {c.path: c for c in coverage}
    assert by["lo.py"].reason == "over-cap" and not by["lo.py"].agent_reviewed


def test_marks_override_cap_up_to_ceiling():
    files = _files("a.py", "b.py", "c.py")
    paths, _ = select_agent_files(
        files, marked={"a.py", "b.py", "c.py"}, scanner_findings=[], cap=1, ceiling=150,
    )
    assert set(paths) == {"a.py", "b.py", "c.py"}  # marks beat the cap


def test_marks_over_ceiling_rejected():
    files = _files("a.py", "b.py", "c.py")
    with pytest.raises(SelectionError):
        select_agent_files(files, marked={"a.py", "b.py", "c.py"}, scanner_findings=[],
                           cap=25, ceiling=2)


def test_empty_selection_falls_back_to_first_n_source_files():
    files = _files("a.py", "b.py", "c.py")
    paths, coverage = select_agent_files(
        files, marked=set(), scanner_findings=[], cap=2, ceiling=150,
    )
    assert len(paths) == 2
    assert all(c.reason == "fallback" for c in coverage if c.agent_reviewed)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest apps/api/tests/test_selection.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'adc_api.selection'`).

- [ ] **Step 3: Implement**

Create `apps/api/src/adc_api/selection.py`:

```python
from __future__ import annotations

from adc_api.corpus import CorpusFile
from adc_core.models import FileCoverage, Finding

_SEV_RANK = {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1}


class SelectionError(ValueError):
    """Raised when the marked set exceeds the hard ceiling."""


def _max_sev_by_file(scanner_findings: list[Finding]) -> dict[str, int]:
    out: dict[str, int] = {}
    for f in scanner_findings:
        path = f.location.file
        if path is None:
            continue
        out[path] = max(out.get(path, 0), _SEV_RANK.get(f.severity, 0))
    return out


def select_agent_files(
    files: list[CorpusFile], *, marked: set[str], scanner_findings: list[Finding],
    cap: int, ceiling: int,
) -> tuple[list[str], list[FileCoverage]]:
    """Return (agent_set_paths, per-file coverage).

    Priority: marked files (always kept, even past `cap`, up to `ceiling`), then scanner-hit
    files by descending severity until `cap`. If nothing is marked or flagged, fall back to the
    first `cap` source files so the agents always contribute.
    """
    all_paths = [f.path for f in files]
    marked = {m for m in marked if m in set(all_paths)}
    if len(marked) > ceiling:
        raise SelectionError(
            f"{len(marked)} files marked for deep review; max is {ceiling}. Narrow your selection."
        )

    hits = _max_sev_by_file(scanner_findings)
    hit_paths = sorted(
        (p for p in all_paths if p in hits and p not in marked),
        key=lambda p: (-hits[p], all_paths.index(p)),
    )

    chosen: dict[str, str] = {p: "marked" for p in marked}
    remaining = max(cap - len(chosen), 0)
    for p in hit_paths[:remaining]:
        chosen[p] = "scanner-hit"

    if not chosen:  # nothing marked, nothing flagged -> review the first N source files
        for f in files:
            if f.language is not None and len(chosen) < cap:
                chosen[f.path] = "fallback"

    coverage: list[FileCoverage] = []
    for p in all_paths:
        if p in chosen:
            coverage.append(FileCoverage(path=p, agent_reviewed=True, reason=chosen[p]))
        elif p in hits:
            coverage.append(FileCoverage(path=p, agent_reviewed=False, reason="over-cap"))
        else:
            coverage.append(FileCoverage(path=p, agent_reviewed=False, reason="not-flagged"))
    return list(chosen), coverage
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest apps/api/tests/test_selection.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/adc_api/selection.py apps/api/tests/test_selection.py
git commit -m "feat(api): agent file selection (marks + scanner hits, cap/ceiling, fallback) + coverage

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: ReviewService — corpus pipeline (two tiers + coverage)

**Files:**
- Modify: `apps/api/src/adc_api/review_service.py`
- Test: `apps/api/tests/test_review_service.py`

The heart of the increment: scanners once over the corpus, agents per-file under a semaphore, file-aware aggregate, coverage, bounded progress, all-failed semantics.

- [ ] **Step 1: Write the failing tests** (replace the whole file — the `run()` signature changes from `code=` to `files=`)

Replace `apps/api/tests/test_review_service.py` with:

```python
import pytest
from adc_api.agents import build_agents
from adc_api.corpus import CorpusFile
from adc_api.providers import MockProvider
from adc_api.review_service import ReviewService


def _files(*paths):
    return [CorpusFile(p, "x = 1\n", "python") for p in paths]


@pytest.mark.asyncio
async def test_per_file_findings_carry_file_and_merge_per_file():
    agents = build_agents(provider=MockProvider(seed=[{
        "category": "security", "severity": "high", "title": "SQL injection",
        "description": "d", "recommendation": "r", "start_line": 1, "end_line": 1,
    }]))
    svc = ReviewService(agents=agents, scanners=[])
    result = await svc.run(
        review_id="r1", files=_files("a.py", "b.py"), marked={"a.py", "b.py"},
        on_progress=lambda e: None,
    )
    assert result.status == "done"
    # one merged card per file (all six agents cite the same issue within each file)
    files = sorted(f.location.file for f in result.findings)
    assert files == ["a.py", "b.py"]
    assert result.coverage.files_total == 2
    assert result.coverage.files_agent_reviewed == 2


@pytest.mark.asyncio
async def test_skipped_files_recorded_in_coverage():
    agents = build_agents(provider=MockProvider(seed=[]))
    svc = ReviewService(agents=agents, scanners=[])
    result = await svc.run(
        review_id="r2", files=_files("a.py", "b.py", "c.py"), marked={"a.py"},
        on_progress=lambda e: None,
    )
    by = {c.path: c for c in result.coverage.files}
    assert by["a.py"].agent_reviewed and by["a.py"].reason == "marked"
    assert not by["b.py"].agent_reviewed and by["b.py"].reason == "not-flagged"
    assert result.coverage.files_agent_reviewed == 1


@pytest.mark.asyncio
async def test_all_agents_failing_surfaces_as_failed_not_clean():
    class _Boom(MockProvider):
        async def complete_structured(self, **kwargs):
            raise RuntimeError("auth error")

    svc = ReviewService(agents=build_agents(provider=_Boom()), scanners=[])
    stages: list[str] = []
    result = await svc.run(
        review_id="rf", files=_files("a.py"), marked={"a.py"},
        on_progress=lambda e: stages.append(e.stage),
    )
    assert result.status == "failed"
    assert "agents failed" in (result.error or "")
    assert stages[-1] == "failed"


@pytest.mark.asyncio
async def test_progress_reports_bounded_file_counts():
    agents = build_agents(provider=MockProvider(seed=[]))
    svc = ReviewService(agents=agents, scanners=[])
    subs: list[dict] = []
    await svc.run(
        review_id="rp", files=_files("a.py", "b.py"), marked={"a.py", "b.py"},
        on_progress=lambda e: subs.append(e.sub_status) if e.stage == "analyzing" else None,
    )
    last = subs[-1]
    assert last.get("filesTotal") == "2" and last.get("filesReviewed") == "2"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest apps/api/tests/test_review_service.py -q`
Expected: FAIL (`run()` got unexpected keyword `files`).

- [ ] **Step 3: Implement**

Replace `apps/api/src/adc_api/review_service.py` with:

```python
from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from adc_core.models import Coverage, Finding, ReviewResult, ReviewStatus
from adc_core.syntax import check_syntax

from adc_api.aggregator import aggregate
from adc_api.agents import SpecialistAgent, build_agents
from adc_api.corpus import CorpusFile
from adc_api.graph import build_graph
from adc_api.scanners import Scanner, build_scanners
from adc_api.schemas import ProgressEvent
from adc_api.selection import select_agent_files
from adc_api.settings import settings

OnProgress = Callable[[ProgressEvent], None]


def _summarize(findings: list[Finding]) -> str:
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.category] = counts.get(f.category, 0) + 1
    return ", ".join(f"{n} {c}" for c, n in sorted(counts.items())) or "no issues found"


class ReviewService:
    """Runs the two-tier corpus review behind a stable run() signature."""

    def __init__(
        self,
        agents: list[SpecialistAgent] | None = None,
        scanners: list[Scanner] | None = None,
    ) -> None:
        self._agents = agents if agents is not None else build_agents()
        self._scanners = scanners if scanners is not None else build_scanners()
        self._agent_names = {a.name for a in self._agents}
        self._graph = build_graph(self._agents)  # agents-only per-file fan-out

    async def _scan_corpus(self, work_dir: str, languages: set[str]) -> list[Finding]:
        async def run_one(scanner: Scanner) -> list[Finding]:
            if scanner.languages and not (scanner.languages & languages):
                return []
            try:
                return await scanner.scan_path(work_dir)
            except Exception:  # noqa: BLE001 — a scanner failure never sinks the review
                return []

        results = await asyncio.gather(*(run_one(s) for s in self._scanners))
        return [f for r in results for f in r]

    async def _review_file(
        self, f: CorpusFile
    ) -> tuple[list[Finding], set[str], bool]:
        """Run the agent fan-out on one file. Returns (findings, failed_agents, any_agent_ok)."""
        syntax = check_syntax(f.language or "", f.content) if f.language else []
        for s in syntax:
            s.location.file = f.path
        findings: list[Finding] = list(syntax)
        failed: set[str] = set()
        any_ok = False
        async for update in self._graph.astream(
            {"code": f.content, "language": f.language or "text", "file": f.path,
             "findings": list(syntax), "failures": [], "result": []},
            stream_mode="updates",
        ):
            for node_name, delta in update.items():
                if node_name in self._agent_names:
                    if isinstance(delta, dict) and delta.get("failures"):
                        failed.update(delta["failures"])
                    else:
                        any_ok = True
                if isinstance(delta, dict) and node_name == "aggregate":
                    findings = delta["result"]
        return findings, failed, any_ok

    async def run(
        self, *, review_id: str, files: list[CorpusFile], marked: set[str],
        on_progress: OnProgress, work_dir: str | None = None,
        parent_review_id: str | None = None,
    ) -> ReviewResult:
        started = time.monotonic()
        model_label = ",".join(sorted({a.provider.model for a in self._agents}))
        result = ReviewResult(
            id=review_id, language=(files[0].language or "text") if files else "text",
            model=model_label, parent_review_id=parent_review_id,
        )

        def emit(stage: ReviewStatus, **kw) -> None:
            result.status = stage
            on_progress(ProgressEvent(review_id=review_id, stage=stage, **kw))

        try:
            emit("validating")
            languages = {f.language for f in files if f.language}

            def sub(scan: str, reviewed: int, total: int) -> dict[str, str]:
                return {"scan": scan, "filesReviewed": str(reviewed), "filesTotal": str(total)}

            emit("analyzing", sub_status=sub("running", 0, 0))
            scanner_findings = (
                await self._scan_corpus(work_dir, languages) if work_dir and self._scanners else []
            )

            agent_paths, coverage_files = select_agent_files(
                files, marked=marked, scanner_findings=scanner_findings,
                cap=settings.agent_file_cap, ceiling=settings.agent_file_ceiling,
            )
            agent_set = [f for f in files if f.path in set(agent_paths)]
            total = len(agent_set)
            emit("analyzing", sub_status=sub("done", 0, total))

            sem = asyncio.Semaphore(settings.file_concurrency)
            reviewed = 0
            all_findings: list[Finding] = list(scanner_findings)
            failed_agents: set[str] = set()
            any_agent_ok = False

            async def worker(cf: CorpusFile) -> None:
                nonlocal reviewed, any_agent_ok
                async with sem:
                    f_findings, f_failed, f_ok = await self._review_file(cf)
                all_findings.extend(f_findings)
                failed_agents.update(f_failed)
                any_agent_ok = any_agent_ok or f_ok
                reviewed += 1
                emit("analyzing", sub_status=sub("done", reviewed, total))

            await asyncio.gather(*(worker(cf) for cf in agent_set))

            aggregated = aggregate(all_findings)
            result.duration_ms = int((time.monotonic() - started) * 1000)
            result.coverage = Coverage(
                files_total=len(files),
                files_agent_reviewed=sum(1 for c in coverage_files if c.agent_reviewed),
                files=coverage_files,
            )

            # If agents were asked to review files but EVERY agent invocation failed (e.g. bad
            # API key) and produced nothing, surface failed instead of a misleading empty "done".
            if agent_set and not any_agent_ok and failed_agents and not [
                f for f in aggregated if any(s.type == "agent" for s in f.sources)
            ]:
                result.error = (
                    f"All review agents failed ({', '.join(sorted(failed_agents))}). "
                    "Check the model provider / API key."
                )
                emit("failed", message=result.error)
            else:
                emit("finalizing")
                result.findings = aggregated
                result.summary = _summarize(aggregated)
                emit("done")
        except Exception as exc:  # noqa: BLE001 — surfaced to the user as a failed job
            result.error = str(exc)
            result.duration_ms = int((time.monotonic() - started) * 1000)
            emit("failed", message=str(exc))
        return result
```

Note: `build_graph(self._agents)` uses the default `scanners=()`, so the per-file graph is agents-only.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest apps/api/tests/test_review_service.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/adc_api/review_service.py apps/api/tests/test_review_service.py
git commit -m "feat(api): two-tier corpus pipeline — scanners once, agents per file, coverage

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 10: Request schema — `files[]` + `marked[]`

**Files:**
- Modify: `apps/api/src/adc_api/schemas.py`
- Test: `apps/api/tests/test_settings.py` (or a small new `test_schemas.py`)

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/test_schemas.py`:

```python
def test_review_request_accepts_files_and_marked_camelcase():
    from adc_api.schemas import ReviewRequest

    req = ReviewRequest.model_validate({
        "files": [{"path": "a.py", "content": "x=1\n"}],
        "marked": ["a.py"],
    })
    assert req.files[0].path == "a.py"
    assert req.marked == ["a.py"]


def test_review_request_legacy_code_still_valid():
    from adc_api.schemas import ReviewRequest

    req = ReviewRequest.model_validate({"language": "python", "code": "x=1\n"})
    assert req.code == "x=1\n" and req.files == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest apps/api/tests/test_schemas.py -q`
Expected: FAIL (`files`/`marked` not fields; `language`/`code` currently required).

- [ ] **Step 3: Implement**

In `apps/api/src/adc_api/schemas.py`, replace `ReviewRequest` and add `FileInput`:

```python
class FileInput(_Camel):
    path: str
    content: str
    language: str | None = None

class ReviewRequest(_Camel):
    language: str | None = None        # legacy single-snippet
    code: str | None = None            # legacy single-snippet
    files: list[FileInput] = Field(default_factory=list)
    marked: list[str] = Field(default_factory=list)
```

(Add `Field` to the existing `from pydantic import ...` if not already imported — it is.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest apps/api/tests/test_schemas.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/adc_api/schemas.py apps/api/tests/test_schemas.py
git commit -m "feat(api): ReviewRequest accepts files[]+marked[] (legacy code/language optional)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 11: Worker + queue — corpus-based job signature

**Files:**
- Modify: `apps/api/src/adc_api/worker.py`, `apps/api/src/adc_api/queue.py`
- Test: `apps/api/tests/test_worker.py`, `apps/api/tests/test_queue.py`

The job no longer carries code — it carries `review_id` + `marked` and loads the corpus from the shared `CorpusStore`.

- [ ] **Step 1: Write the failing test**

Replace `apps/api/tests/test_worker.py` with (read the old file first to preserve any other cases; this is the core one):

```python
import pytest
from adc_api.corpus import CorpusStore, ingest_files
from adc_api.agents import build_agents
from adc_api.events import InMemoryEventBus
from adc_api.providers import MockProvider
from adc_api.repository import InMemoryReviewRepository
from adc_api.worker import run_review_core


@pytest.mark.asyncio
async def test_run_review_core_loads_corpus_and_saves_result(tmp_path):
    store = CorpusStore(str(tmp_path))
    store.write("rev1", ingest_files([{"path": "a.py", "content": "x = 1\n"}]))
    repo = InMemoryReviewRepository()
    await repo.create("rev1", "python")
    bus = InMemoryEventBus()
    provider = MockProvider(seed=[{
        "category": "security", "severity": "high", "title": "SQLi",
        "description": "d", "recommendation": "r", "start_line": 1, "end_line": 1,
    }])

    await run_review_core(
        "rev1", ["a.py"], repo=repo, bus=bus, store=store,
        agents=build_agents(provider=provider),
    )
    result = await repo.get("rev1")
    assert result.status == "done"
    assert result.coverage.files_total == 1
    assert result.findings[0].location.file == "a.py"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest apps/api/tests/test_worker.py -q`
Expected: FAIL (`run_review_core` signature mismatch).

- [ ] **Step 3: Implement**

Replace `apps/api/src/adc_api/worker.py` with:

```python
from __future__ import annotations

import asyncio

from adc_api.agents import SpecialistAgent, build_agents
from adc_api.corpus import CorpusStore
from adc_api.events import EventBus, RedisEventBus
from adc_api.repository import ReviewRepository, SqlReviewRepository
from adc_api.review_service import ReviewService
from adc_api.schemas import ProgressEvent

_TERMINAL = {"done", "failed"}


async def run_review_core(
    review_id: str,
    marked: list[str],
    *,
    repo: ReviewRepository,
    bus: EventBus,
    store: CorpusStore,
    agents: list[SpecialistAgent],
) -> None:
    """Load the persisted corpus, run the two-tier review, stream non-terminal stages live, then
    save the final result and publish the terminal event LAST."""
    events: asyncio.Queue[ProgressEvent | None] = asyncio.Queue()

    def on_progress(event: ProgressEvent) -> None:
        events.put_nowait(event)

    async def drain() -> None:
        while True:
            ev = await events.get()
            if ev is None:
                return
            if ev.stage not in _TERMINAL:
                await repo.set_status(review_id, ev.stage)
                await bus.publish(review_id, ev)

    drain_task = asyncio.create_task(drain())
    svc = ReviewService(agents=agents)
    result = await svc.run(
        review_id=review_id, files=store.list_files(review_id), marked=set(marked),
        on_progress=on_progress, work_dir=str(store.path(review_id)),
    )
    events.put_nowait(None)
    await drain_task

    await repo.save_result(result)
    await bus.publish(review_id, ProgressEvent(review_id=review_id, stage=result.status))


# ---- arq task + worker settings (production) ----

async def run_review(ctx: dict, review_id: str, marked: list[str]) -> None:
    await run_review_core(
        review_id, marked, repo=ctx["repo"], bus=ctx["bus"], store=ctx["store"],
        agents=build_agents(),
    )


async def _on_startup(ctx: dict) -> None:
    from adc_api.db.engine import make_engine, make_session_factory
    from adc_api.settings import settings

    ctx["repo"] = SqlReviewRepository(make_session_factory(make_engine(settings.database_url)))
    ctx["bus"] = RedisEventBus(settings.redis_url)
    ctx["store"] = CorpusStore(settings.work_root)


def _redis_settings():
    from arq.connections import RedisSettings

    from adc_api.settings import settings

    return RedisSettings.from_dsn(settings.redis_url)


class WorkerSettings:
    functions = [run_review]
    on_startup = _on_startup
    redis_settings = _redis_settings()
    max_tries = 1
```

Replace `apps/api/src/adc_api/queue.py` with:

```python
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Protocol

from adc_api.agents import SpecialistAgent, build_agents
from adc_api.corpus import CorpusStore
from adc_api.events import EventBus
from adc_api.repository import ReviewRepository
from adc_api.worker import run_review_core


class ReviewQueue(Protocol):
    async def enqueue(self, review_id: str, marked: list[str]) -> None: ...


class InlineReviewQueue:
    """Runs the review in-process (memory backend / tests / quick demo), fire-and-forget."""

    def __init__(
        self,
        repo: ReviewRepository,
        bus: EventBus,
        store: CorpusStore,
        agents_factory: Callable[[], list[SpecialistAgent]] = build_agents,
    ) -> None:
        self._repo = repo
        self._bus = bus
        self._store = store
        self._agents_factory = agents_factory
        self._tasks: set[asyncio.Task[None]] = set()

    async def enqueue(self, review_id: str, marked: list[str]) -> None:
        task = asyncio.create_task(
            run_review_core(
                review_id, marked, repo=self._repo, bus=self._bus, store=self._store,
                agents=self._agents_factory(),
            )
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)


class ArqReviewQueue:
    """Enqueues the `run_review` job onto arq/Redis (production)."""

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url

    async def enqueue(self, review_id: str, marked: list[str]) -> None:
        from arq import create_pool
        from arq.connections import RedisSettings

        pool = await create_pool(RedisSettings.from_dsn(self._redis_url))
        try:
            await pool.enqueue_job("run_review", review_id, marked)
        finally:
            await pool.aclose()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest apps/api/tests/test_worker.py apps/api/tests/test_queue.py -q`
Expected: PASS. (Update `test_queue.py` to the new `enqueue(review_id, marked)` + `InlineReviewQueue(repo, bus, store, ...)` signature; read it and adapt — it must construct a `CorpusStore(tmp)` and write a corpus first.)

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/adc_api/worker.py apps/api/src/adc_api/queue.py apps/api/tests/test_worker.py apps/api/tests/test_queue.py
git commit -m "feat(api): corpus-based job — queue/worker load files from CorpusStore by review id

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 12: Repository + migration — persist coverage + parent id; `fileCount` in list

**Files:**
- Modify: `apps/api/src/adc_api/db/models.py`, `apps/api/src/adc_api/repository.py`
- Create: `apps/api/migrations/versions/0002_corpus_columns.py`
- Test: `apps/api/tests/test_repository.py`, `apps/api/tests/test_db_models.py`

- [ ] **Step 1: Write the failing test**

Append to `apps/api/tests/test_repository.py` (read the file for its in-memory/SQLite fixture style and match it):

```python
@pytest.mark.asyncio
async def test_inmemory_roundtrips_coverage_and_parent():
    from adc_core.models import Coverage, FileCoverage, ReviewResult
    from adc_api.repository import InMemoryReviewRepository

    repo = InMemoryReviewRepository()
    await repo.create("r1", "python")
    cov = Coverage(files_total=2, files_agent_reviewed=1,
                   files=[FileCoverage(path="a.py", agent_reviewed=True, reason="marked")])
    await repo.save_result(ReviewResult(
        id="r1", status="done", language="python", model="m", coverage=cov,
        parent_review_id="p0",
    ))
    got = await repo.get("r1")
    assert got.coverage.files_total == 2 and got.parent_review_id == "p0"
```

(If `test_repository.py` exercises `SqlReviewRepository` over SQLite, add the same assertions there too, matching its fixture.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest apps/api/tests/test_repository.py -k coverage -q`
Expected: FAIL (SQL path drops coverage/parent; or assertion error).

- [ ] **Step 3: Implement**

In `apps/api/src/adc_api/db/models.py`, add columns to `ReviewRow`:

```python
    coverage: Mapped[dict | None] = mapped_column(_JSON, nullable=True)
    parent_review_id: Mapped[str | None] = mapped_column(String, nullable=True)
```

In `apps/api/src/adc_api/repository.py`:

- In `_row_to_result`, reconstruct the new fields:

```python
from adc_core.models import Coverage  # add to imports

    return ReviewResult(
        id=row.id,
        status=row.status,  # type: ignore[arg-type]
        language=row.language,
        model=row.model,
        findings=[Finding.model_validate(f) for f in (row.findings or [])],
        summary=row.summary,
        created_at=row.created_at,
        duration_ms=row.duration_ms,
        error=row.error,
        coverage=Coverage.model_validate(row.coverage) if row.coverage else None,
        parent_review_id=row.parent_review_id,
    )
```

- Add `set_parent` to the `ReviewRepository` Protocol (the rerun endpoint tags the new review's parent before the worker runs):

```python
    async def set_parent(self, review_id: str, parent_review_id: str) -> None: ...
```

- `InMemoryReviewRepository`: add `set_parent` and preserve a previously-set parent in `save_result` (the worker's `run()` doesn't know the parent, so don't let it null it out):

```python
    async def set_parent(self, review_id: str, parent_review_id: str) -> None:
        if review_id in self._d:
            self._d[review_id].parent_review_id = parent_review_id

    async def save_result(self, result: ReviewResult) -> None:
        existing = self._d.get(result.id)
        if existing is not None:
            result.created_at = existing.created_at
            result.parent_review_id = result.parent_review_id or existing.parent_review_id
        self._d[result.id] = result
```

- `SqlReviewRepository`: add `set_parent` and persist coverage + a preserved parent in `save_result` (inside the existing block):

```python
    async def set_parent(self, review_id: str, parent_review_id: str) -> None:
        async with self._sf() as s, s.begin():
            row = await s.get(ReviewRow, review_id)
            if row is not None:
                row.parent_review_id = parent_review_id
```

and inside `save_result`'s existing `row.* = ...` block:

```python
            row.coverage = (
                result.coverage.model_dump(by_alias=True, mode="json")
                if result.coverage else None
            )
            row.parent_review_id = result.parent_review_id or row.parent_review_id
```

Create `apps/api/migrations/versions/0002_corpus_columns.py`:

```python
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("reviews", sa.Column("coverage", JSONB(), nullable=True))
    op.add_column("reviews", sa.Column("parent_review_id", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("reviews", "parent_review_id")
    op.drop_column("reviews", "coverage")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest apps/api/tests/test_repository.py apps/api/tests/test_db_models.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/adc_api/db/models.py apps/api/src/adc_api/repository.py apps/api/migrations/versions/0002_corpus_columns.py apps/api/tests/test_repository.py
git commit -m "feat(api): persist coverage + parentReviewId (migration 0002)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 13: API endpoints — files[]/zip/rerun/file + wire CorpusStore

**Files:**
- Modify: `apps/api/src/adc_api/main.py`
- Test: `apps/api/tests/test_api.py`

- [ ] **Step 1: Write the failing tests** (replace `_app()` helper to inject a store; add multi-file + rerun + file-endpoint tests)

Replace `apps/api/tests/test_api.py` with (preserving the legacy 422 test):

```python
import tempfile

import pytest
from adc_api.agents import build_agents
from adc_api.corpus import CorpusStore
from adc_api.events import InMemoryEventBus
from adc_api.main import create_app
from adc_api.providers import MockProvider
from adc_api.queue import InlineReviewQueue
from adc_api.repository import InMemoryReviewRepository
from httpx import ASGITransport, AsyncClient


def _app():
    repo = InMemoryReviewRepository()
    bus = InMemoryEventBus()
    store = CorpusStore(tempfile.mkdtemp())
    provider = MockProvider(seed=[{
        "category": "security", "severity": "high", "title": "SQLi",
        "description": "concat", "recommendation": "params", "start_line": 1, "end_line": 1,
    }])
    queue = InlineReviewQueue(repo, bus, store, agents_factory=lambda: build_agents(provider=provider))
    return create_app(repo=repo, bus=bus, queue=queue, store=store)


async def _drain(c, review_id):
    async with c.stream("GET", f"/api/reviews/{review_id}/events") as s:
        async for _ in s.aiter_lines():
            pass


@pytest.mark.asyncio
async def test_multifile_review_carries_files_and_coverage():
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.post("/api/reviews", json={
            "files": [{"path": "a.py", "content": "x=1\n"}, {"path": "b.py", "content": "y=2\n"}],
            "marked": ["a.py", "b.py"],
        })
        assert r.status_code == 202
        rid = r.json()["reviewId"]
        await _drain(c, rid)
        result = (await c.get(f"/api/reviews/{rid}")).json()
        assert result["status"] == "done"
        assert result["coverage"]["filesTotal"] == 2
        assert {f["location"]["file"] for f in result["findings"]} == {"a.py", "b.py"}


@pytest.mark.asyncio
async def test_legacy_code_still_works_and_rejects_bad_language():
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        ok = await c.post("/api/reviews", json={"language": "python", "code": "x=1\n"})
        assert ok.status_code == 202
        bad = await c.post("/api/reviews", json={"language": "cobol", "code": "x"})
        assert bad.status_code == 422


@pytest.mark.asyncio
async def test_get_file_serves_content_and_blocks_traversal():
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        rid = (await c.post("/api/reviews", json={
            "files": [{"path": "a.py", "content": "hello\n"}], "marked": ["a.py"],
        })).json()["reviewId"]
        await _drain(c, rid)
        good = await c.get(f"/api/reviews/{rid}/file", params={"path": "a.py"})
        assert good.status_code == 200 and good.json()["content"] == "hello\n"
        bad = await c.get(f"/api/reviews/{rid}/file", params={"path": "../../etc/passwd"})
        assert bad.status_code == 400


@pytest.mark.asyncio
async def test_rerun_reuses_corpus_with_new_marks():
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        rid = (await c.post("/api/reviews", json={
            "files": [{"path": "a.py", "content": "x=1\n"}, {"path": "b.py", "content": "y=2\n"}],
            "marked": ["a.py"],
        })).json()["reviewId"]
        await _drain(c, rid)
        rr = await c.post(f"/api/reviews/{rid}/rerun", json={"marked": ["a.py", "b.py"]})
        assert rr.status_code == 202
        rid2 = rr.json()["reviewId"]
        await _drain(c, rid2)
        result = (await c.get(f"/api/reviews/{rid2}")).json()
        assert result["parentReviewId"] == rid
        assert result["coverage"]["filesAgentReviewed"] == 2


@pytest.mark.asyncio
async def test_list_includes_file_count():
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        rid = (await c.post("/api/reviews", json={
            "files": [{"path": "a.py", "content": "x=1\n"}], "marked": ["a.py"],
        })).json()["reviewId"]
        await _drain(c, rid)
        listing = (await c.get("/api/reviews")).json()
        row = next(x for x in listing if x["id"] == rid)
        assert row["fileCount"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest apps/api/tests/test_api.py -q`
Expected: FAIL (`create_app` has no `store`; endpoints missing).

- [ ] **Step 3: Implement**

Rewrite `apps/api/src/adc_api/main.py`:

```python
from __future__ import annotations

import json
import uuid

from adc_core.sanitization import SubmissionError, validate_submission
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from adc_api.corpus import CorpusFile, CorpusStore, IngestError, ingest_files, ingest_zip
from adc_api.events import EventBus, InMemoryEventBus, RedisEventBus
from adc_api.queue import ArqReviewQueue, InlineReviewQueue, ReviewQueue
from adc_api.repository import InMemoryReviewRepository, ReviewRepository, SqlReviewRepository
from adc_api.schemas import ProgressEvent, ReviewRequest
from adc_api.settings import settings

_TERMINAL = {"done", "failed"}


class RerunRequest(BaseModel):
    marked: list[str] = []


def _default_deps() -> tuple[ReviewRepository, EventBus, ReviewQueue, CorpusStore]:
    store = CorpusStore(settings.work_root)
    if settings.backend == "memory":
        repo: ReviewRepository = InMemoryReviewRepository()
        bus: EventBus = InMemoryEventBus()
        return repo, bus, InlineReviewQueue(repo, bus, store), store
    from adc_api.db.engine import make_engine, make_session_factory

    repo = SqlReviewRepository(make_session_factory(make_engine(settings.database_url)))
    bus = RedisEventBus(settings.redis_url)
    return repo, bus, ArqReviewQueue(settings.redis_url), store


def _corpus_from_request(req: ReviewRequest) -> list[CorpusFile]:
    """Legacy {code,language} -> 1-file corpus; otherwise ingest files[]."""
    if req.files:
        return ingest_files([f.model_dump() for f in req.files])
    if req.code is not None and req.language is not None:
        code = validate_submission(
            req.language, req.code,
            max_bytes=settings.max_code_bytes, max_lines=settings.max_code_lines,
        )
        ext = {"python": "py", "typescript": "ts", "java": "java"}.get(req.language, "txt")
        return [CorpusFile(path=f"snippet.{ext}", content=code, language=req.language)]
    raise IngestError("provide either files[] or code+language")


def create_app(
    repo: ReviewRepository | None = None,
    bus: EventBus | None = None,
    queue: ReviewQueue | None = None,
    store: CorpusStore | None = None,
) -> FastAPI:
    if repo is None or bus is None or queue is None or store is None:
        d_repo, d_bus, d_queue, d_store = _default_deps()
        repo, bus, queue, store = repo or d_repo, bus or d_bus, queue or d_queue, store or d_store

    app = FastAPI(title="AI Dev Companion API")
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )

    async def _start(files: list[CorpusFile], marked: list[str], parent: str | None = None) -> str:
        review_id = str(uuid.uuid4())
        store.write(review_id, files)
        await repo.create(review_id, (files[0].language or "text"))
        valid = {f.path for f in files}
        await queue.enqueue(review_id, [m for m in marked if m in valid])
        return review_id

    @app.post("/api/reviews", status_code=202)
    async def create_review(req: ReviewRequest) -> dict:
        try:
            files = _corpus_from_request(req)
        except (IngestError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except SubmissionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        marked = req.marked or [f.path for f in files]
        return {"reviewId": await _start(files, marked), "status": "queued"}

    @app.post("/api/reviews/zip", status_code=202)
    async def create_review_zip(file: UploadFile) -> dict:
        try:
            files = ingest_zip(await file.read())
        except IngestError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"reviewId": await _start(files, [f.path for f in files]), "status": "queued"}

    @app.post("/api/reviews/{review_id}/rerun", status_code=202)
    async def rerun_review(review_id: str, req: RerunRequest) -> dict:
        if await repo.get(review_id) is None:
            raise HTTPException(status_code=404, detail="review not found")
        new_id = str(uuid.uuid4())
        store.copy(review_id, new_id)
        files = store.list_files(new_id)
        await repo.create(new_id, (files[0].language or "text") if files else "text")
        valid = {f.path for f in files}
        await queue.enqueue(new_id, [m for m in req.marked if m in valid])
        # tag the parent so the result links back (worker reads it from list_files? no —
        # pass via repo: store parent at create time)
        await repo.set_parent(new_id, review_id)
        return {"reviewId": new_id, "status": "queued", "parentReviewId": review_id}

    @app.get("/api/reviews/{review_id}/file")
    async def get_file(review_id: str, path: str) -> dict:
        try:
            return {"path": path, "content": store.read_file(review_id, path)}
        except IngestError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/reviews/{review_id}/events")
    async def review_events(review_id: str) -> EventSourceResponse:
        if await repo.get(review_id) is None:
            raise HTTPException(status_code=404, detail="review not found")

        async def gen():
            agen = await bus.subscribe(review_id)
            snap = await repo.get(review_id)
            if snap is not None and snap.status in _TERMINAL:
                ev = ProgressEvent(review_id=review_id, stage=snap.status)
                yield {"event": "progress",
                       "data": json.dumps(ev.model_dump(by_alias=True), default=str)}
                yield {"event": "complete", "data": "{}"}
                await agen.aclose()
                return
            async for ev in agen:
                yield {"event": "progress",
                       "data": json.dumps(ev.model_dump(by_alias=True), default=str)}
            yield {"event": "complete", "data": "{}"}

        return EventSourceResponse(gen())

    @app.get("/api/reviews")
    async def list_reviews() -> list[dict]:
        out = []
        for r in await repo.list_all():
            d = r.model_dump(by_alias=True, mode="json")
            d["fileCount"] = r.coverage.files_total if r.coverage else 0
            out.append(d)
        return out

    @app.get("/api/reviews/{review_id}")
    async def get_review(review_id: str) -> dict:
        result = await repo.get(review_id)
        if result is None:
            raise HTTPException(status_code=404, detail="review not found")
        return result.model_dump(by_alias=True, mode="json")

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
```

`repo.set_parent(...)` and the parent-preservation in `save_result` were added in Task 12 — the rerun endpoint above just calls `set_parent`, then the worker's `save_result` keeps the parent because Task 12 made it preserve a non-null parent.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest apps/api/tests/test_api.py -q`
Expected: PASS (5 tests). Then full suite: `uv run pytest packages/core apps/api -q` — fix any cross-test fallout (e.g. `test_integration.py` if it constructs `InlineReviewQueue`/`run_review_core` with old signatures; read and update to pass a `CorpusStore` + a written corpus).

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/adc_api/main.py apps/api/src/adc_api/repository.py apps/api/tests/test_api.py
git commit -m "feat(api): multi-file endpoints — files[]/zip/rerun/file + fileCount; wire CorpusStore

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 14: Backend green sweep + ruff + integration test

**Files:**
- Modify: any backend test left on an old signature (`apps/api/tests/test_integration.py`, etc.)

- [ ] **Step 1: Run the full suite**

Run: `uv run pytest packages/core apps/api -q`
Expected: all pass. If a test fails because it used the old `run()`/`enqueue()`/`scan()` signatures, read it and update to the corpus equivalents (write a corpus via `CorpusStore`, pass `files=`/`marked=`/`store=`).

- [ ] **Step 2: Lint**

Run: `uv run ruff check .`
Expected: `All checks passed!` Fix any unused imports left by the scanner/review_service refactors.

- [ ] **Step 3: Update the gated integration test for multi-file**

In `apps/api/tests/test_integration.py` (read it first), update/add a `@pytest.mark.integration` test that writes a 2-file Python corpus (one with an obvious SQLi) to a `CorpusStore`, runs `run_review_core` with real scanners (`settings.scanners` reset), and asserts a finding on the SQLi file carries a `bandit`/`semgrep` source. Self-skips if `docker version` fails (reuse the existing skip guard).

- [ ] **Step 4: Verify integration test collection (not run without Docker)**

Run: `uv run pytest apps/api -q -m integration --collect-only`
Expected: collects without import errors.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "test(api): green sweep + multi-file gated integration; ruff clean

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 15: Frontend types + client

**Files:**
- Modify: `apps/web/src/api/types.ts`, `apps/web/src/api/client.ts`
- Test: `apps/web/src/api/client.test.ts`

- [ ] **Step 1: Write the failing test**

Append to `apps/web/src/api/client.test.ts` (read it for its fetch-mock style; match it):

```ts
import { describe, expect, it, vi } from "vitest";
import { createReview, getFile, rerunReview } from "./client";

describe("multi-file client", () => {
  it("createReview posts files + marked and returns id", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ reviewId: "r1" }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const id = await createReview({ files: [{ path: "a.py", content: "x" }], marked: ["a.py"] });
    expect(id).toBe("r1");
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.files[0].path).toBe("a.py");
    expect(body.marked).toEqual(["a.py"]);
  });

  it("getFile fetches file content", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ path: "a.py", content: "hello" }),
    }));
    expect(await getFile("r1", "a.py")).toBe("hello");
  });

  it("rerunReview posts marks and returns new id", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ reviewId: "r2" }),
    }));
    expect(await rerunReview("r1", ["a.py"])).toBe("r2");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --filter web test -- --run src/api/client.test.ts`
Expected: FAIL (`createReview`/`getFile`/`rerunReview` signatures/exports missing).

- [ ] **Step 3: Implement**

In `apps/web/src/api/types.ts`, add:

```ts
export type CoverageReason = "marked" | "scanner-hit" | "fallback" | "not-flagged" | "over-cap";
export interface FileCoverage { path: string; agentReviewed: boolean; reason: CoverageReason; }
export interface Coverage { filesTotal: number; filesAgentReviewed: number; files: FileCoverage[]; }
export interface FileInput { path: string; content: string; language?: string; }
export interface CreateReviewBody { files: FileInput[]; marked: string[]; }
```

and extend `ReviewResult`:

```ts
  coverage?: Coverage; parentReviewId?: string;
```

(and the history row type — extend the `ReviewResult` usage with optional `fileCount?: number;`).

Replace `apps/web/src/api/client.ts` `createReview` and add the new calls:

```ts
import type { CreateReviewBody, ReviewResult } from "./types";

export const BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export async function createReview(body: CreateReviewBody): Promise<string> {
  const res = await fetch(`${BASE}/api/reviews`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`createReview failed: ${res.status} ${await res.text()}`);
  return (await res.json()).reviewId as string;
}

export async function rerunReview(id: string, marked: string[]): Promise<string> {
  const res = await fetch(`${BASE}/api/reviews/${id}/rerun`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ marked }),
  });
  if (!res.ok) throw new Error(`rerun failed: ${res.status}`);
  return (await res.json()).reviewId as string;
}

export async function getFile(id: string, path: string): Promise<string> {
  const res = await fetch(`${BASE}/api/reviews/${id}/file?path=${encodeURIComponent(path)}`);
  if (!res.ok) throw new Error(`getFile failed: ${res.status}`);
  return (await res.json()).content as string;
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

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm --filter web test -- --run src/api/client.test.ts` then `pnpm --filter web exec tsc --noEmit`
Expected: PASS + no type errors. (Update `useReviewStream.ts` call sites to the new `createReview(body)` shape — Task 17 covers the hook; for now keep tsc green by adjusting the hook's `createReview` call.)

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/api/types.ts apps/web/src/api/client.ts apps/web/src/api/client.test.ts
git commit -m "feat(web): multi-file API client + types (createReview body, rerun, getFile, coverage)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 16: File tree component (tri-state, select-all, dir-toggle, badges, skipped)

**Files:**
- Create: `apps/web/src/components/FileTree.tsx`
- Create: `apps/web/src/components/fileTree.ts` (pure tree-building + toggle logic — easy to unit test)
- Test: `apps/web/src/components/fileTree.test.ts`

- [ ] **Step 1: Write the failing test**

Create `apps/web/src/components/fileTree.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { buildTree, togglePath, descendantFiles } from "./fileTree";

const PATHS = ["app/auth.py", "app/db.py", "tests/test_a.py"];

describe("file tree logic", () => {
  it("builds nested nodes from flat paths", () => {
    const root = buildTree(PATHS);
    const app = root.children.find((c) => c.name === "app")!;
    expect(app.isDir).toBe(true);
    expect(app.children.map((c) => c.name).sort()).toEqual(["auth.py", "db.py"]);
  });

  it("descendantFiles returns all files under a dir", () => {
    const root = buildTree(PATHS);
    expect(descendantFiles(root, "app").sort()).toEqual(["app/auth.py", "app/db.py"]);
  });

  it("toggling a dir selects all its files; toggling again clears them", () => {
    const root = buildTree(PATHS);
    let sel = new Set<string>();
    sel = togglePath(root, sel, "app");
    expect(sel).toEqual(new Set(["app/auth.py", "app/db.py"]));
    sel = togglePath(root, sel, "app");
    expect(sel.size).toBe(0);
  });

  it("toggling a file toggles just that file", () => {
    const root = buildTree(PATHS);
    const sel = togglePath(root, new Set<string>(), "app/auth.py");
    expect(sel).toEqual(new Set(["app/auth.py"]));
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --filter web test -- --run src/components/fileTree.test.ts`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement**

Create `apps/web/src/components/fileTree.ts`:

```ts
export interface TreeNode {
  name: string;
  path: string;       // full path for files; dir prefix for dirs
  isDir: boolean;
  children: TreeNode[];
}

export function buildTree(paths: string[]): TreeNode {
  const root: TreeNode = { name: "", path: "", isDir: true, children: [] };
  for (const p of [...paths].sort()) {
    const parts = p.split("/");
    let node = root;
    parts.forEach((part, i) => {
      const isFile = i === parts.length - 1;
      const path = parts.slice(0, i + 1).join("/");
      let child = node.children.find((c) => c.name === part && c.isDir === !isFile);
      if (!child) {
        child = { name: part, path, isDir: !isFile, children: [] };
        node.children.push(child);
      }
      node = child;
    });
  }
  const sortRec = (n: TreeNode) => {
    n.children.sort((a, b) => Number(b.isDir) - Number(a.isDir) || a.name.localeCompare(b.name));
    n.children.forEach(sortRec);
  };
  sortRec(root);
  return root;
}

function find(node: TreeNode, path: string): TreeNode | null {
  if (node.path === path) return node;
  for (const c of node.children) {
    const hit = find(c, path);
    if (hit) return hit;
  }
  return null;
}

export function descendantFiles(root: TreeNode, path: string): string[] {
  const node = path === "" ? root : find(root, path);
  if (!node) return [];
  if (!node.isDir) return [node.path];
  return node.children.flatMap((c) => descendantFiles(root, c.path));
}

export function togglePath(root: TreeNode, selected: Set<string>, path: string): Set<string> {
  const files = descendantFiles(root, path);
  const allSelected = files.every((f) => selected.has(f));
  const next = new Set(selected);
  for (const f of files) (allSelected ? next.delete(f) : next.add(f));
  return next;
}
```

Create `apps/web/src/components/FileTree.tsx` (presentational; uses the logic above):

```tsx
import { useMemo } from "react";
import { buildTree, descendantFiles, togglePath, type TreeNode } from "./fileTree";
import type { FileCoverage } from "../api/types";

interface Props {
  paths: string[];
  selected: Set<string>;
  onSelectedChange: (next: Set<string>) => void;
  active: string | null;
  onOpen: (path: string) => void;
  hits?: Record<string, number>;          // path -> scanner hit count
  coverage?: Record<string, FileCoverage>; // path -> coverage (after a run)
}

export function FileTree(props: Props) {
  const root = useMemo(() => buildTree(props.paths), [props.paths]);
  const allFiles = props.paths;
  const allSelected = allFiles.length > 0 && allFiles.every((f) => props.selected.has(f));

  const renderNode = (node: TreeNode, depth: number) => {
    const files = descendantFiles(root, node.path);
    const selectedCount = files.filter((f) => props.selected.has(f)).length;
    const checked = files.length > 0 && selectedCount === files.length;
    const indeterminate = selectedCount > 0 && selectedCount < files.length;
    const cov = props.coverage?.[node.path];
    const skipped = cov && !cov.agentReviewed;
    return (
      <div key={node.path || "root"}>
        <div className="tree-row" style={{ paddingLeft: depth * 14 }}>
          <input
            type="checkbox"
            checked={checked}
            ref={(el) => { if (el) el.indeterminate = indeterminate; }}
            onChange={() => props.onSelectedChange(togglePath(root, props.selected, node.path))}
            aria-label={`select ${node.path}`}
          />
          {node.isDir ? (
            <span className="tree-dir">{node.name}/</span>
          ) : (
            <button className={`tree-file ${props.active === node.path ? "active" : ""}`}
              onClick={() => props.onOpen(node.path)}>
              {node.name}
            </button>
          )}
          {props.hits?.[node.path] ? <span className="hit-badge">●{props.hits[node.path]}</span> : null}
          {skipped ? <span className="skip-tag">not deep-reviewed</span> : null}
        </div>
        {node.children.map((c) => renderNode(c, depth + 1))}
      </div>
    );
  };

  return (
    <div className="file-tree">
      <label className="tree-row select-all">
        <input type="checkbox" checked={allSelected}
          onChange={() => props.onSelectedChange(togglePath(root, props.selected, ""))}
          aria-label="select all" />
        <strong>Select all</strong>
      </label>
      {root.children.map((c) => renderNode(c, 0))}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm --filter web test -- --run src/components/fileTree.test.ts` then `pnpm --filter web exec tsc --noEmit`
Expected: PASS + no type errors.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/components/fileTree.ts apps/web/src/components/FileTree.tsx apps/web/src/components/fileTree.test.ts
git commit -m "feat(web): FileTree — tri-state checkboxes, select-all, dir-toggle, hit/skipped badges

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 17: Workspace three-pane + hook (multi-file, coverage banner, re-run)

**Files:**
- Modify: `apps/web/src/components/Workspace.tsx`, `apps/web/src/hooks/useReviewStream.ts`
- Modify: `apps/web/src/styles.css` (three-pane + tree styles)

- [ ] **Step 1: Update the hook**

Rewrite `apps/web/src/hooks/useReviewStream.ts` so `start` takes a `CreateReviewBody`, and add `rerun` + `load` (open an existing review by id):

```ts
import { useCallback, useRef, useState } from "react";
import { createReview, eventsUrl, getReview, rerunReview } from "../api/client";
import type { CreateReviewBody, ProgressEvent, ReviewResult } from "../api/types";

const TERMINAL = new Set(["done", "failed"]);

export function useReviewStream() {
  const [progress, setProgress] = useState<ProgressEvent | null>(null);
  const [result, setResult] = useState<ReviewResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reviewId, setReviewId] = useState<string | null>(null);
  const esRef = useRef<EventSource | null>(null);

  const stream = useCallback((id: string) => {
    setReviewId(id);
    const es = new EventSource(eventsUrl(id));
    esRef.current = es;
    let finished = false;
    const finish = async () => {
      if (finished) return;
      finished = true;
      es.close();
      const r = await getReview(id);
      setResult(r); setRunning(false);
      if (r.status === "failed") setError(r.error ?? "review failed");
    };
    es.addEventListener("progress", (e) => {
      const ev = JSON.parse((e as MessageEvent).data) as ProgressEvent;
      setProgress(ev);
      if (TERMINAL.has(ev.stage)) void finish();
    });
    es.addEventListener("complete", () => void finish());
    es.onerror = () => {
      if (finished) return;
      es.close(); setRunning(false); setError("connection lost");
    };
  }, []);

  const start = useCallback(async (body: CreateReviewBody) => {
    setProgress(null); setResult(null); setError(null); setRunning(true);
    try {
      stream(await createReview(body));
    } catch (err) {
      setRunning(false); setError(err instanceof Error ? err.message : "unknown error");
    }
  }, [stream]);

  const rerun = useCallback(async (id: string, marked: string[]) => {
    setProgress(null); setResult(null); setError(null); setRunning(true);
    try {
      stream(await rerunReview(id, marked));
    } catch (err) {
      setRunning(false); setError(err instanceof Error ? err.message : "unknown error");
    }
  }, [stream]);

  const load = useCallback(async (id: string) => {
    setProgress(null); setError(null); setRunning(false);
    setReviewId(id);
    setResult(await getReview(id));
  }, []);

  return { start, rerun, load, progress, result, running, error, reviewId };
}
```

- [ ] **Step 2: Rewrite Workspace as three-pane**

Rewrite `apps/web/src/components/Workspace.tsx`. It supports both authoring (paste/upload → mark → review) and viewing (a loaded past review). Key behaviors: build `files` from picker/drag/zip; left FileTree drives `marked`; center Monaco shows the active file (fetched via `getFile` when viewing, or from local memory when authoring); right shows findings for the active file; top banner shows coverage + Re-run.

```tsx
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Editor, { type OnMount } from "@monaco-editor/react";
import JSZip from "jszip";
import { useReviewStream } from "../hooks/useReviewStream";
import { getFile } from "../api/client";
import type { FileCoverage, FileInput, Finding } from "../api/types";
import { FileTree } from "./FileTree";
import { ProgressStepper } from "./ProgressStepper";
import { FindingCard } from "./FindingCard";

const SAMPLE: FileInput = {
  path: "snippet.py",
  content:
    'def get_user_data(user_id):\n    query = "SELECT * FROM users WHERE id = " + str(user_id)\n    cursor.execute(query)\n    return cursor.fetchall()\n',
  language: "python",
};
const EXT_LANG: Record<string, string> = { py: "python", ts: "typescript", tsx: "typescript", js: "javascript", java: "java" };
const langOf = (p: string) => EXT_LANG[p.split(".").pop() ?? ""] ?? "plaintext";

export function Workspace({ loadId }: { loadId?: string }) {
  const [files, setFiles] = useState<FileInput[]>([SAMPLE]);
  const [marked, setMarked] = useState<Set<string>>(new Set([SAMPLE.path]));
  const [active, setActive] = useState<string>(SAMPLE.path);
  const [viewContent, setViewContent] = useState<string | null>(null);
  const editorRef = useRef<Parameters<OnMount>[0] | null>(null);
  const { start, rerun, load, progress, result, running, error, reviewId } = useReviewStream();

  useEffect(() => { if (loadId) void load(loadId); }, [loadId, load]);

  // When viewing a loaded/finished review, fetch active file content from the server.
  useEffect(() => {
    if (!reviewId || !result) { setViewContent(null); return; }
    let on = true;
    void getFile(reviewId, active).then((c) => { if (on) setViewContent(c); }).catch(() => setViewContent(null));
    return () => { on = false; };
  }, [reviewId, result, active]);

  const localContent = useMemo(
    () => files.find((f) => f.path === active)?.content ?? "", [files, active]);
  const editorValue = result ? (viewContent ?? "") : localContent;

  const coverageByPath = useMemo<Record<string, FileCoverage>>(() => {
    const m: Record<string, FileCoverage> = {};
    result?.coverage?.files.forEach((c) => { m[c.path] = c; });
    return m;
  }, [result]);

  const hits = useMemo<Record<string, number>>(() => {
    const m: Record<string, number> = {};
    result?.findings.forEach((f) => {
      const file = f.location.file;
      if (file && f.sources.some((s) => s.type === "tool")) m[file] = (m[file] ?? 0) + 1;
    });
    return m;
  }, [result]);

  const allPaths = result?.coverage?.files.map((c) => c.path) ?? files.map((f) => f.path);
  const findingsForActive: Finding[] = (result?.findings ?? []).filter((f) => f.location.file === active);

  const onMount: OnMount = (editor) => { editorRef.current = editor; };
  const jumpTo = (line: number) => {
    const ed = editorRef.current;
    if (!ed) return;
    ed.revealLineInCenter(line); ed.setPosition({ lineNumber: line, column: 1 }); ed.focus();
  };

  const addFiles = useCallback(async (fileList: FileList) => {
    const next: FileInput[] = [];
    for (const f of Array.from(fileList)) {
      if (f.name.endsWith(".zip")) {
        const zip = await JSZip.loadAsync(f);
        for (const [path, entry] of Object.entries(zip.files)) {
          if (!entry.dir) next.push({ path, content: await entry.async("string"), language: langOf(path) });
        }
      } else {
        const rel = (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name;
        next.push({ path: rel, content: await f.text(), language: langOf(rel) });
      }
    }
    if (next.length) {
      setFiles(next);
      setMarked(new Set(next.map((f) => f.path)));
      setActive(next[0].path);
    }
  }, []);

  const review = () => start({ files, marked: [...marked] });

  return (
    <div className="workspace-3">
      <aside className="pane tree-pane">
        <div className="controls">
          <label className="upload-btn">
            Add files / folder
            <input type="file" multiple style={{ display: "none" }}
              // @ts-expect-error non-standard but widely supported
              webkitdirectory=""
              onChange={(e) => e.target.files && void addFiles(e.target.files)} />
          </label>
          <label className="upload-btn">
            Upload .zip
            <input type="file" accept=".zip" style={{ display: "none" }}
              onChange={(e) => e.target.files && void addFiles(e.target.files)} />
          </label>
        </div>
        <FileTree paths={allPaths} selected={marked} onSelectedChange={setMarked}
          active={active} onOpen={setActive} hits={hits} coverage={coverageByPath} />
      </aside>

      <section className="pane editor-pane">
        {result?.coverage && (
          <div className="coverage-banner">
            agents reviewed {result.coverage.filesAgentReviewed} / {result.coverage.filesTotal} ·
            scanners covered all {result.coverage.filesTotal}
            {reviewId && (
              <button className="rerun-btn" disabled={running}
                onClick={() => void rerun(reviewId, [...marked])}>Re-run ▶</button>
            )}
          </div>
        )}
        <div className="active-path">{active}</div>
        <Editor height="58vh" language={langOf(active)} theme="vs-dark" value={editorValue}
          onMount={onMount} options={{ minimap: { enabled: false }, fontSize: 13, readOnly: !!result }} />
        {!result && (
          <button className="review-btn" disabled={running} onClick={review}>
            {running ? "Reviewing…" : `Review ${marked.size} file(s) ▶`}
          </button>
        )}
      </section>

      <section className="pane findings-pane">
        <ProgressStepper progress={progress} />
        {error && <div className="error" role="alert">{error}</div>}
        {result && (
          <>
            <div className="summary">{result.summary}</div>
            {findingsForActive.length === 0 && <p>No findings in this file.</p>}
            {findingsForActive.map((f) => <FindingCard key={f.id} finding={f} onJump={jumpTo} />)}
          </>
        )}
      </section>
    </div>
  );
}
```

Add `jszip` to web deps: `pnpm --filter web add jszip`.

Also add two small spec items to this component:

- **Cost/time warning** near the Review button when the marked set is large. Read the ceiling from a constant (`const CEILING = 150;`) and render when `marked.size > 25`:

```tsx
{!result && marked.size > 25 && (
  <div className="cost-warning">
    {marked.size} files marked for deep review — this may be slow/expensive
    {marked.size > 150 ? " (over the limit; narrow your selection)" : ""}.
  </div>
)}
```

- **"Show all findings grouped by file" toggle** in the findings pane. Add `const [showAll, setShowAll] = useState(false);` and, when `showAll`, render every finding grouped by `location.file` instead of only `findingsForActive`:

```tsx
{result && (
  <label className="show-all">
    <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />
    Show all files
  </label>
)}
{result && showAll
  ? Object.entries(
      (result.findings ?? []).reduce<Record<string, Finding[]>>((acc, f) => {
        const k = f.location.file ?? "(unknown)";
        (acc[k] ??= []).push(f);
        return acc;
      }, {}),
    ).map(([file, fs]) => (
      <div key={file}>
        <div className="group-file">{file}</div>
        {fs.map((f) => <FindingCard key={f.id} finding={f} onJump={jumpTo} />)}
      </div>
    ))
  : null}
```

(Render the per-active-file list only when `!showAll`.)

- [ ] **Step 3: Add styles**

Append to `apps/web/src/styles.css`:

```css
.workspace-3 { display: grid; grid-template-columns: 240px 1fr 360px; gap: 12px; height: calc(100vh - 56px); padding: 12px; }
.tree-pane { overflow: auto; }
.file-tree { font-size: 13px; }
.tree-row { display: flex; align-items: center; gap: 6px; padding: 2px 4px; white-space: nowrap; }
.tree-row.select-all { border-bottom: 1px solid var(--border, #2a2f3a); margin-bottom: 6px; padding-bottom: 6px; }
.tree-dir { color: #9aa4b2; }
.tree-file { background: none; border: 0; color: #cdd3dc; cursor: pointer; padding: 0; }
.tree-file.active { color: #6ea8fe; font-weight: 600; }
.hit-badge { color: #ff6b6b; font-size: 11px; }
.skip-tag { color: #6b7280; font-size: 10px; font-style: italic; }
.coverage-banner { background: #15331f; color: #7ee2a8; padding: 6px 10px; border-radius: 6px; font-size: 12px; display: flex; align-items: center; gap: 10px; }
.rerun-btn { margin-left: auto; }
.active-path { font-family: monospace; font-size: 12px; color: #9aa4b2; padding: 4px 0; }
.upload-btn { display: inline-block; cursor: pointer; background: #222a38; padding: 4px 8px; border-radius: 6px; font-size: 12px; margin-right: 6px; }
.cost-warning { color: #ffb86b; font-size: 12px; margin: 6px 0; }
.show-all { display: flex; align-items: center; gap: 6px; font-size: 12px; margin-bottom: 8px; }
.group-file { font-family: monospace; font-size: 12px; color: #6ea8fe; margin: 8px 0 4px; }
```

- [ ] **Step 4: Verify**

Run: `pnpm --filter web exec tsc --noEmit` then `pnpm --filter web build`
Expected: no type errors; build succeeds.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/components/Workspace.tsx apps/web/src/hooks/useReviewStream.ts apps/web/src/styles.css apps/web/package.json
git commit -m "feat(web): three-pane multi-file workspace (tree + Monaco + per-file findings, re-run)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 18: History — clickable rows open a past review

**Files:**
- Modify: `apps/web/src/pages/HistoryPage.tsx`, `apps/web/src/App.tsx`

- [ ] **Step 1: Implement routing + clickable rows**

In `apps/web/src/App.tsx`, add a route that renders the workspace for a given id:

```tsx
import { Link, Route, Routes, useParams } from "react-router-dom";
import { Workspace } from "./components/Workspace";
import { HistoryPage } from "./pages/HistoryPage";
import { SettingsPage } from "./pages/SettingsPage";

function ReviewView() {
  const { id } = useParams();
  return <Workspace loadId={id} />;
}

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
        <Route path="/review/:id" element={<ReviewView />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Routes>
    </div>
  );
}
```

Rewrite `apps/web/src/pages/HistoryPage.tsx` so rows link to `/review/:id` and show `fileCount`:

```tsx
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { BASE } from "../api/client";
import type { ReviewResult } from "../api/types";

type Row = ReviewResult & { fileCount?: number };

export function HistoryPage() {
  const [items, setItems] = useState<Row[]>([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    fetch(`${BASE}/api/reviews`)
      .then((r) => r.json()).then(setItems)
      .catch(() => setItems([])).finally(() => setLoading(false));
  }, []);
  return (
    <div style={{ padding: 16 }}>
      <h2>Review History</h2>
      <table>
        <thead><tr><th>Language</th><th>Files</th><th>Status</th><th>Findings</th><th>Summary</th></tr></thead>
        <tbody>
          {items.map((r) => (
            <tr key={r.id}>
              <td><Link to={`/review/${r.id}`}>{r.language}</Link></td>
              <td>{r.fileCount ?? 0}</td>
              <td>{r.status}</td>
              <td>{r.findings.length}</td>
              <td>{r.summary}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {loading && <p>Loading…</p>}
      {!loading && items.length === 0 && <p>No reviews yet.</p>}
    </div>
  );
}
```

- [ ] **Step 2: Verify**

Run: `pnpm --filter web exec tsc --noEmit` then `pnpm --filter web build`
Expected: no type errors; build succeeds.

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/pages/HistoryPage.tsx apps/web/src/App.tsx
git commit -m "feat(web): clickable history rows open a past review in the three-pane view

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 19: Playwright e2e — multi-file + re-run + history

**Files:**
- Create: `apps/web/e2e/multifile.spec.ts` (read an existing e2e spec first to match config/fixtures: base URL, how the API is started, selectors)

- [ ] **Step 1: Write the e2e spec**

Create `apps/web/e2e/multifile.spec.ts` (adapt selectors/setup to the existing e2e harness — this is the intended flow):

```ts
import { test, expect } from "@playwright/test";

// Assumes the e2e harness starts the API (ADC_BACKEND=memory, ADC_SCANNERS="") and the web app,
// matching the existing e2e config. Adjust the file-upload helper to your harness.
test("multi-file review groups findings by file and supports re-run", async ({ page }) => {
  await page.goto("/");

  // Upload two files via the hidden folder input.
  const input = page.locator('input[type="file"]').first();
  await input.setInputFiles([
    { name: "auth.py", mimeType: "text/x-python",
      buffer: Buffer.from('q = "SELECT * FROM users WHERE id=" + uid\ncursor.execute(q)\n') },
    { name: "util.py", mimeType: "text/x-python", buffer: Buffer.from("x = 1\n") },
  ]);

  await page.getByRole("button", { name: /Review .* file/ }).click();

  // Coverage banner appears when done.
  await expect(page.locator(".coverage-banner")).toBeVisible({ timeout: 30_000 });

  // Open auth.py and see its finding.
  await page.getByRole("button", { name: "auth.py" }).click();
  await expect(page.locator(".finding-card").first()).toBeVisible();

  // Re-run is available.
  await expect(page.getByRole("button", { name: /Re-run/ })).toBeVisible();
});
```

- [ ] **Step 2: Run e2e**

Run the project's e2e command (e.g. `pnpm --filter web e2e` or per the existing harness).
Expected: PASS. If the harness needs the API up, start it with `ADC_BACKEND=memory ADC_SCANNERS=""` first (matching existing e2e setup).

- [ ] **Step 3: Commit**

```bash
git add apps/web/e2e/multifile.spec.ts
git commit -m "test(web): e2e — multi-file review groups by file + re-run available

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 20: Docs, env, credits

**Files:**
- Modify: `README.md`, `AGENTS.md`, `.env.example` (if present), `CREDITS.md`, `docs/tech-debt.md`

- [ ] **Step 1: Update docs**

- `README.md`: update the "How it works" mermaid + feature list for multi-file (two-tier review, coverage, re-run, History reloads files). Document new env vars (`ADC_AGENT_FILE_CAP`, `ADC_AGENT_FILE_CEILING`, `ADC_FILE_CONCURRENCY`, `ADC_MAX_FILES`, `ADC_MAX_TOTAL_BYTES`, `ADC_MAX_FILE_BYTES`, `ADC_IGNORE_GLOBS`, `ADC_WORK_ROOT`).
- `AGENTS.md`: note the corpus pipeline + that `ADC_WORK_ROOT` must be a shared volume between API and worker in the infra backend.
- `.env.example` (if it exists): add the new vars with defaults.
- `CREDITS.md`: add **JSZip** (browser-side zip unzip).
- `docs/tech-debt.md`: add "work-dir retention has no TTL/cleanup yet" and "scanner findings categorized `security` by default."

- [ ] **Step 2: Verify infra**

If `docker-compose.yml` mounts volumes, ensure `ADC_WORK_ROOT` points to a volume shared by the `api` and `worker` services (add the mount if missing). Confirm `task` targets still reference valid commands.

- [ ] **Step 3: Commit**

```bash
git add README.md AGENTS.md CREDITS.md docs/tech-debt.md .env.example docker-compose.yml
git commit -m "docs: multi-file review — how-it-works, env vars, JSZip credit, work-dir retention debt

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 21: Final verification + PR

- [ ] **Step 1: Full backend suite + lint**

Run: `uv run pytest packages/core apps/api -q && uv run ruff check .`
Expected: all pass; `All checks passed!`

- [ ] **Step 2: Full frontend checks**

Run: `pnpm --filter web test -- --run && pnpm --filter web exec tsc --noEmit && pnpm --filter web build`
Expected: all green.

- [ ] **Step 3: Real local smoke (optional but recommended)**

With `.env` configured (OpenAI key, `ADC_SCANNERS=semgrep,bandit`), start the API + worker, upload a small 2-file Python repo (one with a SQLi), confirm: SQLi card on that file cited by agents + bandit/semgrep; coverage banner correct; a skipped file shows the tag; Re-run with it marked promotes it to reviewed.

- [ ] **Step 4: Branch + push + PR**

```bash
git push -u origin <feature-branch>
gh pr create --title "Multi-file review (Piece A): two-tier codebase review + coverage + re-run + history" --body "$(cat <<'EOF'
## Summary
- Ingest a whole codebase (files[]/folder/zip) → per-review corpus on disk.
- Two-tier review: scanners cover every file; agents deep-review marked ∪ scanner-hit (capped/ceilinged), per-file fan-out under a concurrency semaphore.
- File-aware aggregation; findings carry location.file; coverage report + skipped-file surfacing.
- Mark-and-re-run loop (reuses the work dir); History reloads a past review's files + report.

## Test Plan
- [ ] uv run pytest packages/core apps/api -q
- [ ] uv run ruff check .
- [ ] pnpm --filter web test / tsc --noEmit / build
- [ ] Playwright e2e (multi-file + re-run)
- [ ] Manual smoke: 2-file repo, SQLi cited by agents + scanners, re-run promotes a skipped file

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Notes for the executor

- **Per-file syntax** findings are produced only for agent-set files (the depth tier); scanners cover breadth. This is intentional.
- **Why the per-file graph is agents-only:** scanners run once over the whole corpus dir in `ReviewService._scan_corpus`; the LangGraph fan-out is reused per file purely for the 6 agents + the `failures` channel. The single final `aggregate(...)` merges scanner findings into agent findings within each file.
- **Shared work root (infra backend):** API and arq worker are separate processes — they must point `ADC_WORK_ROOT` at the same path/volume so the worker can read the corpus the API wrote.
- **Backward compatibility:** legacy `{code, language}` still works (normalized to a 1-file corpus, auto-marked); the existing 422-on-unsupported-language behavior is preserved via `validate_submission` on that branch.
