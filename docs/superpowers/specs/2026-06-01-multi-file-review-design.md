# Multi-File Review (Piece A of "multi-file + retrieval") — Design Spec

**Date:** 2026-06-01
**Status:** Approved (brainstorm) — pending implementation plan
**Builds on:** Inc 0–3 + Inc 5 (SARIF scanners), all merged to `main`
**Repo:** https://github.com/omrihaber/ai-dev-companion

---

## 1. Overview

Generalize review from a **single snippet** to a **whole codebase**. The user uploads many files (a
dropped folder or a `.zip`); the system reviews them with a **two-tier** strategy:

- **Scanner tier (breadth):** Semgrep/Bandit run **once over the whole corpus** — cheap, fast, scales to
  hundreds of files. Every ingested file is statically scanned.
- **Agent tier (depth):** the 6 LLM specialist agents deep-review a **bounded, prioritized subset** —
  the files the user **marked** ∪ the files **scanners flagged** — because a full 6-agent fan-out over
  hundreds of files is too slow/expensive (and cross-file context needs retrieval, which is the *next*
  increment, Piece B).

The result reports **coverage** ("agents reviewed N of M files; scanners covered all M") and, crucially,
flags which files were **skipped** so the user can mark the relevant ones and **re-run** for depth — an
iterative breadth→depth loop. Findings now carry their **file path**; the existing multi-source
aggregator merges **per file**, so a SQL injection in `auth.py` cited by `security-agent`+`bandit` still
collapses into one card, while an unrelated issue in `db.py` stays separate.

This is **Piece A** of the "multi-file + retrieval" increment. **Piece B** (pgvector embeddings +
cross-file retrieval context + retrieval-driven file selection) is a separate, follow-on spec.

### Guiding principles
- **One normalized shape** — every transport (JSON `files[]`, server-side zip) becomes a `Corpus`.
- **Reuse the seams** — scanners already mount a directory; the aggregator already unions `sources[]`; the
  `failures` channel + arq queue already exist. Multi-file extends them, it does not replace them.
- **Honest coverage** — never imply the agents read everything; show exactly what got the deep treatment.
- **Iterative** — surface skipped files; let the user mark + re-run cheaply (reuse the persisted corpus).
- **Single-snippet still works** — `{code, language}` normalizes to a 1-file corpus (full backward compat).
- **Bounded everything** — file counts, byte sizes, agent-set size, and concurrency are all capped/config.

---

## 2. Ingestion → Corpus

A **`Corpus`** is a list of `CorpusFile{path, content, language}` materialized into a **per-review work
dir** on disk (`<work_root>/<review_id>/`), used by scanners (mounted read-only), by the agent tier, by
the file-content endpoint, and by re-runs.

### 2.1 Transports
- **JSON** on the existing `POST /api/reviews`: `files: [{path, content, language?}]`.
- **Multipart** `POST /api/reviews/zip`: a `.zip`, unzipped server-side, for **non-browser / API / CLI**
  clients.
- **Browser**: a dropped **folder** (`webkitdirectory`, gives relative path + content per file) **and** a
  dropped **`.zip`** (unzipped client-side via JSZip) are both normalized to `files[]` — so the browser
  always uses the one JSON contract; the server zip endpoint exists for non-browser clients.

### 2.2 Normalization + safety (shared by all transports)
- **Path safety (zip):** reject entries containing `..`, absolute paths, or symlinks; flatten to repo-relative.
- **Caps:** `ADC_MAX_FILES` (default 2000), `ADC_MAX_TOTAL_BYTES` (default 50 MB uncompressed),
  `ADC_MAX_FILE_BYTES` (default 512 KB). Exceeding any cap → ingestion rejected (HTTP 413/422) with a clear
  message; **no review is created**. (Guards against zip bombs.)
- **Ignore denylist** (`ADC_IGNORE_GLOBS`, sensible default): `.git/`, `node_modules/`, `dist/`, `build/`,
  `vendor/`, `__pycache__/`, `*.lock`, lockfiles, and binary/non-UTF-8 files are dropped before review so
  "review my repo" never reviews dependencies.
- **Language** is inferred per file from its extension (reusing the existing language map); files of unknown
  language are still ingested (scanners gate themselves by language; agents get the raw text).
- **Single snippet:** a request with `{code, language}` and no `files[]` becomes a 1-file corpus
  (`snippet.<ext>`), `marked = [that file]`.

---

## 3. Two-tier review pipeline

```
ingest → Corpus (work dir)
  │
  ├─ SCANNER TIER (breadth): each scanner runs ONCE over the work dir → findings for every file
  │                          (Finding.location.file populated from the SARIF artifact uri)
  │
  ├─ BUILD AGENT SET: agent_set = marked ∪ scanner_hit_files
  │     • priority order: marked first, then scanner-hit by descending severity
  │     • cap at ADC_AGENT_FILE_CAP (default 25)
  │     • explicit marks OVERRIDE the cap, up to a hard ADC_AGENT_FILE_CEILING (default 150);
  │       a request whose marks exceed the ceiling is rejected ("narrow your selection")
  │     • fallback: if agent_set is empty (nothing marked, nothing flagged) → first N source files
  │
  ├─ AGENT TIER (depth): for each file in agent_set → the existing 6-agent fan-out on that file
  │                      bounded concurrency = ADC_FILE_CONCURRENCY (default 4 files in flight)
  │
  └─ AGGREGATE (file-aware) → coverage → persist (ReviewRepository) → emit "done"
```

### 3.1 Orchestration
`ReviewService` becomes corpus-aware:
1. Run scanners over the work dir (one invocation per scanner over the directory — the Inc 5 spec named
   this the trivial generalization of the existing dir mount). Collect scanner findings (with file paths).
2. Compute `agent_set` (above).
3. For each file in `agent_set`, run the **agent fan-out** (reuse the existing LangGraph agent nodes,
   scanners excluded from the per-file graph since they ran once already), gated by an
   `asyncio.Semaphore(ADC_FILE_CONCURRENCY)`. Per-file failures are recorded in the existing `failures`
   channel and never sink the run.
4. **Aggregate** all findings (scanner + per-file agent) **file-aware**.
5. Build the **coverage** report; persist; emit terminal status.

The whole review runs as one **arq-queued** job (Inc 3) — appropriate for long large-repo reviews — with
the inline path used by the memory backend.

### 3.2 File-aware aggregation
The existing aggregator (merge by location-overlap + title-similarity, union `sources[]`, max severity,
representative category) gains **file path as part of the merge identity**: two findings merge only if they
are on the **same `location.file`**. Result: same-file multi-source findings still collapse to one
multi-source card; identical issues in different files remain distinct cards.

### 3.3 All-failure semantics (reuse Inc 5)
If **every** agent invocation across **every** file in `agent_set` fails (e.g. bad API key), the review is
`failed` with an actionable error — not a misleading empty `done`. A single file's or single agent's
failure degrades gracefully (that file/agent contributes nothing).

---

## 4. Re-run loop (breadth → depth)

After a run, **every corpus file** carries an agent-review status:
- `reviewed` — reason `marked`, `scanner-hit`, or `fallback`
- `skipped` — reason `not-flagged` or `over-cap`

The UI surfaces skipped files (muted "not deep-reviewed" tag + a checkbox). The user marks the relevant
ones and triggers **`POST /api/reviews/{id}/rerun { marked: [paths] }`**, which **reuses the persisted work
dir** (no re-upload) and creates a **new, linked review** (`parent_review_id`) with the updated marks. This
is the iterative cycle: scanners flag breadth → user sees skipped files → marks → re-runs for depth.

---

## 5. Data model & API

### 5.1 Schema (`adc_core.models`, camelCase via existing alias generator)
- `FileInput { path: str, content: str, language: str | None }`.
- `ReviewRequest`: add `files: list[FileInput] = []` and `marked: list[str] = []`; keep `code`/`language`
  (normalized to a 1-file corpus when `files` is empty).
- `Finding.location.file` — already in the schema — is now **populated** for all findings (agents get the
  file path of the file under review; scanners map it from the SARIF artifact `uri`).
- `FileCoverage { path: str, agentReviewed: bool, reason: "marked"|"scanner-hit"|"fallback"|"not-flagged"|"over-cap" }`
  (`reviewed` ⇒ `marked`/`scanner-hit`/`fallback`; `skipped` ⇒ `not-flagged`/`over-cap`).
- `ReviewResult`: add `coverage: { filesTotal: int, filesAgentReviewed: int, files: list[FileCoverage] }`
  and `parentReviewId: str | None`.

### 5.2 Endpoints
- `POST /api/reviews` — accepts the extended JSON (`files[]` + `marked[]`) **or** the legacy `{code,language}`.
- `POST /api/reviews/zip` — multipart `.zip` (server-side unzip + hardening) → same pipeline.
- `POST /api/reviews/{id}/rerun` — `{ marked: [paths] }`; reuses the work dir; returns a new linked review.
- `GET /api/reviews/{id}/file?path=…` — returns one file's content (from the work dir) for the editor;
  rejects paths escaping the work dir.
- `GET /api/reviews/{id}` and the SSE stream — unchanged shape aside from the new `coverage` field.

### 5.3 Persistence
- Corpus files persist on disk under the per-review work dir (serves file content **and** powers re-runs).
- Findings + coverage persist via the existing `ReviewRepository` (SQL/JSONB or in-memory).

### 5.4 Configuration (new env)
`ADC_AGENT_FILE_CAP` (25), `ADC_AGENT_FILE_CEILING` (150), `ADC_FILE_CONCURRENCY` (4),
`ADC_MAX_FILES` (2000), `ADC_MAX_TOTAL_BYTES` (50 MB), `ADC_MAX_FILE_BYTES` (512 KB),
`ADC_IGNORE_GLOBS` (default denylist above), `ADC_WORK_ROOT` (work-dir base path).

---

## 6. Progress model (SSE)

Stages unchanged: `queued → validating → analyzing → finalizing → done | failed`. During `analyzing`,
`sub_status` reports **bounded** progress — `{ scan: "running"|"done", filesReviewed: n, filesTotal: m }` —
**not** per-agent-per-file (which would explode for hundreds of files). The stepper renders
"Scanning… / Reviewing files 12 of 25."

---

## 7. Frontend (three-pane, extends today's app)

- **Left — File tree** built from `files[]` paths: tri-state checkboxes (checking a folder marks all
  descendants; clicking again clears; partial = indeterminate) + a **select-all** at the root. Per-file
  scanner-hit badge (`●3`) once results arrive; after a run, **skipped** files show a muted
  "not deep-reviewed" tag, and their checkbox is the mark-for-rerun control.
- **Center — Monaco editor** for the selected file, with findings rendered as inline markers (squiggles)
  at their lines; content from `GET /api/reviews/{id}/file?path=…` (or client memory on first submit).
- **Right — Findings panel**: findings for the selected file (existing multi-source chip cards), with a
  toggle to show **all** findings grouped by file.
- **Top — Coverage banner**: "agents reviewed N / M · scanners covered all M" + a **Re-run** button
  (enabled when the marked set changed).
- A **cost/time warning** appears when the marked set is large (approaching the ceiling).

---

## 8. Error handling

- **Ingestion**: over a cap / zip bomb / path traversal / all-binary → reject with a clear message; no
  review created.
- **Per-file agent failure**: that file's findings empty + recorded in `failures`; never sinks the run.
- **All agents failed across all files** → `failed` with an actionable error (reuse Inc 5 logic).
- **Scanner unavailable** (no Docker / `ADC_SCANNERS=""`): scanners contribute nothing; agents still run
  on the marked set (today's graceful degradation). With no scanner hits, the agent set is marks ∪ fallback.
- **File-content endpoint**: a `path` escaping the work dir → 400.

---

## 9. Testing

- **Unit:** ingestion normalization (files[] + zip → corpus; ignore denylist; caps; path-traversal reject);
  agent-set selection (marks ∪ hits; cap; ceiling reject; empty→fallback); **file-aware aggregation**
  (same SQLi in two files → two cards; same file, two agents → one merged multi-source card); coverage /
  skipped-status computation.
- **API (Docker-free, `ADC_SCANNERS=""`):** multi-file review end-to-end → findings carry `file`, coverage
  correct, skipped files flagged; `rerun` reuses the work dir with new marks and links `parentReviewId`;
  `file?path=` returns content and rejects traversal.
- **Gated integration (Docker):** real Semgrep/Bandit over a small multi-file repo → scanner findings land
  on the right files; self-skips if `docker version` fails.
- **Frontend:** tree tri-state / select-all / dir-toggle (vitest); Playwright e2e — upload a 2-file folder,
  run, see findings grouped by file, mark a skipped file, re-run, see it become reviewed.
- Determinism rule holds (assert schema / sources / coverage, not exact model wording).

---

## 10. Out of scope (→ Piece B, next increment)

- **pgvector embeddings + cross-file retrieval context** injected into agent prompts.
- **Retrieval-driven agent file selection** (smarter than scanner-hit ∪ marks).
- An embeddings method on the `ModelProvider` seam (Ollama `/api/embeddings` + OpenAI embeddings).
- Git ingestion (clone a repo/branch/commit), webhooks/CI triggers — separate increment.
- SonarQube / CodeRabbit adapters; per-rule scanner category refinement.

---

## 11. Known limitations

- Large repos get **whole-repo scanner coverage** but only **bounded agent depth** (by design, until
  Piece B's retrieval enables smarter, broader agent selection). Coverage is reported honestly.
- The work dir persists per review; cleanup/retention policy is left simple (best-effort; a TTL/cleanup
  job is deferred).
- Client-side zip unzip (browser) is bounded by browser memory; very large zips should use the server
  `POST /api/reviews/zip` endpoint.
- Per-file agent fan-out cost scales with the marked set; the cap/ceiling + cost warning bound it.
