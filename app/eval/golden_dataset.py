"""Handcrafted evaluation dataset for the bundled e-commerce sample DB.

Each item has:
- question: the natural-language question
- relevant_tables: tables that *should* appear in the retrieved schema context
- ground_truth_sql: a correct reference SQL the executor can run for result-set comparison
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class GoldenItem:
    question: str
    relevant_tables: tuple[str, ...]
    ground_truth_sql: str


GOLDEN_SET: list[GoldenItem] = [
    GoldenItem(
        question="How many customers do we have in total?",
        relevant_tables=("customers",),
        ground_truth_sql="SELECT COUNT(*) AS n FROM customers",
    ),
    GoldenItem(
        question="List the 5 most expensive products.",
        relevant_tables=("products",),
        ground_truth_sql="SELECT name, price FROM products ORDER BY price DESC LIMIT 5",
    ),
    GoldenItem(
        question="What is total revenue from completed orders in the last 90 days?",
        relevant_tables=("orders", "order_items"),
        ground_truth_sql=(
            "SELECT SUM(oi.quantity * oi.unit_price) AS revenue "
            "FROM orders o JOIN order_items oi ON oi.order_id = o.id "
            "WHERE o.status = 'completed' "
            "AND o.order_date >= CURRENT_DATE - INTERVAL '90 days'"
        ),
    ),
    GoldenItem(
        question="Which region has the most customers?",
        relevant_tables=("customers",),
        ground_truth_sql=(
            "SELECT region, COUNT(*) AS n FROM customers "
            "GROUP BY region ORDER BY n DESC LIMIT 1"
        ),
    ),
    GoldenItem(
        question="How many returns happened last year?",
        relevant_tables=("returns",),
        ground_truth_sql=(
            "SELECT COUNT(*) AS n FROM returns "
            "WHERE return_date >= CURRENT_DATE - INTERVAL '1 year'"
        ),
    ),
    GoldenItem(
        question="Average delivery time for delivered shipments by carrier.",
        relevant_tables=("shipments",),
        ground_truth_sql=(
            "SELECT carrier, AVG(delivered_date - shipped_date) AS avg_days "
            "FROM shipments WHERE status = 'delivered' "
            "GROUP BY carrier ORDER BY avg_days"
        ),
    ),
    GoldenItem(
        question="Payment success rate overall.",
        relevant_tables=("payments",),
        ground_truth_sql=(
            "SELECT COUNT(*) FILTER (WHERE status = 'succeeded')::float / COUNT(*) "
            "AS success_rate FROM payments"
        ),
    ),
    GoldenItem(
        question="How many employees are in the Engineering department?",
        relevant_tables=("employees",),
        ground_truth_sql=(
            "SELECT COUNT(*) AS n FROM employees WHERE department = 'Engineering'"
        ),
    ),
    GoldenItem(
        question="Top 3 categories by units sold.",
        relevant_tables=("products", "order_items"),
        ground_truth_sql=(
            "SELECT p.category, SUM(oi.quantity) AS units "
            "FROM products p JOIN order_items oi ON oi.product_id = p.id "
            "GROUP BY p.category ORDER BY units DESC LIMIT 3"
        ),
    ),
    GoldenItem(
        question="How many cancelled orders are there?",
        relevant_tables=("orders",),
        ground_truth_sql="SELECT COUNT(*) AS n FROM orders WHERE status = 'cancelled'",
    ),
]
