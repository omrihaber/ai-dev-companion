from __future__ import annotations

import uuid
from dataclasses import dataclass

from adc_core.models import Category, Finding, Location, Source

from adc_api import agent_prompts
from adc_api.providers import ModelProvider, build_provider
from adc_api.schemas import ReviewOutput

# (name, category, prompt-attr, env-key)
_SPECS: list[tuple[str, Category, str, str]] = [
    ("security-agent", "security", "SECURITY", "SECURITY"),
    ("performance-agent", "performance", "PERFORMANCE", "PERFORMANCE"),
    ("logic-agent", "logic", "LOGIC", "LOGIC"),
    ("quality-agent", "quality", "QUALITY", "QUALITY"),
    ("docs-agent", "docs", "DOCS", "DOCS"),
    ("tests-agent", "tests", "TESTS", "TESTS"),
]


@dataclass
class SpecialistAgent:
    name: str
    category: Category
    system_prompt: str
    provider: ModelProvider

    async def analyze(self, code: str, language: str, file: str | None = None) -> list[Finding]:
        out: ReviewOutput = await self.provider.complete_structured(
            system=self.system_prompt.format(language=language),
            user=f"```{language}\n{code}\n```",
            response_model=ReviewOutput,
        )
        return [
            Finding(
                id=str(uuid.uuid4()),
                category=self.category,
                severity=raw.severity,
                title=raw.title,
                description=raw.description,
                recommendation=raw.recommendation,
                location=Location(file=file, start_line=raw.start_line, end_line=raw.end_line),
                sources=[Source(type="agent", name=self.name)],
            )
            for raw in out.findings
        ]


def build_agents(
    provider: ModelProvider | None = None, model: str | None = None
) -> list[SpecialistAgent]:
    """Build the 6 specialists. If `provider` is given, all agents share it (used by
    tests/e2e to inject a MockProvider). Otherwise each agent resolves its own provider from
    per-agent env, falling back to the per-review `model` choice, then the global default."""
    import os

    agents: list[SpecialistAgent] = []
    for name, category, prompt_attr, env_key in _SPECS:
        if provider is not None:
            p: ModelProvider = provider
        else:
            model_id = os.getenv(f"ADC_AGENT_{env_key}_MODEL") or model
            kind = os.getenv(f"ADC_AGENT_{env_key}_PROVIDER")
            p = build_provider(model=model_id, kind=kind)
        agents.append(
            SpecialistAgent(
                name=name,
                category=category,
                system_prompt=getattr(agent_prompts, prompt_attr),
                provider=p,
            )
        )
    return agents
