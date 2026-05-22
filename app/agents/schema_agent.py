from app.agents.base import PipelineState
from app.rag.retriever import HybridRetriever


class SchemaRetrievalAgent:
    name = "schema_retrieval"

    def __init__(self, retriever: HybridRetriever | None = None) -> None:
        self._retriever = retriever or HybridRetriever()

    def run(self, state: PipelineState) -> None:
        query = state.get("rewritten_query") or state.get("query")
        top_k = state.get("top_k")
        ctx = self._retriever.retrieve(query, top_k=top_k)
        state.set("schema_context", ctx)
        state.set("schema_context_text", ctx.render())
