import pytest
from adc_api.providers import MockProvider


@pytest.mark.asyncio
async def test_mock_provider_returns_seeded_findings():
    provider = MockProvider(seed=[{
        "category": "security", "severity": "high", "title": "SQLi",
        "description": "d", "recommendation": "r", "start_line": 2, "end_line": 2,
    }])
    out = await provider.review("code", "python")
    assert out[0].category == "security"
    assert provider.name == "core-reviewer"
