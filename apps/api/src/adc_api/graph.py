from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from adc_core.models import Finding
from langgraph.graph import END, START, StateGraph

from adc_api.agents import SpecialistAgent
from adc_api.aggregator import aggregate


class ReviewState(TypedDict):
    code: str
    language: str
    findings: Annotated[list[Finding], operator.add]  # concurrent specialist appends
    result: list[Finding]                             # aggregator output (last-write-wins)


def _specialist_node(agent: SpecialistAgent):
    async def node(state: ReviewState) -> dict:
        try:
            found = await agent.analyze(state["code"], state["language"])
        except Exception:  # noqa: BLE001 — isolate one agent's failure from the whole review
            found = []
        return {"findings": found}

    return node


def _scanner_node(scanner):
    async def node(state: ReviewState) -> dict:
        try:
            found = await scanner.scan(state["code"], state["language"])
        except Exception:  # noqa: BLE001 — isolate a scanner failure from the review
            found = []
        return {"findings": found}

    return node


async def _aggregate_node(state: ReviewState) -> dict:
    return {"result": aggregate(state["findings"])}


def build_graph(agents: list[SpecialistAgent], scanners=()):
    """Compile START -> {specialists + scanners concurrently} -> aggregate -> END."""
    g = StateGraph(ReviewState)
    g.add_node("aggregate", _aggregate_node)
    for agent in agents:
        g.add_node(agent.name, _specialist_node(agent))
    for scanner in scanners:
        g.add_node(scanner.name, _scanner_node(scanner))
    for agent in agents:
        g.add_edge(START, agent.name)
        g.add_edge(agent.name, "aggregate")
    for scanner in scanners:
        g.add_edge(START, scanner.name)
        g.add_edge(scanner.name, "aggregate")
    g.add_edge("aggregate", END)
    return g.compile()
