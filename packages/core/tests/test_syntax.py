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
