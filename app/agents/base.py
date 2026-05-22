from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, TypedDict

from langgraph.graph import StateGraph, START, END


@dataclass
class AgentTrace:
    name: str
    latency_ms: float
    output_keys: list[str]
    notes: list[str] = field(default_factory=list)


@dataclass
class PipelineState:
    """Mutable bag passed through every agent. Each agent reads what it needs and writes its result."""
    inputs: dict[str, Any] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)
    trace: list[AgentTrace] = field(default_factory=list)

    def get(self, key: str, default: Any = None) -> Any:
        if key in self.data:
            return self.data[key]
        return self.inputs.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value


class Agent(Protocol):
    name: str
    def run(self, state: PipelineState) -> None: ...


class GraphState(TypedDict, total=False):
    """LangGraph state schema. The PipelineState object is threaded through nodes
    which mutate it in place; LangGraph just overwrites the slot each step.
    Keeping a single object lets the existing agents (which expect PipelineState)
    work unchanged.
    """
    state: PipelineState


def agent_node(agent: Agent) -> Callable[[GraphState], GraphState]:
    """Wrap an Agent.run() into a LangGraph node. Records timing and the set of
    new keys it wrote into the PipelineState.trace so /ask responses still carry
    a per-stage trace."""
    def _node(gs: GraphState) -> GraphState:
        ps = gs["state"]
        before = set(ps.data.keys())
        start = time.perf_counter()
        agent.run(ps)
        latency_ms = (time.perf_counter() - start) * 1000.0
        new_keys = sorted(set(ps.data.keys()) - before)
        ps.trace.append(
            AgentTrace(name=agent.name, latency_ms=latency_ms, output_keys=new_keys)
        )
        return {"state": ps}
    return _node


def _build_linear_graph(agents: list[Agent]) -> Any:
    builder = StateGraph(GraphState)
    prev: Any = START
    for agent in agents:
        builder.add_node(agent.name, agent_node(agent))
        builder.add_edge(prev, agent.name)
        prev = agent.name
    builder.add_edge(prev, END)
    return builder.compile()


class Pipeline:
    """Runs a compiled LangGraph StateGraph and returns the final PipelineState.

    Two construction forms are supported:
      - Pipeline([agent_a, agent_b, ...]) builds a linear graph (backward
        compatible with the previous sequential Pipeline).
      - Pipeline(compiled_graph) wraps a pre-compiled StateGraph, used by the
        orchestrator to add conditional edges (self-correct loop).
    """
    def __init__(self, agents_or_graph: list[Agent] | Any) -> None:
        if isinstance(agents_or_graph, list):
            self._graph = _build_linear_graph(agents_or_graph)
        else:
            self._graph = agents_or_graph

    def run(self, inputs: dict[str, Any]) -> PipelineState:
        ps = PipelineState(inputs=dict(inputs))
        final = self._graph.invoke({"state": ps})
        return final["state"]
