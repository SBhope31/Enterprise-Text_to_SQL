from datetime import datetime, date
from decimal import Decimal

from sqlalchemy import (
    String, Integer, Numeric, ForeignKey, Date, DateTime, func, Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    country: Mapped[str] = mapped_column(String(80), nullable=False)
    region: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    orders: Mapped[list["Order"]] = relationship(back_populates="customer")


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="completed")
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)

    customer: Mapped[Customer] = relationship(back_populates="orders")
    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    order: Mapped[Order] = relationship(back_populates="items")


class Return(Base):
    __tablename__ = "returns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_item_id: Mapped[int] = mapped_column(ForeignKey("order_items.id"), nullable=False)
    return_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str] = mapped_column(String(120), nullable=False)
    refund_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    method: Mapped[str] = mapped_column(String(30), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="succeeded")


class Shipment(Base):
    __tablename__ = "shipments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    shipped_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    delivered_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    carrier: Mapped[str] = mapped_column(String(40), nullable=False)
    tracking_number: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="in_transit")


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    department: Mapped[str] = mapped_column(String(80), nullable=False)
    role: Mapped[str] = mapped_column(String(80), nullable=False)
    hire_date: Mapped[date] = mapped_column(Date, nullable=False)
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    salary: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)


SCHEMA_DESCRIPTIONS: dict[str, str] = {
    "customers": "Customer master table. Stores customer identity, contact, and geography. Use for revenue-by-customer, geography breakdowns, and customer activity analysis.",
    "products": "Product catalog. Stores SKU name, category, list price, and current stock level. Use for product-mix, inventory, category performance, and pricing analysis.",
    "orders": "Order header table. One row per order with customer, order_date, status, and total_amount. Use for revenue, order volume, time-series trend, and customer-frequency analysis.",
    "order_items": "Order line items. One row per product in an order with quantity and unit_price. Use to compute item-level revenue, units sold, and joins from orders to products.",
    "returns": "Product return records. Links to order_items and stores return_date, reason, and refund_amount. Use for return rate, refund value, and product-quality analysis.",
    "payments": "Order payments. One or more payments per order with method (card, paypal, bank_transfer), amount, and status (succeeded, failed, refunded). Use for payment success rate, method mix, and revenue collected.",
    "shipments": "Order shipments. One row per shipment with carrier, tracking, ship and delivery dates, and status (in_transit, delivered, returned, lost). Use for delivery time, carrier performance, and fulfilment analysis.",
    "employees": "Internal employee directory. Stores name, email, department, role, hire date, manager (self-reference), and salary. Use for headcount, salary, tenure, and org-chart analysis.",
}

COLUMN_DESCRIPTIONS: dict[tuple[str, str], str] = {
    ("customers", "id"): "Primary key of the customer.",
    ("customers", "name"): "Full name of the customer.",
    ("customers", "email"): "Customer email address (unique).",
    ("customers", "country"): "Country of the customer (ISO-name).",
    ("customers", "region"): "Sales region (e.g., NA, EMEA, APAC, LATAM).",
    ("customers", "created_at"): "Timestamp the customer record was created.",

    ("products", "id"): "Primary key of the product.",
    ("products", "name"): "Product display name.",
    ("products", "category"): "Product category (e.g., Electronics, Apparel, Home).",
    ("products", "price"): "Current list price in USD.",
    ("products", "stock"): "Current units available in inventory.",

    ("orders", "id"): "Primary key of the order.",
    ("orders", "customer_id"): "Foreign key to customers.id.",
    ("orders", "order_date"): "Date the order was placed.",
    ("orders", "status"): "Order status: completed, pending, cancelled, refunded.",
    ("orders", "total_amount"): "Total order value in USD (sum of item quantity * unit_price).",

    ("order_items", "id"): "Primary key of the order line item.",
    ("order_items", "order_id"): "Foreign key to orders.id.",
    ("order_items", "product_id"): "Foreign key to products.id.",
    ("order_items", "quantity"): "Units of the product purchased in this line.",
    ("order_items", "unit_price"): "Price per unit at order time (may differ from current products.price).",

    ("returns", "id"): "Primary key of the return record.",
    ("returns", "order_item_id"): "Foreign key to order_items.id.",
    ("returns", "return_date"): "Date the return was processed.",
    ("returns", "reason"): "Reason text (e.g., damaged, wrong_item, not_as_described).",
    ("returns", "refund_amount"): "Refund value in USD.",

    ("payments", "id"): "Primary key of the payment.",
    ("payments", "order_id"): "Foreign key to orders.id.",
    ("payments", "payment_date"): "Date the payment was processed.",
    ("payments", "method"): "Payment method: card, paypal, bank_transfer.",
    ("payments", "amount"): "Payment amount in USD.",
    ("payments", "status"): "Payment status: succeeded, failed, refunded.",

    ("shipments", "id"): "Primary key of the shipment.",
    ("shipments", "order_id"): "Foreign key to orders.id.",
    ("shipments", "shipped_date"): "Date the shipment left the warehouse (NULL if not shipped).",
    ("shipments", "delivered_date"): "Date the shipment was delivered (NULL if undelivered).",
    ("shipments", "carrier"): "Shipping carrier (e.g., UPS, FedEx, DHL, USPS).",
    ("shipments", "tracking_number"): "Carrier tracking number.",
    ("shipments", "status"): "Shipment status: in_transit, delivered, returned, lost.",

    ("employees", "id"): "Primary key of the employee.",
    ("employees", "name"): "Full name of the employee.",
    ("employees", "email"): "Employee email address (unique).",
    ("employees", "department"): "Department (Engineering, Sales, Support, Marketing, Operations, HR, Finance).",
    ("employees", "role"): "Job title (e.g., Engineer, Manager, Analyst).",
    ("employees", "hire_date"): "Date the employee was hired.",
    ("employees", "manager_id"): "Self-referencing FK to employees.id (NULL for top of chain).",
    ("employees", "salary"): "Annual salary in USD.",
}
