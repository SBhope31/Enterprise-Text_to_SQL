from __future__ import annotations

import time
from functools import lru_cache
from typing import Any

from langgraph.graph import StateGraph, START, END

from app.agents.base import (
    AgentTrace, GraphState, Pipeline, agent_node,
)
from app.agents.execution_agent import ExecutionAgent
from app.agents.explanation_agent import ExplanationAgent
from app.agents.optimization_agent import OptimizationAgent
from app.agents.rewrite_agent import RewriteAgent
from app.agents.schema_agent import SchemaRetrievalAgent
from app.agents.sql_agent import SQLGenerationAgent
from app.agents.validation_agent import ValidationAgent
from app.db.models import Base
from app.validation.validator import SQLValidator


MAX_SELF_CORRECT_RETRIES = 2


@lru_cache
def _validator() -> SQLValidator:
    allowed: dict[str, list[str]] = {}
    for table_name, table in Base.metadata.tables.items():
        allowed[table_name] = [c.name for c in table.columns]
    return SQLValidator(allowed_schema=allowed)


def _self_correct_node(gs: GraphState) -> GraphState:
    """Re-prompt SQL generation with the previous failed SQL and the error.

    Done by appending the feedback to schema_context_text so the next pass
    through SQLGenerationAgent sees it. No changes to the agent or generator.
    """
    ps = gs["state"]
    start = time.perf_counter()
    retry = int(ps.data.get("retry_count", 0))

    prev_sql = ps.data.get("sql", "") or ""
    issues = ps.data.get("validation_issues") or []
    exec_error = ps.data.get("execution_error")

    parts: list[str] = []
    if issues:
        parts.append("Validation issues:\n" + "\n".join(f"- {i}" for i in issues))
    if exec_error:
        parts.append(f"Execution error: {exec_error}")
    error_msg = "\n".join(parts) if parts else "(unknown error)"

    schema_text = ps.data.get("schema_context_text", "") or ""
    augmented = (
        f"{schema_text}\n\n"
        f"PREVIOUS ATTEMPT (failed):\n{prev_sql}\n\n"
        f"FIX THE FOLLOWING:\n{error_msg}\n"
        f"Return a corrected SQL query that addresses the error above."
    )
    ps.set("schema_context_text", augmented)
    ps.set("retry_count", retry + 1)
    # Clear stale outputs so they don't bleed into the next attempt.
    ps.data.pop("execution_error", None)
    ps.data.pop("execution_result", None)

    latency_ms = (time.perf_counter() - start) * 1000.0
    ps.trace.append(AgentTrace(
        name="self_correct",
        latency_ms=latency_ms,
        output_keys=["retry_count", "schema_context_text"],
        notes=[f"retry {retry + 1}/{MAX_SELF_CORRECT_RETRIES}"],
    ))
    return {"state": ps}


def _after_validation(gs: GraphState) -> str:
    ps = gs["state"]
    if ps.get("validation_ok"):
        return "optimization"
    if int(ps.data.get("retry_count", 0)) < MAX_SELF_CORRECT_RETRIES:
        return "self_correct"
    return "explanation"  # give up; let explanation surface the failure


def _after_execution(gs: GraphState) -> str:
    ps = gs["state"]
    if ps.data.get("execution_error") and int(ps.data.get("retry_count", 0)) < MAX_SELF_CORRECT_RETRIES:
        return "self_correct"
    return "explanation"


def _build_full_graph() -> Any:
    rewrite = RewriteAgent()
    schema = SchemaRetrievalAgent()
    sql_gen = SQLGenerationAgent()
    validation = ValidationAgent(validator=_validator())
    optimization = OptimizationAgent()
    execution = ExecutionAgent()
    explanation = ExplanationAgent()

    g = StateGraph(GraphState)
    g.add_node(rewrite.name, agent_node(rewrite))
    g.add_node(schema.name, agent_node(schema))
    g.add_node(sql_gen.name, agent_node(sql_gen))
    g.add_node(validation.name, agent_node(validation))
    g.add_node(optimization.name, agent_node(optimization))
    g.add_node(execution.name, agent_node(execution))
    g.add_node(explanation.name, agent_node(explanation))
    g.add_node("self_correct", _self_correct_node)

    g.add_edge(START, rewrite.name)
    g.add_edge(rewrite.name, schema.name)
    g.add_edge(schema.name, sql_gen.name)
    g.add_edge(sql_gen.name, validation.name)

    g.add_conditional_edges(
        validation.name,
        _after_validation,
        {
            "optimization": optimization.name,
            "self_correct": "self_correct",
            "explanation": explanation.name,
        },
    )
    g.add_edge(optimization.name, execution.name)
    g.add_conditional_edges(
        execution.name,
        _after_execution,
        {
            "self_correct": "self_correct",
            "explanation": explanation.name,
        },
    )
    g.add_edge("self_correct", sql_gen.name)
    g.add_edge(explanation.name, END)

    return g.compile()


@lru_cache
def get_full_pipeline() -> Pipeline:
    """rewrite -> retrieve -> generate -> validate -> [optimize -> execute] -> explain,
    with a self-correct loop that re-prompts SQL generation on validation failure
    or execution error (max 2 retries)."""
    return Pipeline(_build_full_graph())


@lru_cache
def get_generate_only_pipeline() -> Pipeline:
    """Rewrite -> retrieve -> generate -> validate. No execution, no retry loop."""
    return Pipeline([
        RewriteAgent(),
        SchemaRetrievalAgent(),
        SQLGenerationAgent(),
        ValidationAgent(validator=_validator()),
    ])
