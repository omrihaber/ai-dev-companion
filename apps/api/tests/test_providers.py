import pytest
from adc_api.providers import MockProvider, build_provider
from adc_api.schemas import ReviewOutput


@pytest.mark.asyncio
async def test_mock_provider_returns_seeded_structured_output():
    provider = MockProvider(seed=[{
        "category": "security", "severity": "high", "title": "SQLi",
        "description": "d", "recommendation": "r", "start_line": 2, "end_line": 2,
    }])
    out = await provider.complete_structured(system="s", user="u", response_model=ReviewOutput)
    assert isinstance(out, ReviewOutput)
    assert out.findings[0].category == "security"


def test_build_provider_defaults_to_ollama():
    p = build_provider()
    assert p.model  # has a model string
    assert hasattr(p, "complete_structured")
