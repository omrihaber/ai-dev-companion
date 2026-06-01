from __future__ import annotations

import fnmatch
import io
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path

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
    return any(
        fnmatch.fnmatch(path, g) or fnmatch.fnmatch(path.split("/")[-1], g)
        for g in globs
    )


def _normalize(
    raw: list[tuple[str, str]],  # (path, content)
    *, max_files: int, max_total_bytes: int, max_file_bytes: int, ignore_globs: list[str],
) -> list[CorpusFile]:
    out: list[CorpusFile] = []
    total = 0
    for path, content in raw:
        path = path.removeprefix("./").replace("\\", "/")
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
            raise IngestError(f"submission has more than {max_files} files; max is {max_files}")
    if not out:
        raise IngestError("no reviewable files after applying the ignore rules")
    return out


def _caps(
    max_files: int | None,
    max_total_bytes: int | None,
    max_file_bytes: int | None,
    ignore_globs: str | None,
) -> dict:
    return dict(
        max_files=max_files if max_files is not None else settings.max_files,
        max_total_bytes=(
            max_total_bytes if max_total_bytes is not None else settings.max_total_bytes
        ),
        max_file_bytes=max_file_bytes if max_file_bytes is not None else settings.max_file_bytes,
        ignore_globs=[
            g.strip()
            for g in (ignore_globs or settings.ignore_globs).split(",")
            if g.strip()
        ],
    )


def ingest_files(
    files: list[dict],
    *,
    max_files: int | None = None,
    max_total_bytes: int | None = None,
    max_file_bytes: int | None = None,
    ignore_globs: str | None = None,
) -> list[CorpusFile]:
    raw = [(f["path"], f.get("content", "")) for f in files]
    return _normalize(raw, **_caps(max_files, max_total_bytes, max_file_bytes, ignore_globs))


def ingest_zip(
    data: bytes,
    *,
    max_files: int | None = None,
    max_total_bytes: int | None = None,
    max_file_bytes: int | None = None,
    ignore_globs: str | None = None,
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
            cap = max_file_bytes if max_file_bytes is not None else settings.max_file_bytes
            try:
                with zf.open(info) as fh:
                    blob = fh.read(cap + 1)  # bounded: never decompress more than cap+1 bytes
            except (OSError, zipfile.BadZipFile):
                continue
            if len(blob) > cap:
                continue  # oversized / decompression bomb: skip (consistent with ingest_files)
            try:
                content = blob.decode("utf-8")
            except UnicodeDecodeError:
                continue  # binary / unreadable: skip
            raw.append((name, content))
    return _normalize(raw, **_caps(max_files, max_total_bytes, max_file_bytes, ignore_globs))


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
