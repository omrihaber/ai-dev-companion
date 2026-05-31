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
