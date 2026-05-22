"""Optional Ragas-based evaluation.

Ragas treats the retrieved schema text as 'context' and the generated SQL +
explanation as the 'answer'. Faithfulness measures whether the answer is
grounded in the context; context_precision / context_recall measure retrieval.

Run only after the main `runner.evaluate()` because it reuses its results.
This is OPTIONAL because Ragas pulls in transformers/datasets which are heavy.
"""
from __future__ import annotations

from typing import Any

from app.eval.runner import ItemResult


def run_ragas(items: list[ItemResult]) -> dict[str, Any]:
    try:
        from datasets import Dataset
        from ragas import evaluate as ragas_evaluate
        from ragas.metrics import (
            answer_relevancy, context_precision, context_recall, faithfulness,
        )
    except ImportError as e:
        return {"error": f"Ragas/datasets not installed: {e}"}

    rows = []
    for it in items:
        rows.append(
            {
                "question": it.question,
                "answer": f"SQL:\n{it.sql}",
                "contexts": [", ".join(it.retrieved_tables)],
                "ground_truth": f"SQL:\n{it.ground_truth_sql}",
            }
        )
    ds = Dataset.from_list(rows)
    result = ragas_evaluate(
        ds,
        metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
    )
    return result.to_pandas().mean(numeric_only=True).to_dict()
