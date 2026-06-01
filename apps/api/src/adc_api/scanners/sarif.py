from __future__ import annotations

import uuid

from adc_core.models import Finding, Location, Severity, Source

_LEVEL: dict[str, Severity] = {"error": "high", "warning": "medium", "note": "low", "none": "low"}


def _severity(result: dict, rule: dict) -> Severity:
    sec = rule.get("properties", {}).get("security-severity")
    if sec is not None:
        try:
            v = float(sec)
        except (TypeError, ValueError):
            v = None
        if v is not None:
            if v >= 9.0:
                return "critical"
            if v >= 7.0:
                return "high"
            if v >= 4.0:
                return "medium"
            return "low"
    return _LEVEL.get(result.get("level", "warning"), "medium")


def _region(result: dict) -> dict | None:
    for loc in result.get("locations", []):
        region = loc.get("physicalLocation", {}).get("region")
        if region and region.get("startLine"):
            return region
    return None


def sarif_to_findings(sarif: dict, scanner_name: str) -> list[Finding]:
    findings: list[Finding] = []
    for run in sarif.get("runs", []):
        rules = {
            r.get("id"): r
            for r in run.get("tool", {}).get("driver", {}).get("rules", [])
        }
        for result in run.get("results", []):
            region = _region(result)
            if region is None:
                continue
            rule = rules.get(result.get("ruleId"), {})
            message = (result.get("message", {}).get("text") or "").strip()
            title = rule.get("shortDescription", {}).get("text") or message or "Scanner finding"
            recommendation = (
                rule.get("help", {}).get("text")
                or rule.get("fullDescription", {}).get("text")
                or "Review and remediate per the rule."
            )
            findings.append(
                Finding(
                    id=str(uuid.uuid4()),
                    category="security",
                    severity=_severity(result, rule),
                    title=title.split("\n")[0][:120],
                    description=message or title,
                    recommendation=recommendation,
                    location=Location(
                        start_line=region["startLine"],
                        end_line=region.get("endLine", region["startLine"]),
                        start_col=region.get("startColumn"),
                        end_col=region.get("endColumn"),
                    ),
                    sources=[Source(
                        type="tool",
                        name=scanner_name,
                        rule_id=result.get("ruleId"),
                        url=rule.get("helpUri"),
                    )],
                )
            )
    return findings
