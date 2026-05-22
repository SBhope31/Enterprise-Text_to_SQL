from dataclasses import dataclass
from typing import Any

from rank_bm25 import BM25Okapi

from app.config import get_settings
from app.rag.embeddings import OpenAIEmbedder
from app.rag.vector_store import QdrantSchemaStore


def _tokenize(text: str) -> list[str]:
    return [t for t in text.lower().replace(".", " ").replace("_", " ").split() if t]


@dataclass
class RetrievedContext:
    tables: list[str]
    table_docs: list[dict[str, Any]]
    column_docs: list[dict[str, Any]]
    glossary_docs: list[dict[str, Any]]
    sample_query_docs: list[dict[str, Any]]
    raw_hits: list[dict[str, Any]]

    def render(self) -> str:
        lines: list[str] = []
        for t in self.table_docs:
            lines.append(f"TABLE {t['table']}: {t['text']}")
        for c in self.column_docs:
            lines.append(f"  COLUMN {c['table']}.{c['column']}: {c['text']}")
        if self.glossary_docs:
            lines.append("")
            lines.append("BUSINESS DEFINITIONS:")
            for g in self.glossary_docs:
                term = g.get("term") or "?"
                lines.append(f"- {term}: {g.get('definition', '')}")
        if self.sample_query_docs:
            lines.append("")
            lines.append("RELATED EXAMPLE QUERIES (for style only, do not copy verbatim):")
            for s in self.sample_query_docs:
                lines.append(f"Q: {s.get('question', '')}")
                lines.append("SQL:")
                lines.append(s.get("sql", ""))
                lines.append("")
        return "\n".join(lines)


class HybridRetriever:
    """Dense (Qdrant) + BM25 fusion using Reciprocal Rank Fusion.

    When `db_id` is set, both dense search and the BM25 corpus are restricted
    to docs whose payload `database_id` matches. This is how Spider's
    multi-DB eval scopes retrieval to the right schema.
    """

    def __init__(
        self,
        store: QdrantSchemaStore | None = None,
        embedder: OpenAIEmbedder | None = None,
        db_id: str | None = None,
    ) -> None:
        self._store = store or QdrantSchemaStore()
        self._embedder = embedder or OpenAIEmbedder()
        self._db_id = db_id
        self._corpus: list[dict[str, Any]] = []
        self._bm25: BM25Okapi | None = None
        self._refresh_corpus()

    def _payload_filter(self) -> dict[str, Any] | None:
        return {"database_id": self._db_id} if self._db_id else None

    def _refresh_corpus(self) -> None:
        self._corpus = self._store.scroll_all(payload_filters=self._payload_filter())
        if self._corpus:
            tokenized = [_tokenize(d["text"]) for d in self._corpus]
            self._bm25 = BM25Okapi(tokenized)
        else:
            self._bm25 = None

    def retrieve(self, query: str, top_k: int | None = None) -> RetrievedContext:
        settings = get_settings()
        k = top_k or settings.retrieval_top_k

        dense_hits = self._store.search(
            self._embedder.embed_one(query),
            top_k=k * 2,
            payload_filters=self._payload_filter(),
        )
        sparse_hits: list[dict[str, Any]] = []
        if self._bm25 and self._corpus:
            scores = self._bm25.get_scores(_tokenize(query))
            ranked = sorted(
                zip(self._corpus, scores), key=lambda x: x[1], reverse=True
            )[: k * 2]
            sparse_hits = [{"score": float(s), **d} for d, s in ranked if s > 0]

        # Reciprocal Rank Fusion
        rrf_k = 60
        fused: dict[str, dict[str, Any]] = {}

        def add(hits: list[dict[str, Any]]) -> None:
            for rank, hit in enumerate(hits):
                key = hit.get("doc_id") or f"{hit.get('table')}::{hit.get('column')}"
                cur = fused.setdefault(key, {**hit, "rrf": 0.0})
                cur["rrf"] += 1.0 / (rrf_k + rank + 1)

        add(dense_hits)
        add(sparse_hits)
        ranked = sorted(fused.values(), key=lambda x: x["rrf"], reverse=True)

        # Pick top-k tables from schema-kind hits; pull columns for those tables.
        schema_kinds = {"table", "column"}
        seen_tables: list[str] = []
        for hit in ranked:
            if hit.get("kind") not in schema_kinds:
                continue
            t = hit.get("table")
            if t and t not in seen_tables:
                seen_tables.append(t)
            if len(seen_tables) >= k:
                break

        table_docs = [
            h for h in ranked
            if h.get("kind") == "table" and h.get("table") in seen_tables
        ]
        column_docs = [
            h for h in ranked
            if h.get("kind") == "column" and h.get("table") in seen_tables
        ]

        # Ensure each chosen table has a table-doc entry even if only columns ranked.
        present = {t["table"] for t in table_docs}
        for t in seen_tables:
            if t not in present:
                for c in self._corpus:
                    if c.get("kind") == "table" and c.get("table") == t:
                        table_docs.append({"score": 0.0, "rrf": 0.0, **c})
                        break

        # Glossary + sample queries: keep top of their respective kinds, filtered
        # to entries that touch at least one retrieved table.
        glossary_docs: list[dict[str, Any]] = []
        sample_query_docs: list[dict[str, Any]] = []
        seen_set = set(seen_tables)
        for h in ranked:
            kind = h.get("kind")
            tables = set(h.get("tables") or []) | ({h.get("table")} if h.get("table") else set())
            if not (tables & seen_set):
                continue
            if kind == "glossary" and len(glossary_docs) < 4:
                glossary_docs.append(h)
            elif kind == "sample_query" and len(sample_query_docs) < 2:
                sample_query_docs.append(h)

        return RetrievedContext(
            tables=seen_tables,
            table_docs=table_docs,
            column_docs=column_docs,
            glossary_docs=glossary_docs,
            sample_query_docs=sample_query_docs,
            raw_hits=ranked[: k * 2],
        )
