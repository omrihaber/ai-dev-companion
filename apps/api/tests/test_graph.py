import pytest
from adc_api.agents import SpecialistAgent
from adc_api.graph import build_graph
from adc_api.providers import MockProvider
from adc_core.models import Finding, Location, Source


def _agent(name, cat, sev, provider=None):
    return SpecialistAgent(
        name=name, category=cat, system_prompt="s",
        provider=provider or MockProvider(seed=[{
            "category": cat, "severity": sev, "title": cat, "description": "d",
            "recommendation": "r", "start_line": 5, "end_line": 5,
        }]),
    )


def _syntax():
    return Finding(
        id="s", category="syntax", severity="high", title="Syntax error", description="d",
        recommendation="r", location=Location(start_line=1, end_line=1),
        sources=[Source(type="tool", name="tree-sitter")],
    )


@pytest.mark.asyncio
async def test_graph_runs_specialists_and_aggregates_with_syntax_seeded():
    graph = build_graph([_agent("security-agent", "security", "critical"),
                         _agent("quality-agent", "quality", "low")])
    out = await graph.ainvoke(
        {"code": "x", "language": "python", "findings": [_syntax()], "result": []}
    )
    res = out["result"]
    cats = [f.category for f in res]
    assert {"security", "quality", "syntax"} <= set(cats)
    assert cats[0] == "security"  # critical ranked first
    assert next(f for f in res if f.category == "security").sources[0].name == "security-agent"


@pytest.mark.asyncio
async def test_failing_agent_is_isolated_review_still_aggregates():
    class Boom(MockProvider):
        async def complete_structured(self, **kw):
            raise RuntimeError("agent down")
    graph = build_graph([_agent("security-agent", "security", "high", provider=Boom()),
                         _agent("quality-agent", "quality", "low")])
    out = await graph.ainvoke({"code": "x", "language": "python", "findings": [], "result": []})
    cats = [f.category for f in out["result"]]
    assert "quality" in cats and "security" not in cats  # failed agent contributed nothing


class _FakeScanner:
    name = "semgrep"
    languages = {"python"}

    def __init__(self, findings):
        self._findings = findings

    async def scan(self, code, language):
        return self._findings


@pytest.mark.asyncio
async def test_scanner_finding_merges_with_agent_finding_into_one_citation():
    from adc_api.agents import SpecialistAgent
    from adc_api.providers import MockProvider

    agent = SpecialistAgent(
        name="security-agent", category="security", system_prompt="s",
        provider=MockProvider(seed=[{
            "category": "security", "severity": "high", "title": "SQL Injection",
            "description": "d", "recommendation": "r", "start_line": 2, "end_line": 2,
        }]),
    )
    scanner_finding = Finding(
        id="sg", category="security", severity="critical", title="SQL Injection Vulnerability",
        description="d", recommendation="r", location=Location(start_line=2, end_line=2),
        sources=[Source(type="tool", name="semgrep", rule_id="python.sqli", url="https://x")],
    )
    graph = build_graph([agent], [_FakeScanner([scanner_finding])])
    out = await graph.ainvoke(
        {"code": "q='..'+uid", "language": "python", "findings": [], "result": []}
    )

    security = [f for f in out["result"] if f.category == "security"]
    assert len(security) == 1  # agent + scanner merged into ONE card
    assert {s.name for s in security[0].sources} == {"security-agent", "semgrep"}
    assert security[0].severity == "critical"  # max severity across merged sources
