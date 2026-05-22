from functools import lru_cache

from fastapi import APIRouter, HTTPException

from app.agents.orchestrator import get_full_pipeline, get_generate_only_pipeline
from app.api.schemas import (
    AgentTraceEntry, AskRequest, AskResponse,
    ExecuteQueryRequest, ExecuteQueryResponse,
    GenerateSQLRequest, GenerateSQLResponse,
    RetrievedColumn, RetrievedTable, SchemaContextResponse,
)
from app.config import get_settings
from app.db.models import Base
from app.execution.executor import SafeExecutor
from app.monitoring.logger import get_logger
from app.rag.retriever import HybridRetriever, RetrievedContext
from app.validation.validator import SQLValidator


router = APIRouter()
log = get_logger(__name__)


@lru_cache
def _retriever() -> HybridRetriever:
    return HybridRetriever()


@lru_cache
def _executor() -> SafeExecutor:
    return SafeExecutor()


@lru_cache
def _validator() -> SQLValidator:
    # Build allowed_schema from SQLAlchemy metadata so it stays in sync with models.
    allowed: dict[str, list[str]] = {}
    for table_name, table in Base.metadata.tables.items():
        allowed[table_name] = [c.name for c in table.columns]
    return SQLValidator(allowed_schema=allowed)


def _to_schema_context_response(
    ctx: RetrievedContext, rewritten: str | None
) -> SchemaContextResponse:
    return SchemaContextResponse(
        rewritten_query=rewritten,
        tables=[
            RetrievedTable(
                table=t["table"], text=t["text"], score=float(t.get("rrf", t.get("score", 0.0)))
            )
            for t in ctx.table_docs
        ],
        columns=[
            RetrievedColumn(
                table=c["table"],
                column=c["column"] or "",
                text=c["text"],
                score=float(c.get("rrf", c.get("score", 0.0))),
            )
            for c in ctx.column_docs
        ],
    )


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/schema-context", response_model=SchemaContextResponse)
def schema_context(query: str, top_k: int | None = None) -> SchemaContextResponse:
    if len(query) < 3:
        raise HTTPException(status_code=400, detail="query too short")
    ctx = _retriever().retrieve(query, top_k=top_k)
    return _to_schema_context_response(ctx, rewritten=None)


@router.post("/generate-sql", response_model=GenerateSQLResponse)
def generate_sql(req: GenerateSQLRequest) -> GenerateSQLResponse:
    state = get_generate_only_pipeline().run(
        {"query": req.query, "rewrite": req.rewrite, "top_k": req.top_k}
    )
    ctx: RetrievedContext = state.get("schema_context")
    if ctx is None or not ctx.tables:
        raise HTTPException(
            status_code=412,
            detail="No schema context retrieved. Did you run scripts/embed_schema.py?",
        )
    return GenerateSQLResponse(
        original_query=req.query,
        rewritten_query=state.get("rewritten_query", req.query),
        sql=state.get("sql", ""),
        explanation=state.get("explanation", ""),
        schema_context=_to_schema_context_response(
            ctx, rewritten=state.get("rewritten_query")
        ),
        validation_ok=bool(state.get("validation_ok")),
        validation_issues=state.get("validation_issues") or [],
    )


@router.post("/execute-query", response_model=ExecuteQueryResponse)
def execute_query(req: ExecuteQueryRequest) -> ExecuteQueryResponse:
    settings = get_settings()
    validation = _validator().validate(req.sql, max_rows=settings.sql_max_rows)
    if not validation.ok:
        raise HTTPException(status_code=400, detail={"issues": validation.issues})
    try:
        result = _executor().execute(validation.sql)
    except Exception as e:  # surface DB errors as 400 instead of 500
        log.exception("execution failed")
        raise HTTPException(status_code=400, detail=f"Execution error: {e}") from e
    return ExecuteQueryResponse(
        columns=result.columns,
        rows=result.rows,
        row_count=result.row_count,
        latency_ms=result.latency_ms,
        truncated=result.truncated,
    )


@router.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    """End-to-end: rewrite -> retrieve -> generate -> validate -> optimize -> execute -> explain."""
    state = get_full_pipeline().run(
        {"query": req.query, "rewrite": req.rewrite, "top_k": req.top_k}
    )

    ctx: RetrievedContext | None = state.get("schema_context")
    if ctx is None or not ctx.tables:
        raise HTTPException(
            status_code=412,
            detail="No schema context retrieved. Did you run scripts/embed_schema.py?",
        )

    issues = list(state.get("validation_issues") or [])
    if state.get("execution_error"):
        issues.append(f"Execution error: {state.get('execution_error')}")

    exec_payload: ExecuteQueryResponse | None = None
    r = state.get("execution_result")
    if r is not None:
        exec_payload = ExecuteQueryResponse(
            columns=r.columns,
            rows=r.rows,
            row_count=r.row_count,
            latency_ms=r.latency_ms,
            truncated=r.truncated,
        )

    return AskResponse(
        original_query=req.query,
        rewritten_query=state.get("rewritten_query", req.query),
        sql=state.get("sql", ""),
        explanation=state.get("explanation", ""),
        validation_ok=bool(state.get("validation_ok")),
        validation_issues=issues,
        optimization_notes=state.get("optimization_notes") or [],
        result=exec_payload,
        trace=[
            AgentTraceEntry(name=t.name, latency_ms=t.latency_ms, output_keys=t.output_keys)
            for t in state.trace
        ],
    )
