from typing import Any
from pydantic import BaseModel, Field


class GenerateSQLRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=1000)
    rewrite: bool = Field(True, description="Run query rewriting before retrieval.")
    top_k: int | None = Field(None, ge=1, le=20)


class RetrievedTable(BaseModel):
    table: str
    text: str
    score: float


class RetrievedColumn(BaseModel):
    table: str
    column: str
    text: str
    score: float


class SchemaContextResponse(BaseModel):
    tables: list[RetrievedTable]
    columns: list[RetrievedColumn]
    rewritten_query: str | None = None


class GenerateSQLResponse(BaseModel):
    original_query: str
    rewritten_query: str
    sql: str
    explanation: str
    schema_context: SchemaContextResponse
    validation_ok: bool
    validation_issues: list[str]


class ExecuteQueryRequest(BaseModel):
    sql: str = Field(..., min_length=6)


class ExecuteQueryResponse(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    latency_ms: float
    truncated: bool


class AskRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=1000)
    rewrite: bool = True
    top_k: int | None = Field(None, ge=1, le=20)


class AgentTraceEntry(BaseModel):
    name: str
    latency_ms: float
    output_keys: list[str]


class AskResponse(BaseModel):
    original_query: str
    rewritten_query: str
    sql: str
    explanation: str
    validation_ok: bool
    validation_issues: list[str]
    optimization_notes: list[str] = []
    result: ExecuteQueryResponse | None = None
    trace: list[AgentTraceEntry] = []
