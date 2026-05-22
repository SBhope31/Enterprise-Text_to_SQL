"""ExplanationAgent.

Refines the one-liner explanation produced during SQL generation by adding the
list of tables actually used and (if executed) the row count. Kept deterministic
to avoid an extra LLM call -- swap in an LLM-based version if needed.
"""
from app.agents.base import PipelineState


class ExplanationAgent:
    name = "explanation"

    def run(self, state: PipelineState) -> None:
        explanation = state.get("explanation", "") or ""
        used_tables = state.get("validation_used_tables") or []
        exec_result = state.get("execution_result")

        parts = [explanation.strip()] if explanation.strip() else []
        if used_tables:
            parts.append(f"Uses table(s): {', '.join(used_tables)}.")
        if exec_result is not None:
            row_count = getattr(exec_result, "row_count", None)
            if row_count is not None:
                parts.append(f"Returned {row_count} row(s).")
        state.set("explanation", " ".join(p for p in parts if p))
