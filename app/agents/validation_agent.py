from app.agents.base import PipelineState
from app.config import get_settings
from app.validation.validator import SQLValidator


class ValidationAgent:
    name = "validation"

    def __init__(self, validator: SQLValidator) -> None:
        self._validator = validator

    def run(self, state: PipelineState) -> None:
        sql = state.get("sql", "")
        max_rows = get_settings().sql_max_rows
        result = self._validator.validate(sql, max_rows=max_rows)
        state.set("sql", result.sql)
        state.set("validation_ok", result.ok)
        state.set("validation_issues", result.issues)
        state.set("validation_used_tables", result.used_tables)
        state.set("validation_used_columns", result.used_columns)
