"""Run the end-to-end evaluation harness against the bundled golden set.

Produces:
- Retrieval Recall@K, Precision@K, MRR
- SQL Execution Accuracy (result-set equality vs. ground-truth SQL)
- Hallucination Rate (references to unknown tables/columns)
- Avg latency per stage
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from app.agents.orchestrator import get_full_pipeline
from app.db.models import Base
from app.eval.golden_dataset import GOLDEN_SET, GoldenItem
from app.eval.metrics import (
    exact_match, hallucination, mean_reciprocal_rank,
    precision_at_k, recall_at_k, result_set_equal,
)
from app.execution.executor import SafeExecutor
from app.monitoring.logger import configure_logging, get_logger

log = get_logger(__name__)


@dataclass
class ItemResult:
    question: str
    rewritten: str
    sql: str
    ground_truth_sql: str
    retrieved_tables: list[str]
    relevant_tables: list[str]
    recall_at_k: float
    precision_at_k: float
    reciprocal_rank: float
    exact_match: bool
    execution_match: bool | None
    hallucinated: bool
    validation_ok: bool
    validation_issues: list[str]
    latency_ms_total: float
    latency_ms_by_stage: dict[str, float] = field(default_factory=dict)


def _allowed_schema() -> dict[str, set[str]]:
    return {
        t.name.lower(): {c.name.lower() for c in t.columns}
        for t in Base.metadata.tables.values()
    }


def _run_one(item: GoldenItem, k: int = 5) -> ItemResult:
    pipeline = get_full_pipeline()
    executor = SafeExecutor()

    start = time.perf_counter()
    state = pipeline.run({"query": item.question, "rewrite": True, "top_k": k})
    total_ms = (time.perf_counter() - start) * 1000.0

    ctx = state.get("schema_context")
    retrieved_tables = list(getattr(ctx, "tables", []) or [])
    sql = state.get("sql", "") or ""

    rec = recall_at_k(retrieved_tables, item.relevant_tables, k=k)
    prec = precision_at_k(retrieved_tables, item.relevant_tables, k=k)
    rr = (
        1.0 / (retrieved_tables.index(next(t for t in item.relevant_tables if t in retrieved_tables)) + 1)
        if any(t in retrieved_tables for t in item.relevant_tables) else 0.0
    )

    em = exact_match(sql, item.ground_truth_sql)

    # Execution accuracy: run both queries and compare result sets.
    execution_match: bool | None = None
    if state.get("validation_ok") and sql:
        try:
            gen_result = executor.execute(sql)
            truth_result = executor.execute(item.ground_truth_sql)
            execution_match = result_set_equal(
                gen_result.columns, gen_result.rows,
                truth_result.columns, truth_result.rows,
            )
        except Exception as e:
            log.warning("Execution failed for %r: %s", item.question, e)
            execution_match = False

    used_tables = state.get("validation_used_tables") or []
    used_columns = state.get("validation_used_columns") or []
    hall = hallucination(used_tables, used_columns, _allowed_schema())

    stage_latencies = {t.name: t.latency_ms for t in state.trace}

    return ItemResult(
        question=item.question,
        rewritten=state.get("rewritten_query", ""),
        sql=sql,
        ground_truth_sql=item.ground_truth_sql,
        retrieved_tables=retrieved_tables,
        relevant_tables=list(item.relevant_tables),
        recall_at_k=rec,
        precision_at_k=prec,
        reciprocal_rank=rr,
        exact_match=em,
        execution_match=execution_match,
        hallucinated=hall,
        validation_ok=bool(state.get("validation_ok")),
        validation_issues=state.get("validation_issues") or [],
        latency_ms_total=total_ms,
        latency_ms_by_stage=stage_latencies,
    )


@dataclass
class RunSummary:
    n: int
    k: int
    avg_recall_at_k: float
    avg_precision_at_k: float
    mrr: float
    exact_match_rate: float
    execution_accuracy: float
    hallucination_rate: float
    validation_pass_rate: float
    avg_latency_ms: float
    avg_latency_by_stage: dict[str, float]
    items: list[ItemResult]

    def as_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "k": self.k,
            "avg_recall_at_k": self.avg_recall_at_k,
            "avg_precision_at_k": self.avg_precision_at_k,
            "mrr": self.mrr,
            "exact_match_rate": self.exact_match_rate,
            "execution_accuracy": self.execution_accuracy,
            "hallucination_rate": self.hallucination_rate,
            "validation_pass_rate": self.validation_pass_rate,
            "avg_latency_ms": self.avg_latency_ms,
            "avg_latency_by_stage": self.avg_latency_by_stage,
        }


def evaluate(k: int = 5) -> RunSummary:
    configure_logging()
    items: list[ItemResult] = []
    for it in GOLDEN_SET:
        log.info("Evaluating: %s", it.question)
        items.append(_run_one(it, k=k))

    n = len(items)
    avg_recall = sum(i.recall_at_k for i in items) / n
    avg_prec = sum(i.precision_at_k for i in items) / n
    mrr = mean_reciprocal_rank(
        [(i.retrieved_tables, i.relevant_tables) for i in items]
    )
    em_rate = sum(1 for i in items if i.exact_match) / n
    exec_runs = [i for i in items if i.execution_match is not None]
    exec_acc = (
        sum(1 for i in exec_runs if i.execution_match) / len(exec_runs)
        if exec_runs else 0.0
    )
    hall_rate = sum(1 for i in items if i.hallucinated) / n
    val_rate = sum(1 for i in items if i.validation_ok) / n
    avg_lat = sum(i.latency_ms_total for i in items) / n

    stages: dict[str, list[float]] = {}
    for i in items:
        for k_name, v in i.latency_ms_by_stage.items():
            stages.setdefault(k_name, []).append(v)
    avg_stage = {k_name: sum(v) / len(v) for k_name, v in stages.items()}

    return RunSummary(
        n=n,
        k=k,
        avg_recall_at_k=avg_recall,
        avg_precision_at_k=avg_prec,
        mrr=mrr,
        exact_match_rate=em_rate,
        execution_accuracy=exec_acc,
        hallucination_rate=hall_rate,
        validation_pass_rate=val_rate,
        avg_latency_ms=avg_lat,
        avg_latency_by_stage=avg_stage,
        items=items,
    )
