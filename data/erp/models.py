"""SQLAlchemy models for Brunnstein's operational data.

These tables stand in for the company's ERP and DMS. v1 focuses on the
accounts payable side: incoming supplier invoices validated against
purchase orders and goods receipts.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    Date,
    DateTime,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy import (
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.now,
        onupdate=datetime.now,
    )


def _enum(e: type[StrEnum]) -> SAEnum:
    """Portable enum: VARCHAR + CHECK constraint, not a Postgres native type.

    Aurora DSQL does not support custom enum types.
    """
    return SAEnum(e, native_enum=False, length=30)


class SupplierInvoiceStatus(StrEnum):
    received = "received"
    extracted = "extracted"
    validated = "validated"
    approved = "approved"
    paid = "paid"
    rejected = "rejected"


class ExtractionStatus(StrEnum):
    pending = "pending"
    extracted = "extracted"
    failed = "failed"


class PurchaseOrderStatus(StrEnum):
    open = "open"
    partial = "partial"
    received = "received"
    closed = "closed"
    cancelled = "cancelled"


class GoodsReceiptStatus(StrEnum):
    pending_invoice = "pending_invoice"
    matched = "matched"
    discrepancy = "discrepancy"


class RawMaterialCategory(StrEnum):
    packaging = "packaging"
    ingredient = "ingredient"
    auxiliary = "auxiliary"


class Supplier(Base, TimestampMixin):
    __tablename__ = "supplier"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    supplier_number: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    vat_id: Mapped[str | None] = mapped_column(String(20))
    iban: Mapped[str] = mapped_column(String(34))
    bic: Mapped[str | None] = mapped_column(String(11))
    payment_terms_days: Mapped[int] = mapped_column(SmallInteger, default=30)
    street: Mapped[str] = mapped_column(String(200))
    postal_code: Mapped[str] = mapped_column(String(20))
    city: Mapped[str] = mapped_column(String(100))
    country: Mapped[str] = mapped_column(String(2), default="DE")
    email: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(30))
    active: Mapped[bool] = mapped_column(default=True)


class RawMaterial(Base, TimestampMixin):
    """Inputs purchased from suppliers: packaging, ingredients, auxiliaries."""

    __tablename__ = "raw_material"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    material_number: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[RawMaterialCategory] = mapped_column(_enum(RawMaterialCategory))
    unit_of_measure: Mapped[str] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(default=True)


class PurchaseOrder(Base, TimestampMixin):
    __tablename__ = "purchase_order"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    po_number: Mapped[str] = mapped_column(String(20), unique=True)
    supplier_id: Mapped[UUID] = mapped_column(ForeignKey("supplier.id"))
    order_date: Mapped[date] = mapped_column(Date)
    requested_delivery_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[PurchaseOrderStatus] = mapped_column(
        _enum(PurchaseOrderStatus),
        default=PurchaseOrderStatus.open,
    )
    total_net_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    total_vat_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    total_gross_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    notes: Mapped[str | None] = mapped_column(Text)

    supplier: Mapped[Supplier] = relationship()
    lines: Mapped[list["PurchaseOrderLine"]] = relationship(
        back_populates="purchase_order",
        cascade="all, delete-orphan",
    )


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_line"
    __table_args__ = (UniqueConstraint("purchase_order_id", "line_number"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    purchase_order_id: Mapped[UUID] = mapped_column(ForeignKey("purchase_order.id"))
    line_number: Mapped[int] = mapped_column(SmallInteger)
    raw_material_id: Mapped[UUID] = mapped_column(ForeignKey("raw_material.id"))
    description: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    unit_price_net_eur: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    vat_rate_pct: Mapped[Decimal] = mapped_column(Numeric(4, 2))
    line_net_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    line_vat_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    line_gross_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    purchase_order: Mapped[PurchaseOrder] = relationship(back_populates="lines")
    raw_material: Mapped[RawMaterial] = relationship()


class GoodsReceipt(Base, TimestampMixin):
    """Records that ordered raw materials physically arrived.

    Enables 3-way match: PO + goods receipt + supplier invoice should
    agree on quantity and price before payment is released.
    """

    __tablename__ = "goods_receipt"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    gr_number: Mapped[str] = mapped_column(String(20), unique=True)
    purchase_order_id: Mapped[UUID] = mapped_column(ForeignKey("purchase_order.id"))
    received_date: Mapped[date] = mapped_column(Date)
    status: Mapped[GoodsReceiptStatus] = mapped_column(
        _enum(GoodsReceiptStatus),
        default=GoodsReceiptStatus.pending_invoice,
    )
    notes: Mapped[str | None] = mapped_column(Text)

    purchase_order: Mapped[PurchaseOrder] = relationship()
    lines: Mapped[list["GoodsReceiptLine"]] = relationship(
        back_populates="goods_receipt",
        cascade="all, delete-orphan",
    )


class GoodsReceiptLine(Base):
    __tablename__ = "goods_receipt_line"
    __table_args__ = (UniqueConstraint("goods_receipt_id", "line_number"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    goods_receipt_id: Mapped[UUID] = mapped_column(ForeignKey("goods_receipt.id"))
    line_number: Mapped[int] = mapped_column(SmallInteger)
    purchase_order_line_id: Mapped[UUID] = mapped_column(
        ForeignKey("purchase_order_line.id")
    )
    quantity_received: Mapped[Decimal] = mapped_column(Numeric(12, 3))

    goods_receipt: Mapped[GoodsReceipt] = relationship(back_populates="lines")
    purchase_order_line: Mapped[PurchaseOrderLine] = relationship()


class SupplierInvoice(Base, TimestampMixin):
    """An incoming invoice from a supplier.

    Fields populated by the extraction agent are nullable: the row exists
    from the moment the PDF arrives, and extracted values land as the
    agent progresses through its workflow.
    """

    __tablename__ = "supplier_invoice"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    supplier_invoice_number: Mapped[str | None] = mapped_column(String(50))
    supplier_id: Mapped[UUID | None] = mapped_column(ForeignKey("supplier.id"))
    purchase_order_id: Mapped[UUID | None] = mapped_column(ForeignKey("purchase_order.id"))
    source_s3_key: Mapped[str] = mapped_column(String(500))

    invoice_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)

    total_net_eur: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    total_vat_eur: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    total_gross_eur: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))

    # IBAN printed on the incoming PDF; cross-checked against supplier.iban
    # as a fraud-prevention signal (invoice fraud often swaps the IBAN).
    payment_iban: Mapped[str | None] = mapped_column(String(34))

    status: Mapped[SupplierInvoiceStatus] = mapped_column(
        _enum(SupplierInvoiceStatus),
        default=SupplierInvoiceStatus.received,
    )
    extraction_status: Mapped[ExtractionStatus] = mapped_column(
        _enum(ExtractionStatus),
        default=ExtractionStatus.pending,
    )
    extraction_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    validation_notes: Mapped[str | None] = mapped_column(Text)

    supplier: Mapped[Supplier | None] = relationship()
    purchase_order: Mapped[PurchaseOrder | None] = relationship()
    lines: Mapped[list["SupplierInvoiceLine"]] = relationship(
        back_populates="supplier_invoice",
        cascade="all, delete-orphan",
    )


class SupplierInvoiceLine(Base):
    __tablename__ = "supplier_invoice_line"
    __table_args__ = (UniqueConstraint("supplier_invoice_id", "line_number"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    supplier_invoice_id: Mapped[UUID] = mapped_column(ForeignKey("supplier_invoice.id"))
    line_number: Mapped[int] = mapped_column(SmallInteger)
    # Raw text from the invoice PDF; the match to a known raw_material is
    # the agent's job and is allowed to fail (raw_material_id stays NULL).
    description: Mapped[str] = mapped_column(String(500))
    raw_material_id: Mapped[UUID | None] = mapped_column(ForeignKey("raw_material.id"))
    purchase_order_line_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("purchase_order_line.id")
    )
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    unit_price_net_eur: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    vat_rate_pct: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    line_net_eur: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    line_vat_eur: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    line_gross_eur: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))

    supplier_invoice: Mapped[SupplierInvoice] = relationship(back_populates="lines")
    raw_material: Mapped[RawMaterial | None] = relationship()
    purchase_order_line: Mapped[PurchaseOrderLine | None] = relationship()
