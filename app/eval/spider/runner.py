"""End-to-end Spider eval runner.

For each Spider item:
  1. Build a pipeline scoped to that item's database (Spider-specific
     retriever, validator, SQLite executor, dialect-tuned SQL generator).
  2. Run the pipeline on the natural-language question.
  3. Compare result set of generated SQL vs. gold SQL (Spider's official
     execution accuracy metric).

We deliberately skip the Optimization agent because it would no-op on SQLite,
and reduce per-question latency.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from app.agents.base import Pipeline
from app.agents.execution_agent import ExecutionAgent
from app.agents.rewrite_agent import RewriteAgent
from app.agents.schema_agent import SchemaRetrievalAgent
from app.agents.sql_agent import SQLGenerationAgent
from app.agents.validation_agent import ValidationAgent
from app.eval.metrics import (
    hallucination, mean_reciprocal_rank,
    precision_at_k, recall_at_k, result_set_equal,
)
from app.eval.spider.embedder import SPIDER_COLLECTION
from app.eval.spider.loader import SpiderDataset, SpiderItem
from app.execution.executor import SafeExecutor
from app.monitoring.logger import configure_logging, get_logger
from app.rag.retriever import HybridRetriever
from app.rag.vector_store import QdrantSchemaStore
from app.sql_generation.generator import SQLGenerator
from app.validation.validator import SQLValidator

log = get_logger(__name__)


@dataclass
class SpiderItemResult:
    question: str
    db_id: str
    gold_sql: str
    generated_sql: str
    retrieved_tables: list[str]
    gold_tables: list[str]
    recall_at_k: float
    precision_at_k: float
    reciprocal_rank: float
    execution_match: bool | None
    hallucinated: bool
    validation_ok: bool
    validation_issues: list[str]
    latency_ms: float
    latency_ms_by_stage: dict[str, float] = field(default_factory=dict)
    error: str | None = None


@dataclass
class SpiderRunSummary:
    n: int
    k: int
    avg_recall_at_k: float
    avg_precision_at_k: float
    mrr: float
    execution_accuracy: float
    validation_pass_rate: float
    hallucination_rate: float
    avg_latency_ms: float
    by_db_execution_accuracy: dict[str, float]
    items: list[SpiderItemResult]

    def as_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "k": self.k,
            "avg_recall_at_k": self.avg_recall_at_k,
            "avg_precision_at_k": self.avg_precision_at_k,
            "mrr": self.mrr,
            "execution_accuracy": self.execution_accuracy,
            "validation_pass_rate": self.validation_pass_rate,
            "hallucination_rate": self.hallucination_rate,
            "avg_latency_ms": self.avg_latency_ms,
            "by_db_execution_accuracy": self.by_db_execution_accuracy,
        }


def _gold_tables(allowed_schema: dict[str, list[str]], gold_sql: str) -> list[str]:
    """Extract gold tables by scanning the gold SQL for known table names.

    This avoids depending on sqlglot's SQLite parser for messy gold queries.
    """
    lowered = gold_sql.lower()
    return [t for t in allowed_schema if t.lower() in lowered]


def _build_pipeline(
    db_id: str, allowed_schema: dict[str, list[str]], executor: SafeExecutor
) -> Pipeline:
    store = QdrantSchemaStore(collection=SPIDER_COLLECTION)
    retriever = HybridRetriever(store=store, db_id=db_id)
    validator = SQLValidator(allowed_schema=allowed_schema, dialect="sqlite")
    generator = SQLGenerator(dialect="sqlite")

    return Pipeline([
        RewriteAgent(),
        SchemaRetrievalAgent(retriever=retriever),
        SQLGenerationAgent(generator=generator),
        ValidationAgent(validator=validator),
        # No OptimizationAgent on SQLite.
        ExecutionAgent(executor=executor),
    ])


def _run_one(
    item: SpiderItem,
    dataset: SpiderDataset,
    k: int = 5,
) -> SpiderItemResult:
    schema = dataset.introspect(item.db_id)
    allowed = schema.as_allowed_schema()

    sqlite_engine = dataset.engine(item.db_id)
    executor = SafeExecutor(engine=sqlite_engine)
    pipeline = _build_pipeline(item.db_id, allowed, executor=executor)

    start = time.perf_counter()
    error: str | None = None
    try:
        state = pipeline.run({"query": item.question, "rewrite": False, "top_k": k})
    except Exception as e:
        log.exception("pipeline failed on db=%s", item.db_id)
        return SpiderItemResult(
            question=item.question, db_id=item.db_id, gold_sql=item.gold_sql,
            generated_sql="", retrieved_tables=[], gold_tables=[],
            recall_at_k=0.0, precision_at_k=0.0, reciprocal_rank=0.0,
            execution_match=None, hallucinated=False,
            validation_ok=False, validation_issues=[],
            latency_ms=(time.perf_counter() - start) * 1000.0,
            error=str(e),
        )
    total_ms = (time.perf_counter() - start) * 1000.0

    ctx = state.get("schema_context")
    retrieved_tables = list(getattr(ctx, "tables", []) or [])
    generated_sql = state.get("sql", "") or ""

    gold_tables = _gold_tables(allowed, item.gold_sql)
    rec = recall_at_k(retrieved_tables, gold_tables, k=k)
    prec = precision_at_k(retrieved_tables, gold_tables, k=k)
    rr = 0.0
    for rank, t in enumerate(retrieved_tables, start=1):
        if t in gold_tables:
            rr = 1.0 / rank
            break

    execution_match: bool | None = None
    if state.get("validation_ok") and generated_sql:
        try:
            gen_result = executor.execute(generated_sql)
            truth_result = executor.execute(item.gold_sql)
            execution_match = result_set_equal(
                gen_result.columns, gen_result.rows,
                truth_result.columns, truth_result.rows,
                order_sensitive=False,
            )
        except Exception as e:
            log.warning("execution failed for db=%s: %s", item.db_id, e)
            execution_match = False
            error = str(e)

    used_tables = state.get("validation_used_tables") or []
    used_columns = state.get("validation_used_columns") or []
    allowed_lower = {t.lower(): {c.lower() for c in cols} for t, cols in allowed.items()}
    hall = hallucination(used_tables, used_columns, allowed_lower)

    stage_lat = {t.name: t.latency_ms for t in state.trace}

    return SpiderItemResult(
        question=item.question, db_id=item.db_id, gold_sql=item.gold_sql,
        generated_sql=generated_sql,
        retrieved_tables=retrieved_tables, gold_tables=gold_tables,
        recall_at_k=rec, precision_at_k=prec, reciprocal_rank=rr,
        execution_match=execution_match, hallucinated=hall,
        validation_ok=bool(state.get("validation_ok")),
        validation_issues=state.get("validation_issues") or [],
        latency_ms=total_ms, latency_ms_by_stage=stage_lat,
        error=error,
    )


def evaluate_spider(
    limit: int | None = None,
    k: int = 5,
    dataset: SpiderDataset | None = None,
) -> SpiderRunSummary:
    configure_logging()
    ds = dataset or SpiderDataset()
    items = ds.load_dev(limit=limit)
    log.info("Running Spider eval on %d items (k=%d)", len(items), k)

    results: list[SpiderItemResult] = []
    for i, item in enumerate(items, start=1):
        if i % 25 == 0 or i == 1:
            log.info("[%d/%d] db=%s | %s", i, len(items), item.db_id, item.question[:60])
        results.append(_run_one(item, ds, k=k))

    n = len(results)
    avg_recall = sum(r.recall_at_k for r in results) / n if n else 0.0
    avg_prec = sum(r.precision_at_k for r in results) / n if n else 0.0
    mrr = mean_reciprocal_rank([(r.retrieved_tables, r.gold_tables) for r in results])
    exec_runs = [r for r in results if r.execution_match is not None]
    exec_acc = (
        sum(1 for r in exec_runs if r.execution_match) / len(exec_runs)
        if exec_runs else 0.0
    )
    val_rate = sum(1 for r in results if r.validation_ok) / n if n else 0.0
    hall_rate = sum(1 for r in results if r.hallucinated) / n if n else 0.0
    avg_lat = sum(r.latency_ms for r in results) / n if n else 0.0

    by_db: dict[str, list[bool]] = {}
    for r in exec_runs:
        by_db.setdefault(r.db_id, []).append(bool(r.execution_match))
    by_db_acc = {db: sum(v) / len(v) for db, v in by_db.items()}

    return SpiderRunSummary(
        n=n, k=k,
        avg_recall_at_k=avg_recall,
        avg_precision_at_k=avg_prec,
        mrr=mrr,
        execution_accuracy=exec_acc,
        validation_pass_rate=val_rate,
        hallucination_rate=hall_rate,
        avg_latency_ms=avg_lat,
        by_db_execution_accuracy=by_db_acc,
        items=results,
    )
