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
    tree = parser.parse(code)
    findings: list[Finding] = []

    def visit(node) -> None:
        if node.is_error() or node.is_missing():
            start = node.start_position()
            end = node.end_position()
            findings.append(
                Finding(
                    id=str(uuid.uuid4()),
                    category="syntax",
                    severity="high",
                    title="Syntax error",
                    description=f"Parser could not parse this region ({node.kind()}).",
                    recommendation="Fix the syntax error so the code parses.",
                    location=Location(
                        start_line=start.row + 1,
                        end_line=end.row + 1,
                        start_col=start.column,
                        end_col=end.column,
                    ),
                    sources=[Source(type="tool", name="tree-sitter")],
                )
            )
        for i in range(node.child_count()):
            visit(node.child(i))

    visit(tree.root_node())
    return findings
