"""Business glossary and few-shot SQL examples used by the retriever and generator."""
from dataclasses import dataclass


@dataclass(frozen=True)
class GlossaryEntry:
    term: str
    definition: str
    tables: tuple[str, ...]


@dataclass(frozen=True)
class SampleQuery:
    question: str
    sql: str
    tables: tuple[str, ...]


BUSINESS_GLOSSARY: list[GlossaryEntry] = [
    GlossaryEntry(
        term="revenue",
        definition="Revenue is the sum of order_items.quantity * order_items.unit_price for completed orders. Use orders.total_amount only if grouping at the order level and trusting the precomputed total.",
        tables=("orders", "order_items"),
    ),
    GlossaryEntry(
        term="completed orders",
        definition="Orders where orders.status = 'completed'. Exclude 'pending', 'cancelled', and 'refunded' unless the question explicitly asks otherwise.",
        tables=("orders",),
    ),
    GlossaryEntry(
        term="return rate",
        definition="Return rate for a product = COUNT(DISTINCT returns.id) / NULLIF(COUNT(DISTINCT order_items.id), 0) where order_items.product_id matches.",
        tables=("returns", "order_items", "products"),
    ),
    GlossaryEntry(
        term="delivery time",
        definition="Delivery time = shipments.delivered_date - shipments.shipped_date (in days). Only valid when both columns are non-NULL.",
        tables=("shipments",),
    ),
    GlossaryEntry(
        term="active customer",
        definition="A customer is 'active' if they have placed at least one order with status='completed' in the last 90 days.",
        tables=("customers", "orders"),
    ),
    GlossaryEntry(
        term="payment success rate",
        definition="Payment success rate = COUNT(*) FILTER (WHERE payments.status = 'succeeded') / COUNT(*) over the payments table for the period.",
        tables=("payments",),
    ),
    GlossaryEntry(
        term="tenure",
        definition="Employee tenure (in years) = (CURRENT_DATE - employees.hire_date) / 365.0.",
        tables=("employees",),
    ),
    GlossaryEntry(
        term="region",
        definition="Region is the high-level sales geography stored on customers.region with values: NA, EMEA, APAC, LATAM. Do NOT confuse with customers.country.",
        tables=("customers",),
    ),
]


SAMPLE_QUERIES: list[SampleQuery] = [
    SampleQuery(
        question="Show top 5 customers by revenue in the last 3 months.",
        sql=(
            "SELECT c.name, SUM(oi.quantity * oi.unit_price) AS revenue\n"
            "FROM customers c\n"
            "JOIN orders o ON o.customer_id = c.id\n"
            "JOIN order_items oi ON oi.order_id = o.id\n"
            "WHERE o.status = 'completed'\n"
            "  AND o.order_date >= CURRENT_DATE - INTERVAL '3 months'\n"
            "GROUP BY c.name\n"
            "ORDER BY revenue DESC\n"
            "LIMIT 5"
        ),
        tables=("customers", "orders", "order_items"),
    ),
    SampleQuery(
        question="Which products had the highest return rate last year?",
        sql=(
            "SELECT p.name,\n"
            "       COUNT(DISTINCT r.id)::float / NULLIF(COUNT(DISTINCT oi.id), 0) AS return_rate\n"
            "FROM products p\n"
            "JOIN order_items oi ON oi.product_id = p.id\n"
            "JOIN orders o ON o.id = oi.order_id\n"
            "LEFT JOIN returns r ON r.order_item_id = oi.id\n"
            "WHERE o.order_date >= CURRENT_DATE - INTERVAL '1 year'\n"
            "GROUP BY p.name\n"
            "HAVING COUNT(DISTINCT oi.id) > 5\n"
            "ORDER BY return_rate DESC\n"
            "LIMIT 10"
        ),
        tables=("products", "order_items", "orders", "returns"),
    ),
    SampleQuery(
        question="What is the monthly revenue trend for the last 12 months?",
        sql=(
            "SELECT DATE_TRUNC('month', o.order_date) AS month,\n"
            "       SUM(oi.quantity * oi.unit_price) AS revenue\n"
            "FROM orders o\n"
            "JOIN order_items oi ON oi.order_id = o.id\n"
            "WHERE o.status = 'completed'\n"
            "  AND o.order_date >= CURRENT_DATE - INTERVAL '12 months'\n"
            "GROUP BY 1\n"
            "ORDER BY 1"
        ),
        tables=("orders", "order_items"),
    ),
    SampleQuery(
        question="Average delivery time by carrier in the last quarter.",
        sql=(
            "SELECT s.carrier,\n"
            "       AVG(s.delivered_date - s.shipped_date) AS avg_days_to_deliver\n"
            "FROM shipments s\n"
            "WHERE s.status = 'delivered'\n"
            "  AND s.delivered_date >= CURRENT_DATE - INTERVAL '3 months'\n"
            "GROUP BY s.carrier\n"
            "ORDER BY avg_days_to_deliver"
        ),
        tables=("shipments",),
    ),
    SampleQuery(
        question="Payment success rate by method this month.",
        sql=(
            "SELECT p.method,\n"
            "       COUNT(*) FILTER (WHERE p.status = 'succeeded')::float / COUNT(*) AS success_rate\n"
            "FROM payments p\n"
            "WHERE p.payment_date >= DATE_TRUNC('month', CURRENT_DATE)\n"
            "GROUP BY p.method\n"
            "ORDER BY success_rate DESC"
        ),
        tables=("payments",),
    ),
    SampleQuery(
        question="Average employee tenure by department.",
        sql=(
            "SELECT e.department,\n"
            "       AVG((CURRENT_DATE - e.hire_date) / 365.0) AS avg_tenure_years\n"
            "FROM employees e\n"
            "GROUP BY e.department\n"
            "ORDER BY avg_tenure_years DESC"
        ),
        tables=("employees",),
    ),
]
