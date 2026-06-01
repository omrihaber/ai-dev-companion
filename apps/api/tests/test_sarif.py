from adc_api.scanners.sarif import sarif_to_findings

SEMGREP_SARIF = {
    "runs": [{
        "tool": {"driver": {"name": "semgrep", "rules": [{
            "id": "python.sqli",
            # Semgrep's real shortDescription is a generic placeholder — must NOT become the title.
            "shortDescription": {"text": "Semgrep Finding: python.sqli"},
            "helpUri": "https://semgrep.dev/r/python.sqli",
            "help": {"text": "Use parameterized queries."},
            "properties": {"security-severity": "8.0"},
        }]}},
        "results": [{
            "ruleId": "python.sqli",
            "level": "error",
            "message": {"text": "Detected SQL injection from untrusted input"},
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
    assert "SQL injection" in f.title                 # title from the message...
    assert not f.title.lower().startswith("semgrep finding")  # ...not the generic shortDescription
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


def test_maps_artifact_uri_to_location_file():
    findings = sarif_to_findings(SEMGREP_SARIF, "semgrep")
    assert findings[0].location.file == "snippet.py"


def test_strips_leading_dot_slash_from_file():
    sarif = {
        "runs": [{
            "tool": {"driver": {"rules": []}},
            "results": [{
                "ruleId": "x", "level": "error", "message": {"text": "bad"},
                "locations": [{"physicalLocation": {
                    "artifactLocation": {"uri": "./app/db.py"},
                    "region": {"startLine": 3, "endLine": 3},
                }}],
            }],
        }]
    }
    assert sarif_to_findings(sarif, "bandit")[0].location.file == "app/db.py"
