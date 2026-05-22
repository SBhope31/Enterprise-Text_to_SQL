from app.validation.validator import SQLValidator


SCHEMA = {
    "customers": ["id", "name", "email", "country", "region", "created_at"],
    "orders": ["id", "customer_id", "order_date", "status", "total_amount"],
    "order_items": ["id", "order_id", "product_id", "quantity", "unit_price"],
    "products": ["id", "name", "category", "price", "stock"],
    "returns": ["id", "order_item_id", "return_date", "reason", "refund_amount"],
}


def make_validator() -> SQLValidator:
    return SQLValidator(allowed_schema=SCHEMA)


def test_simple_select_passes():
    v = make_validator()
    r = v.validate("SELECT id, name FROM customers", max_rows=100)
    assert r.ok, r.issues
    assert "LIMIT 100" in r.sql.upper()


def test_join_passes():
    v = make_validator()
    sql = """
        SELECT c.name, SUM(o.total_amount) AS revenue
        FROM customers c
        JOIN orders o ON o.customer_id = c.id
        GROUP BY c.name
        ORDER BY revenue DESC
        LIMIT 5
    """
    r = v.validate(sql, max_rows=100)
    assert r.ok, r.issues


def test_destructive_blocked():
    v = make_validator()
    for sql in [
        "DELETE FROM customers",
        "DROP TABLE customers",
        "UPDATE customers SET name='x'",
        "INSERT INTO customers (name) VALUES ('x')",
        "ALTER TABLE customers ADD COLUMN x INT",
        "TRUNCATE TABLE customers",
    ]:
        r = v.validate(sql, max_rows=100)
        assert not r.ok, sql


def test_unknown_table_flagged():
    v = make_validator()
    r = v.validate("SELECT * FROM unicorns", max_rows=100)
    assert not r.ok
    assert any("Unknown tables" in m for m in r.issues)


def test_unknown_column_flagged():
    v = make_validator()
    r = v.validate("SELECT c.not_real FROM customers c", max_rows=100)
    assert not r.ok
    assert any("Unknown columns" in m for m in r.issues)


def test_limit_injected_when_missing():
    v = make_validator()
    r = v.validate("SELECT id FROM customers", max_rows=50)
    assert r.ok
    assert "LIMIT 50" in r.sql.upper()


def test_limit_clamped_when_too_high():
    v = make_validator()
    r = v.validate("SELECT id FROM customers LIMIT 100000", max_rows=500)
    assert r.ok
    assert "LIMIT 500" in r.sql.upper()
