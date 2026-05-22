from app.agents.base import PipelineState
from app.execution.executor import SafeExecutor
from app.monitoring.logger import get_logger

log = get_logger(__name__)


class ExecutionAgent:
    name = "execution"

    def __init__(self, executor: SafeExecutor | None = None) -> None:
        self._executor = executor or SafeExecutor()

    def run(self, state: PipelineState) -> None:
        if not state.get("validation_ok"):
            state.set("execution_result", None)
            return
        sql = state.get("sql", "")
        try:
            result = self._executor.execute(sql)
            state.set("execution_result", result)
        except Exception as e:
            log.exception("execution failed")
            state.set("execution_result", None)
            state.set("execution_error", str(e))
