import pytest
from adc_api.agents import SpecialistAgent, build_agents
from adc_api.providers import MockProvider


@pytest.mark.asyncio
async def test_agent_forces_its_category_and_sets_source():
    agent = SpecialistAgent(
        name="security-agent", category="security", system_prompt="s",
        provider=MockProvider(seed=[{
            "category": "logic", "severity": "high", "title": "SQLi",
            "description": "d", "recommendation": "r", "start_line": 2, "end_line": 2,
        }]),
    )
    findings = await agent.analyze("code", "python")
    assert len(findings) == 1
    f = findings[0]
    assert f.category == "security"  # forced to the agent's category (not the seed's "logic")
    assert f.sources[0].name == "security-agent"
    assert f.location.start_line == 2


def test_build_agents_returns_six_specialists():
    agents = build_agents()
    names = {a.name for a in agents}
    assert names == {
        "security-agent", "performance-agent", "logic-agent",
        "quality-agent", "docs-agent", "tests-agent",
    }


@pytest.mark.asyncio
async def test_agent_sets_location_file_when_given():
    agents = build_agents(provider=MockProvider(seed=[{
        "category": "security", "severity": "high", "title": "SQLi",
        "description": "d", "recommendation": "r", "start_line": 1, "end_line": 1,
    }]))
    findings = await agents[0].analyze("x = 1\n", "python", file="app/auth.py")
    assert findings[0].location.file == "app/auth.py"
