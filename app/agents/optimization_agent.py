"""Optimization Agent.

Runs EXPLAIN on the validated SQL and surfaces simple heuristics:
- whether the planner expects a sequential scan over a large table
- estimated total cost / rows

This is a *static* optimization layer; it does not rewrite SQL automatically.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.agents.base import PipelineState
from app.db.session import engine as default_engine
from app.monitoring.logger import get_logger

log = get_logger(__name__)


class OptimizationAgent:
    name = "optimization"

    def __init__(self, engine: Engine | None = None) -> None:
        self._engine: Engine = engine or default_engine

    def run(self, state: PipelineState) -> None:
        if not state.get("validation_ok"):
            state.set("optimization_notes", ["skipped: validation failed"])
            return
        if self._engine.dialect.name != "postgresql":
            # EXPLAIN (FORMAT JSON) is Postgres-specific; skip on other engines.
            state.set("optimization_notes", ["skipped: non-postgres engine"])
            state.set("plan_summary", {})
            return

        sql = state.get("sql", "")
        notes: list[str] = []
        plan_summary: dict[str, object] = {}
        try:
            with self._engine.connect() as conn:
                conn.execute(text("SET TRANSACTION READ ONLY"))
                rows = conn.execute(text(f"EXPLAIN (FORMAT JSON) {sql}")).fetchone()
            plan = rows[0][0]["Plan"] if rows else {}
            plan_summary = {
                "total_cost": plan.get("Total Cost"),
                "plan_rows": plan.get("Plan Rows"),
                "node_type": plan.get("Node Type"),
            }
            for node in _walk_plan(plan):
                if node.get("Node Type") == "Seq Scan" and (node.get("Plan Rows") or 0) > 10_000:
                    notes.append(
                        f"Large sequential scan on '{node.get('Relation Name')}' "
                        f"(~{node.get('Plan Rows')} rows). Consider an index or a WHERE filter."
                    )
        except Exception as e:
            log.warning("EXPLAIN failed (non-fatal): %s", e)
            notes.append(f"EXPLAIN failed: {e}")

        state.set("optimization_notes", notes)
        state.set("plan_summary", plan_summary)


def _walk_plan(node: dict) -> list[dict]:
    out = [node]
    for child in node.get("Plans", []) or []:
        out.extend(_walk_plan(child))
    return out
