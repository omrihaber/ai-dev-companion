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
    max_files=None,
    max_total_bytes=None,
    max_file_bytes=None,
    ignore_globs=None,
) -> list[CorpusFile]:
    raw = [(f["path"], f.get("content", "")) for f in files]
    return _normalize(raw, **_caps(max_files, max_total_bytes, max_file_bytes, ignore_globs))


def ingest_zip(
    data: bytes,
    *,
    max_files=None,
    max_total_bytes=None,
    max_file_bytes=None,
    ignore_globs=None,
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
