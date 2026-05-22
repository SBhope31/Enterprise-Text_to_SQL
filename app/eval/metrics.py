"""Pure metric functions for retrieval and SQL evaluation."""
from __future__ import annotations

from typing import Any, Iterable


# ---------------- Retrieval metrics ----------------

def recall_at_k(retrieved: list[str], relevant: Iterable[str], k: int) -> float:
    """Fraction of relevant items present in the top-k retrieved list."""
    rel = set(relevant)
    if not rel:
        return 0.0
    top = set(retrieved[:k])
    return len(top & rel) / len(rel)


def precision_at_k(retrieved: list[str], relevant: Iterable[str], k: int) -> float:
    """Fraction of top-k retrieved that are relevant."""
    rel = set(relevant)
    top = retrieved[:k]
    if not top:
        return 0.0
    return sum(1 for r in top if r in rel) / len(top)


def reciprocal_rank(retrieved: list[str], relevant: Iterable[str]) -> float:
    """1 / rank of first relevant item, or 0 if not present."""
    rel = set(relevant)
    for i, item in enumerate(retrieved, start=1):
        if item in rel:
            return 1.0 / i
    return 0.0


def mean_reciprocal_rank(samples: list[tuple[list[str], Iterable[str]]]) -> float:
    if not samples:
        return 0.0
    return sum(reciprocal_rank(r, rel) for r, rel in samples) / len(samples)


# ---------------- SQL generation metrics ----------------

def normalize_sql(sql: str) -> str:
    return " ".join(sql.lower().split()).rstrip(";")


def exact_match(generated: str, ground_truth: str) -> bool:
    return normalize_sql(generated) == normalize_sql(ground_truth)


def result_set_equal(
    a_columns: list[str], a_rows: list[list[Any]],
    b_columns: list[str], b_rows: list[list[Any]],
    order_sensitive: bool = False,
) -> bool:
    """Compare two result sets. Column names are ignored (positional comparison).
    Numeric values are compared with a small tolerance.
    """
    if len(a_columns) != len(b_columns):
        return False
    if len(a_rows) != len(b_rows):
        return False

    def canon_value(v: Any) -> Any:
        if isinstance(v, float):
            return round(v, 4)
        return v

    def canon_row(row: list[Any]) -> tuple:
        return tuple(canon_value(v) for v in row)

    a = [canon_row(r) for r in a_rows]
    b = [canon_row(r) for r in b_rows]
    if order_sensitive:
        return a == b
    return sorted(a, key=lambda x: tuple(str(v) for v in x)) == sorted(
        b, key=lambda x: tuple(str(v) for v in x)
    )


def hallucination(
    used_tables: list[str], used_columns: list[tuple[str, str]],
    allowed_schema: dict[str, set[str]],
) -> bool:
    """Returns True if the SQL references any table or column not present in the schema."""
    for t in used_tables:
        if t and t.lower() not in allowed_schema:
            return True
    for tbl, col in used_columns:
        if not tbl or col == "*":
            continue
        if tbl.lower() not in allowed_schema:
            return True
        if col.lower() not in allowed_schema[tbl.lower()]:
            return True
    return False
