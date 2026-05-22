from app.agents.base import PipelineState
from app.rag.query_rewriter import QueryRewriter


class RewriteAgent:
    name = "rewrite"

    def __init__(self, rewriter: QueryRewriter | None = None) -> None:
        self._rewriter = rewriter or QueryRewriter()

    def run(self, state: PipelineState) -> None:
        query: str = state.get("query")
        if state.get("rewrite", True):
            rewritten = self._rewriter.rewrite(query)
        else:
            rewritten = query
        state.set("rewritten_query", rewritten)
