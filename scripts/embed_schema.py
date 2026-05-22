"""Embed schema docs into Qdrant.

Usage:
    python -m scripts.embed_schema
"""
from __future__ import annotations

from app.db.models import Base, COLUMN_DESCRIPTIONS, SCHEMA_DESCRIPTIONS
from app.rag.embeddings import OpenAIEmbedder
from app.rag.knowledge import BUSINESS_GLOSSARY, SAMPLE_QUERIES
from app.rag.vector_store import QdrantSchemaStore, SchemaDoc


def build_schema_docs() -> list[SchemaDoc]:
    docs: list[SchemaDoc] = []
    for table_name, table in Base.metadata.tables.items():
        col_names = [c.name for c in table.columns]
        table_desc = SCHEMA_DESCRIPTIONS.get(table_name, "")
        table_text = (
            f"Table `{table_name}`. Columns: {', '.join(col_names)}. {table_desc}"
        )
        docs.append(
            SchemaDoc(
                doc_id=f"table::{table_name}",
                table=table_name,
                column=None,
                kind="table",
                text=table_text,
                metadata={"columns": col_names},
            )
        )
        for c in table.columns:
            col_desc = COLUMN_DESCRIPTIONS.get((table_name, c.name), "")
            col_text = (
                f"Column `{table_name}.{c.name}` of type {c.type}. {col_desc}"
            )
            docs.append(
                SchemaDoc(
                    doc_id=f"column::{table_name}::{c.name}",
                    table=table_name,
                    column=c.name,
                    kind="column",
                    text=col_text,
                    metadata={"sql_type": str(c.type)},
                )
            )

    # Business glossary -- one doc per term.
    for entry in BUSINESS_GLOSSARY:
        docs.append(
            SchemaDoc(
                doc_id=f"glossary::{entry.term}",
                table=entry.tables[0] if entry.tables else "",
                column=None,
                kind="glossary",
                text=f"Glossary: {entry.term}. {entry.definition}",
                metadata={
                    "term": entry.term,
                    "definition": entry.definition,
                    "tables": list(entry.tables),
                },
            )
        )

    # Few-shot sample queries -- one doc per pair.
    for i, sq in enumerate(SAMPLE_QUERIES):
        docs.append(
            SchemaDoc(
                doc_id=f"sample::{i}",
                table=sq.tables[0] if sq.tables else "",
                column=None,
                kind="sample_query",
                text=f"Example question: {sq.question}\nSQL:\n{sq.sql}",
                metadata={
                    "question": sq.question,
                    "sql": sq.sql,
                    "tables": list(sq.tables),
                },
            )
        )
    return docs


def main() -> None:
    embedder = OpenAIEmbedder()
    store = QdrantSchemaStore()

    print(f"Resetting Qdrant collection '{store.collection}' (dim={embedder.dim})...")
    store.reset_collection(vector_size=embedder.dim)

    docs = build_schema_docs()
    print(f"Built {len(docs)} schema docs. Embedding...")

    # Batch embed to stay under API limits.
    batch_size = 64
    for i in range(0, len(docs), batch_size):
        chunk = docs[i : i + batch_size]
        vectors = embedder.embed([d.text for d in chunk])
        store.upsert(chunk, vectors)
        print(f"  upserted {i + len(chunk)}/{len(docs)}")

    print("Done.")


if __name__ == "__main__":
    main()
