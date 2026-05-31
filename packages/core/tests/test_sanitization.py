import pytest
from adc_core.sanitization import LANGUAGES, SubmissionError, validate_submission


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
