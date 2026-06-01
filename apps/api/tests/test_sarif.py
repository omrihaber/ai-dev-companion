from adc_api.scanners.sarif import sarif_to_findings

SEMGREP_SARIF = {
    "runs": [{
        "tool": {"driver": {"name": "semgrep", "rules": [{
            "id": "python.sqli",
            "shortDescription": {"text": "SQL injection"},
            "helpUri": "https://semgrep.dev/r/python.sqli",
            "help": {"text": "Use parameterized queries."},
            "properties": {"security-severity": "8.0"},
        }]}},
        "results": [{
            "ruleId": "python.sqli",
            "level": "error",
            "message": {"text": "Detected SQL injection"},
            "locations": [{"physicalLocation": {
                "artifactLocation": {"uri": "snippet.py"},
                "region": {"startLine": 2, "endLine": 2, "startColumn": 5, "endColumn": 40},
            }}],
        }],
    }]
}

BANDIT_SARIF = {
    "runs": [{
        "tool": {"driver": {"name": "Bandit", "rules": [{
            "id": "B608", "name": "hardcoded_sql_expressions",
            "helpUri": "https://bandit.readthedocs.io/en/latest/plugins/b608.html",
        }]}},
        "results": [{
            "ruleId": "B608", "level": "warning",
            "message": {
                "text": "Possible SQL injection vector through string-based query construction.",
            },
            "locations": [{"physicalLocation": {
                "artifactLocation": {"uri": "snippet.py"}, "region": {"startLine": 2, "endLine": 2},
            }}],
        }],
    }]
}


def test_maps_semgrep_result_with_sources_and_severity():
    findings = sarif_to_findings(SEMGREP_SARIF, "semgrep")
    assert len(findings) == 1
    f = findings[0]
    assert f.category == "security"
    assert f.severity == "high"               # security-severity 8.0 -> high
    assert f.location.start_line == 2
    assert "SQL injection" in f.title
    src = f.sources[0]
    assert src.type == "tool" and src.name == "semgrep"
    assert src.rule_id == "python.sqli"
    assert src.url == "https://semgrep.dev/r/python.sqli"


def test_maps_bandit_result_level_to_severity():
    findings = sarif_to_findings(BANDIT_SARIF, "bandit")
    assert len(findings) == 1
    f = findings[0]
    assert f.severity == "medium"             # level "warning" -> medium
    assert f.sources[0].name == "bandit" and f.sources[0].rule_id == "B608"


def test_skips_results_without_a_location():
    sarif = {"runs": [{
        "tool": {"driver": {"rules": []}},
        "results": [{"ruleId": "x", "level": "error", "message": {"text": "no loc"}}],
    }]}
    assert sarif_to_findings(sarif, "semgrep") == []
