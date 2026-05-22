import time
from dataclasses import dataclass
from decimal import Decimal
from datetime import date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.config import get_settings
from app.db.session import engine as default_engine


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


@dataclass
class ExecutionResult:
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    latency_ms: float
    truncated: bool


class SafeExecutor:
    """Executes a SELECT against a chosen engine with timeout + row cap.

    Defaults to the application Postgres engine. Spider eval passes a SQLite
    engine so each Spider DB can be queried directly.
    """

    def __init__(self, engine: Engine | None = None) -> None:
        self._settings = get_settings()
        self._engine: Engine = engine or default_engine

    def execute(self, sql: str) -> ExecutionResult:
        timeout_ms = self._settings.sql_exec_timeout_seconds * 1000
        max_rows = self._settings.sql_max_rows
        is_postgres = self._engine.dialect.name == "postgresql"

        start = time.perf_counter()
        with self._engine.connect() as conn:
            if is_postgres:
                conn.execute(text("SET TRANSACTION READ ONLY"))
                conn.execute(text(f"SET LOCAL statement_timeout = {timeout_ms}"))
            # SQLite executes read-only by default for SELECT; timeout is set on engine.
            result = conn.execute(text(sql))
            columns = list(result.keys())
            raw_rows = result.fetchmany(max_rows + 1)

        latency_ms = (time.perf_counter() - start) * 1000.0
        truncated = len(raw_rows) > max_rows
        rows = [[_jsonable(v) for v in r] for r in raw_rows[:max_rows]]
        return ExecutionResult(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            latency_ms=latency_ms,
            truncated=truncated,
        )
