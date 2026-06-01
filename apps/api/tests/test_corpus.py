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


def test_ingest_files_drops_dotgit_and_strips_dot_slash_prefix():
    out = ingest_files([
        {"path": ".git/config", "content": "secret"},
        {"path": "./app/main.py", "content": "x=1\n"},
    ])
    paths = [f.path for f in out]
    assert paths == ["app/main.py"]           # .git/* ignored; leading ./ stripped exactly


def test_ingest_zip_rejects_bad_archive():
    with pytest.raises(IngestError):
        ingest_zip(b"not a zip")


def test_ingest_zip_rejects_absolute_path():
    data = _zip_bytes({"/etc/passwd": "x"})
    with pytest.raises(IngestError):
        ingest_zip(data)


def test_ingest_zip_skips_oversized_entry():
    data = _zip_bytes({"big.py": "x" * 5000, "ok.py": "y = 1\n"})
    out = ingest_zip(data, max_file_bytes=1000)
    assert [f.path for f in out] == ["ok.py"]


def test_ingest_files_rejects_over_file_count_short_circuits():
    files = [{"path": f"f{i}.py", "content": "x=1"} for i in range(5)]
    with pytest.raises(IngestError):
        ingest_files(files, max_files=2)


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


def test_corpus_store_rejects_bad_review_id(tmp_path):
    from adc_api.corpus import CorpusStore

    store = CorpusStore(str(tmp_path))
    with pytest.raises(IngestError):
        store.path("../escape")
