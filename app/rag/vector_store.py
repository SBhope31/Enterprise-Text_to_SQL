from dataclasses import dataclass
from typing import Any
import uuid

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from app.config import get_settings


@dataclass
class SchemaDoc:
    doc_id: str
    table: str
    column: str | None
    kind: str  # "table" | "column"
    text: str
    metadata: dict[str, Any]


class QdrantSchemaStore:
    def __init__(self, collection: str | None = None) -> None:
        settings = get_settings()
        self._collection = collection or settings.qdrant_collection
        self._client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)

    @property
    def collection(self) -> str:
        return self._collection

    def reset_collection(self, vector_size: int) -> None:
        if self._client.collection_exists(self._collection):
            self._client.delete_collection(self._collection)
        self._client.create_collection(
            collection_name=self._collection,
            vectors_config=qm.VectorParams(size=vector_size, distance=qm.Distance.COSINE),
        )

    def ensure_collection(self, vector_size: int) -> None:
        if not self._client.collection_exists(self._collection):
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=qm.VectorParams(size=vector_size, distance=qm.Distance.COSINE),
            )

    def upsert(self, docs: list[SchemaDoc], vectors: list[list[float]]) -> None:
        if not docs:
            return
        points = [
            qm.PointStruct(
                id=str(uuid.uuid4()),
                vector=vec,
                payload={
                    "doc_id": d.doc_id,
                    "table": d.table,
                    "column": d.column,
                    "kind": d.kind,
                    "text": d.text,
                    **d.metadata,
                },
            )
            for d, vec in zip(docs, vectors)
        ]
        self._client.upsert(collection_name=self._collection, points=points)

    def _filter_for(self, payload_filters: dict[str, Any] | None) -> qm.Filter | None:
        if not payload_filters:
            return None
        return qm.Filter(
            must=[
                qm.FieldCondition(key=k, match=qm.MatchValue(value=v))
                for k, v in payload_filters.items()
            ]
        )

    def search(
        self,
        query_vector: list[float],
        top_k: int = 8,
        payload_filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        hits = self._client.search(
            collection_name=self._collection,
            query_vector=query_vector,
            limit=top_k,
            with_payload=True,
            query_filter=self._filter_for(payload_filters),
        )
        return [{"score": h.score, **(h.payload or {})} for h in hits]

    def scroll_all(
        self, payload_filters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        offset: Any = None
        scroll_filter = self._filter_for(payload_filters)
        while True:
            points, offset = self._client.scroll(
                collection_name=self._collection,
                limit=256,
                offset=offset,
                with_payload=True,
                scroll_filter=scroll_filter,
            )
            for p in points:
                if p.payload:
                    out.append(p.payload)
            if offset is None:
                break
        return out
