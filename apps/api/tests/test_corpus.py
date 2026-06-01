import io
import zipfile

import pytest
from adc_api.corpus import IngestError, ingest_files, ingest_zip


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
