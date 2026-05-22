from app.eval.metrics import (
    exact_match, hallucination, mean_reciprocal_rank,
    precision_at_k, recall_at_k, result_set_equal,
)


def test_recall_at_k():
    assert recall_at_k(["a", "b", "c"], {"a", "b"}, k=3) == 1.0
    assert recall_at_k(["a", "b", "c"], {"a", "b"}, k=1) == 0.5
    assert recall_at_k(["x", "y"], {"a"}, k=5) == 0.0
    assert recall_at_k(["a"], set(), k=5) == 0.0


def test_precision_at_k():
    assert precision_at_k(["a", "b", "c"], {"a", "b"}, k=3) == 2 / 3
    assert precision_at_k(["a"], {"a"}, k=1) == 1.0
    assert precision_at_k([], {"a"}, k=5) == 0.0


def test_mrr():
    samples = [
        (["a", "b", "c"], {"b"}),  # rank 2 -> 1/2
        (["x", "y"], {"a"}),       # not found -> 0
        (["c"], {"c"}),            # rank 1 -> 1.0
    ]
    assert abs(mean_reciprocal_rank(samples) - (0.5 + 0 + 1.0) / 3) < 1e-9


def test_exact_match_ignores_whitespace_and_semicolons():
    assert exact_match("SELECT 1", "select   1;")
    assert not exact_match("SELECT 1", "SELECT 2")


def test_result_set_equal_unordered():
    a_cols, a_rows = ["x"], [[1], [2], [3]]
    b_cols, b_rows = ["y"], [[3], [1], [2]]
    assert result_set_equal(a_cols, a_rows, b_cols, b_rows)


def test_result_set_equal_order_sensitive():
    a_cols, a_rows = ["x"], [[1], [2]]
    b_cols, b_rows = ["x"], [[2], [1]]
    assert not result_set_equal(a_cols, a_rows, b_cols, b_rows, order_sensitive=True)
    assert result_set_equal(a_cols, a_rows, b_cols, b_rows, order_sensitive=False)


def test_hallucination():
    schema = {"customers": {"id", "name"}}
    assert hallucination(["customers"], [("customers", "id")], schema) is False
    assert hallucination(["unicorns"], [], schema) is True
    assert hallucination(["customers"], [("customers", "fake_col")], schema) is True
    # unqualified column or star is skipped
    assert hallucination(["customers"], [("", "*")], schema) is False
