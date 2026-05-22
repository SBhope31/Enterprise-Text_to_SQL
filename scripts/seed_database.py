"""Create tables and populate sample e-commerce data.

Usage:
    python -m scripts.seed_database
"""
from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import (
    Base, Customer, Employee, Order, OrderItem, Payment, Product, Return, Shipment,
)
from app.db.session import engine, get_session


COUNTRIES = [
    ("United States", "NA"), ("Canada", "NA"), ("Mexico", "LATAM"),
    ("Brazil", "LATAM"), ("United Kingdom", "EMEA"), ("Germany", "EMEA"),
    ("France", "EMEA"), ("India", "APAC"), ("Japan", "APAC"), ("Australia", "APAC"),
]

PRODUCT_CATALOG = [
    ("Laptop Pro 14", "Electronics", 1499.00),
    ("Laptop Air 13", "Electronics", 999.00),
    ("Wireless Mouse", "Electronics", 29.00),
    ("Mechanical Keyboard", "Electronics", 129.00),
    ("4K Monitor 27\"", "Electronics", 449.00),
    ("Noise-Cancelling Headphones", "Electronics", 299.00),
    ("Smartwatch X", "Electronics", 199.00),
    ("Cotton T-Shirt", "Apparel", 19.00),
    ("Denim Jeans", "Apparel", 59.00),
    ("Running Shoes", "Apparel", 89.00),
    ("Winter Jacket", "Apparel", 159.00),
    ("Yoga Mat", "Home", 35.00),
    ("Coffee Maker", "Home", 79.00),
    ("Air Purifier", "Home", 199.00),
    ("Office Chair", "Home", 249.00),
    ("Standing Desk", "Home", 399.00),
]

RETURN_REASONS = ["damaged", "wrong_item", "not_as_described", "changed_mind", "late_delivery"]
STATUSES = ["completed", "completed", "completed", "completed", "pending", "cancelled", "refunded"]
PAYMENT_METHODS = ["card", "card", "card", "paypal", "bank_transfer"]
PAYMENT_STATUSES = ["succeeded", "succeeded", "succeeded", "succeeded", "failed", "refunded"]
CARRIERS = ["UPS", "FedEx", "DHL", "USPS"]
SHIPMENT_STATUSES = ["delivered", "delivered", "delivered", "in_transit", "returned", "lost"]
DEPARTMENTS = [
    ("Engineering", ["Engineer", "Senior Engineer", "Staff Engineer", "Manager"]),
    ("Sales", ["Sales Rep", "Account Executive", "Manager"]),
    ("Support", ["Support Agent", "Manager"]),
    ("Marketing", ["Marketer", "Content Lead", "Manager"]),
    ("Operations", ["Operations Analyst", "Manager"]),
    ("HR", ["Recruiter", "HR Partner", "Manager"]),
    ("Finance", ["Accountant", "Analyst", "Manager"]),
]


def reset_schema() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def seed_customers(session: Session, n: int = 200) -> list[Customer]:
    customers: list[Customer] = []
    for i in range(n):
        country, region = random.choice(COUNTRIES)
        c = Customer(
            name=f"Customer {i+1:04d}",
            email=f"customer{i+1:04d}@example.com",
            country=country,
            region=region,
        )
        session.add(c)
        customers.append(c)
    session.flush()
    return customers


def seed_products(session: Session) -> list[Product]:
    products: list[Product] = []
    for name, category, price in PRODUCT_CATALOG:
        p = Product(
            name=name,
            category=category,
            price=Decimal(str(price)),
            stock=random.randint(10, 500),
        )
        session.add(p)
        products.append(p)
    session.flush()
    return products


def seed_orders(
    session: Session, customers: list[Customer], products: list[Product], n: int = 1500
) -> list[Order]:
    """Bulk-insert orders + their line items in two flushes total.

    The original version flushed after every order to read back its ID,
    which is 1,500 round trips — fine against localhost (<1ms), painful
    against a remote DB (~250ms each = >6 min). We now plan everything
    in memory, flush once for all orders to assign IDs, then flush once
    for all items.
    """
    today = date.today()

    # Plan every order + its items in memory, no DB calls.
    plans: list[tuple[Order, list[tuple[Product, int, Decimal]]]] = []
    for _ in range(n):
        customer = random.choice(customers)
        days_ago = random.randint(0, 365)
        order_date = today - timedelta(days=days_ago)
        status = random.choice(STATUSES)
        order = Order(
            customer_id=customer.id,
            order_date=order_date,
            status=status,
            total_amount=Decimal("0.00"),
        )
        items_plan: list[tuple[Product, int, Decimal]] = []
        total = Decimal("0.00")
        for _ in range(random.randint(1, 4)):
            product = random.choice(products)
            qty = random.randint(1, 3)
            # small price noise vs. catalog
            unit_price = (
                Decimal(product.price)
                * Decimal(str(random.uniform(0.9, 1.05)))
            ).quantize(Decimal("0.01"))
            items_plan.append((product, qty, unit_price))
            total += unit_price * qty
        order.total_amount = total.quantize(Decimal("0.01"))
        plans.append((order, items_plan))

    # Flush #1: insert all orders, get their IDs back in one round trip.
    session.add_all(o for o, _ in plans)
    session.flush()

    # Flush #2: build every OrderItem using the now-populated order.id, insert.
    items: list[OrderItem] = []
    for order, items_plan in plans:
        for product, qty, unit_price in items_plan:
            items.append(OrderItem(
                order_id=order.id,
                product_id=product.id,
                quantity=qty,
                unit_price=unit_price,
            ))
    session.add_all(items)
    session.flush()

    return [o for o, _ in plans]


def seed_payments(session: Session, orders: list[Order]) -> None:
    for order in orders:
        if order.status == "cancelled":
            continue  # cancelled orders have no payments
        # ~10% of completed orders are split into two payments
        n_payments = 2 if random.random() < 0.10 else 1
        remaining = Decimal(order.total_amount)
        for i in range(n_payments):
            if i == n_payments - 1:
                amount = remaining
            else:
                amount = (remaining * Decimal(str(random.uniform(0.3, 0.7)))).quantize(Decimal("0.01"))
                remaining -= amount
            method = random.choice(PAYMENT_METHODS)
            if order.status == "refunded":
                status = "refunded"
            elif order.status == "pending":
                status = random.choice(["succeeded", "failed"])
            else:
                status = random.choices(PAYMENT_STATUSES, weights=[8, 8, 8, 8, 1, 1])[0]
            pay = Payment(
                order_id=order.id,
                payment_date=order.order_date + timedelta(days=random.randint(0, 2)),
                method=method,
                amount=amount,
                status=status,
            )
            session.add(pay)


def seed_shipments(session: Session, orders: list[Order]) -> None:
    today = date.today()
    for order in orders:
        if order.status in ("cancelled", "pending"):
            continue  # not shipped
        shipped = order.order_date + timedelta(days=random.randint(0, 3))
        if shipped > today:
            shipped = today
        status = random.choice(SHIPMENT_STATUSES)
        delivered = None
        if status == "delivered":
            delivered = shipped + timedelta(days=random.randint(1, 8))
            if delivered > today:
                delivered = today
        ship = Shipment(
            order_id=order.id,
            shipped_date=shipped,
            delivered_date=delivered,
            carrier=random.choice(CARRIERS),
            tracking_number=f"TRK{random.randint(10**9, 10**10 - 1)}",
            status=status,
        )
        session.add(ship)


def seed_employees(session: Session, n: int = 80) -> None:
    today = date.today()

    # First create managers (one per department).
    managers: list[Employee] = []
    for dept, _roles in DEPARTMENTS:
        mgr = Employee(
            name=f"{dept} Manager",
            email=f"{dept.lower()}.manager@example.com",
            department=dept,
            role="Manager",
            hire_date=today - timedelta(days=random.randint(900, 2500)),
            manager_id=None,
            salary=Decimal(random.randint(140_000, 200_000)),
        )
        session.add(mgr)
        managers.append(mgr)
    session.flush()

    # Then create individual contributors reporting to a department manager.
    for i in range(n):
        dept, roles = random.choice(DEPARTMENTS)
        role = random.choice([r for r in roles if r != "Manager"])
        mgr = next(m for m in managers if m.department == dept)
        emp = Employee(
            name=f"Employee {i+1:03d}",
            email=f"employee{i+1:03d}@example.com",
            department=dept,
            role=role,
            hire_date=today - timedelta(days=random.randint(30, 2000)),
            manager_id=mgr.id,
            salary=Decimal(random.randint(60_000, 180_000)),
        )
        session.add(emp)


def seed_returns(session: Session, orders: list[Order]) -> None:
    """Same remote-DB-friendly treatment as seed_orders: avoid lazy loads.

    The original version touched `o.items` (which triggers a lazy SELECT per
    order — 1,500 round trips) and then `session.get(Order, ...)` per return.
    We instead fetch all items in one query and resolve order_date via an
    in-memory dict.
    """
    today = date.today()
    order_date_by_id = {o.id: o.order_date for o in orders}

    # One SELECT instead of 1,500 lazy loads.
    items = session.query(OrderItem).all()

    n_returns = int(len(items) * 0.07)  # ~7% return rate
    sampled = random.sample(items, min(n_returns, len(items)))

    returns: list[Return] = []
    for item in sampled:
        order_date = order_date_by_id.get(item.order_id)
        if order_date is None:
            continue
        rdate = order_date + timedelta(days=random.randint(3, 45))
        if rdate > today:
            rdate = today
        refund_qty = random.randint(1, item.quantity)
        returns.append(Return(
            order_item_id=item.id,
            return_date=rdate,
            reason=random.choice(RETURN_REASONS),
            refund_amount=(Decimal(item.unit_price) * refund_qty).quantize(Decimal("0.01")),
        ))
    session.add_all(returns)
    session.flush()


def main() -> None:
    random.seed(42)
    print("Resetting schema...")
    reset_schema()
    session = get_session()
    try:
        print("Seeding customers...")
        customers = seed_customers(session)
        print(f"  {len(customers)} customers")

        print("Seeding products...")
        products = seed_products(session)
        print(f"  {len(products)} products")

        print("Seeding orders + order items...")
        orders = seed_orders(session, customers, products)
        print(f"  {len(orders)} orders")

        print("Seeding returns...")
        seed_returns(session, orders)

        print("Seeding payments...")
        seed_payments(session, orders)

        print("Seeding shipments...")
        seed_shipments(session, orders)

        print("Seeding employees...")
        seed_employees(session)

        session.commit()
        print("Done.")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
