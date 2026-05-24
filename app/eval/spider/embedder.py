"""Embed Spider schemas into a dedicated Qdrant collection.

Each point's payload includes `database_id` so the retriever can scope to one DB
at query time. We embed table-level docs and column-level docs; no glossary or
few-shot examples (those are app-specific).
"""
from __future__ import annotations

import time

from app.eval.spider.loader import SpiderDataset, SpiderSchema
from app.monitoring.logger import get_logger
from app.rag.embeddings import OpenAIEmbedder
from app.rag.vector_store import QdrantSchemaStore, SchemaDoc

log = get_logger(__name__)

SPIDER_COLLECTION = "spider_schemas"

# Gemini free tier caps embeddings at ~5 RPM. Sleep between batches so we
# don't burn through the per-minute quota and trigger 429 / 500s.
BATCH_PACE_SECONDS = 13


def build_docs_for(schema: SpiderSchema) -> list[SchemaDoc]:
    docs: list[SchemaDoc] = []
    for t in schema.tables:
        col_list = ", ".join(t.columns)
        text = (
            f"Database `{schema.db_id}`. Table `{t.table}`. Columns: {col_list}."
        )
        docs.append(
            SchemaDoc(
                doc_id=f"{schema.db_id}::table::{t.table}",
                table=t.table,
                column=None,
                kind="table",
                text=text,
                metadata={"database_id": schema.db_id, "columns": list(t.columns)},
            )
        )
        for c in t.columns:
            ctext = f"Database `{schema.db_id}`. Column `{t.table}.{c}`."
            docs.append(
                SchemaDoc(
                    doc_id=f"{schema.db_id}::col::{t.table}::{c}",
                    table=t.table,
                    column=c,
                    kind="column",
                    text=ctext,
                    metadata={"database_id": schema.db_id},
                )
            )
    return docs


def embed_spider_corpus(
    dataset: SpiderDataset | None = None,
    db_ids: list[str] | None = None,
    reset: bool = True,
    batch_size: int = 64,
) -> int:
    ds = dataset or SpiderDataset()
    embedder = OpenAIEmbedder()
    store = QdrantSchemaStore(collection=SPIDER_COLLECTION)

    if reset:
        log.info("Resetting Qdrant collection '%s' (dim=%d)", SPIDER_COLLECTION, embedder.dim)
        store.reset_collection(vector_size=embedder.dim)
    else:
        store.ensure_collection(vector_size=embedder.dim)

    targets = db_ids or ds.all_db_ids()
    log.info("Embedding %d Spider databases", len(targets))

    total = 0
    first_batch = True
    for db_id in targets:
        try:
            schema = ds.introspect(db_id)
        except FileNotFoundError as e:
            log.warning("Skipping %s: %s", db_id, e)
            continue
        docs = build_docs_for(schema)
        for i in range(0, len(docs), batch_size):
            if not first_batch:
                time.sleep(BATCH_PACE_SECONDS)
            chunk = docs[i : i + batch_size]
            vectors = embedder.embed([d.text for d in chunk])
            store.upsert(chunk, vectors)
            first_batch = False
        total += len(docs)
        log.info("  %s -> %d docs", db_id, len(docs))
    return total
