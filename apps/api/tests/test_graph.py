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
