"""A/B compare the old linear pipeline vs. the new LangGraph + self-correct pipeline.

Both pipelines run on the same golden set against the same Postgres DB. Reports
per-pipeline execution accuracy, validation pass rate, hallucination rate,
latency, and (for B) retry stats.

Requires:
  - .env populated with OPENAI_API_KEY + Postgres + Qdrant config
  - `python -m scripts.seed_database`     (populated Postgres data)
  - `python -m scripts.embed_schema`      (Qdrant schema docs)
  - `pip install langgraph==0.2.60`

Usage:
    python -m scripts.run_ab_eval
    python -m scripts.run_ab_eval --k 5
"""
from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from typing import Any

from app.agents.base import Pipeline
from app.agents.execution_agent import ExecutionAgent
from app.agents.explanation_agent import ExplanationAgent
from app.agents.optimization_agent import OptimizationAgent
from app.agents.orchestrator import get_full_pipeline
from app.agents.rewrite_agent import RewriteAgent
from app.agents.schema_agent import SchemaRetrievalAgent
from app.agents.sql_agent import SQLGenerationAgent
from app.agents.validation_agent import ValidationAgent
from app.db.models import Base
from app.eval.golden_dataset import GOLDEN_SET, GoldenItem
from app.eval.metrics import exact_match, hallucination, result_set_equal
from app.execution.executor import SafeExecutor
from app.monitoring.logger import configure_logging, get_logger
from app.validation.validator import SQLValidator


log = get_logger(__name__)


def _allowed_schema_sets() -> dict[str, set[str]]:
    return {
        t.name.lower(): {c.name.lower() for c in t.columns}
        for t in Base.metadata.tables.values()
    }


def _validator() -> SQLValidator:
    allowed: dict[str, list[str]] = {}
    for table_name, table in Base.metadata.tables.items():
        allowed[table_name] = [c.name for c in table.columns]
    return SQLValidator(allowed_schema=allowed)


def _linear_pipeline() -> Pipeline:
    """Pre-LangGraph behavior: linear sequence, no retry loop. This is the
    'before' baseline. Pipeline([...]) builds a flat StateGraph via the
    backward-compat constructor, so the structure differs from the old
    Pipeline but the execution path is identical: each agent runs once."""
    return Pipeline([
        RewriteAgent(),
        SchemaRetrievalAgent(),
        SQLGenerationAgent(),
        ValidationAgent(validator=_validator()),
        OptimizationAgent(),
        ExecutionAgent(),
        ExplanationAgent(),
    ])


@dataclass
class ItemMetrics:
    question: str
    sql: str
    validation_ok: bool
    execution_match: bool | None
    hallucinated: bool
    exact_match: bool
    n_retries: int
    latency_ms: float


def _run_one(
    pipeline: Pipeline, item: GoldenItem, executor: SafeExecutor, k: int
) -> ItemMetrics:
    start = time.perf_counter()
    state = pipeline.run({"query": item.question, "rewrite": True, "top_k": k})
    latency = (time.perf_counter() - start) * 1000.0

    sql = state.get("sql", "") or ""
    validation_ok = bool(state.get("validation_ok"))
    n_retries = int(state.data.get("retry_count", 0))

    execution_match: bool | None = None
    if validation_ok and sql:
        try:
            gen_result = executor.execute(sql)
            truth_result = executor.execute(item.ground_truth_sql)
            execution_match = result_set_equal(
                gen_result.columns, gen_result.rows,
                truth_result.columns, truth_result.rows,
            )
        except Exception as e:
            log.warning("execution failed for %r: %s", item.question, e)
            execution_match = False

    used_tables = state.get("validation_used_tables") or []
    used_columns = state.get("validation_used_columns") or []
    hall = hallucination(used_tables, used_columns, _allowed_schema_sets())
    em = exact_match(sql, item.ground_truth_sql)

    return ItemMetrics(
        question=item.question,
        sql=sql,
        validation_ok=validation_ok,
        execution_match=execution_match,
        hallucinated=hall,
        exact_match=em,
        n_retries=n_retries,
        latency_ms=latency,
    )


def _summarize(name: str, results: list[ItemMetrics]) -> dict[str, Any]:
    n = len(results)
    exec_runs = [r for r in results if r.execution_match is not None]
    return {
        "name": name,
        "n": n,
        "validation_pass_rate": sum(1 for r in results if r.validation_ok) / n,
        "execution_accuracy": (
            sum(1 for r in exec_runs if r.execution_match) / len(exec_runs)
            if exec_runs else 0.0
        ),
        "hallucination_rate": sum(1 for r in results if r.hallucinated) / n,
        "exact_match_rate": sum(1 for r in results if r.exact_match) / n,
        "avg_latency_ms": sum(r.latency_ms for r in results) / n,
        "items_with_retry": sum(1 for r in results if r.n_retries > 0),
        "total_retries": sum(r.n_retries for r in results),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=5)
    args = ap.parse_args()
    configure_logging()

    executor = SafeExecutor()

    pipeline_a = _linear_pipeline()
    pipeline_b = get_full_pipeline()

    print(f"\nRunning A/B eval on {len(GOLDEN_SET)} golden items (k={args.k})...\n")

    results_a: list[ItemMetrics] = []
    results_b: list[ItemMetrics] = []

    for item in GOLDEN_SET:
        log.info("A (linear): %s", item.question)
        results_a.append(_run_one(pipeline_a, item, executor, args.k))
        log.info("B (LangGraph + self-correct): %s", item.question)
        results_b.append(_run_one(pipeline_b, item, executor, args.k))

    sum_a = _summarize("A: linear (old behavior)", results_a)
    sum_b = _summarize("B: LangGraph + self-correct", results_b)

    print("\n=== Aggregate comparison ===\n")
    float_keys = [
        "execution_accuracy", "validation_pass_rate", "hallucination_rate",
        "exact_match_rate", "avg_latency_ms",
    ]
    int_keys = ["items_with_retry", "total_retries"]
    print(f"  {'metric':24s}  {'A (linear)':>14s}  {'B (LangGraph)':>16s}  {'delta':>10s}")
    print(f"  {'-'*24}  {'-'*14}  {'-'*16}  {'-'*10}")
    for kk in float_keys:
        a = sum_a[kk]; b = sum_b[kk]
        print(f"  {kk:24s}  {a:>14.3f}  {b:>16.3f}  {b - a:>+10.3f}")
    for kk in int_keys:
        a = sum_a[kk]; b = sum_b[kk]
        print(f"  {kk:24s}  {a:>14d}  {b:>16d}  {b - a:>+10d}")

    print("\n=== Per-item differences ===\n")
    print(f"  {'#':>2}  {'A':^4}  {'B':^4}  {'retries':>7}  question")
    print(f"  {'-'*2}  {'-'*4}  {'-'*4}  {'-'*7}  {'-'*40}")
    rescued_count = 0
    for i, (a, b) in enumerate(zip(results_a, results_b), start=1):
        a_mark = "OK" if a.execution_match else ".."
        b_mark = "OK" if b.execution_match else ".."
        rescued = (not a.execution_match) and bool(b.execution_match)
        marker = "* " if rescued else "  "
        if rescued:
            rescued_count += 1
        print(f"  {i:>2}  {a_mark:^4}  {b_mark:^4}  {b.n_retries:>7}  {marker}{a.question}")

    print(f"\n  * = items rescued by self-correct retry ({rescued_count}/{len(results_a)})")


if __name__ == "__main__":
    main()
