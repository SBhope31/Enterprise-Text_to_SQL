from app.agents.base import PipelineState
from app.sql_generation.generator import SQLGenerator


class SQLGenerationAgent:
    name = "sql_generation"

    def __init__(self, generator: SQLGenerator | None = None) -> None:
        self._generator = generator or SQLGenerator()

    def run(self, state: PipelineState) -> None:
        question = state.get("query")
        schema_text = state.get("schema_context_text", "")
        result = self._generator.generate(question, schema_text)
        state.set("sql", result.sql)
        state.set("explanation", result.explanation)
