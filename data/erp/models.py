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
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import Enum as SAEnum
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


class ProductCategory(StrEnum):
    mineral_water = "mineral_water"
    soft_drink = "soft_drink"
    spritzer = "spritzer"
    craft = "craft"
    specialty = "specialty"


class ContainerType(StrEnum):
    glass_returnable = "glass_returnable"
    glass_oneway = "glass_oneway"
    pet = "pet"
    can = "can"


class ProductionLineType(StrEnum):
    glass = "glass"
    pet = "pet"
    can = "can"
    keg = "keg"


class CustomerChannel(StrEnum):
    retail_chain = "retail_chain"
    gastronomy = "gastronomy"
    wholesaler = "wholesaler"
    convenience = "convenience"


class SalesOrderStatus(StrEnum):
    open = "open"
    confirmed = "confirmed"
    partially_delivered = "partially_delivered"
    delivered = "delivered"
    invoiced = "invoiced"
    cancelled = "cancelled"


class DeliveryStatus(StrEnum):
    planned = "planned"
    picked = "picked"
    shipped = "shipped"
    delivered = "delivered"


class CustomerInvoiceStatus(StrEnum):
    open = "open"
    partially_paid = "partially_paid"
    paid = "paid"
    overdue = "overdue"
    cancelled = "cancelled"


class PaymentMethod(StrEnum):
    bank_transfer = "bank_transfer"
    direct_debit = "direct_debit"


class WebshopOrderStatus(StrEnum):
    placed = "placed"
    paid = "paid"
    shipped = "shipped"
    delivered = "delivered"
    returned = "returned"
    cancelled = "cancelled"


class WebshopPaymentMethod(StrEnum):
    paypal = "paypal"
    credit_card = "credit_card"
    invoice = "invoice"
    sepa_direct_debit = "sepa_direct_debit"


class ProductionRunStatus(StrEnum):
    planned = "planned"
    running = "running"
    completed = "completed"
    aborted = "aborted"


class QualityResult(StrEnum):
    pass_ = "pass"
    warning = "warning"
    fail = "fail"


class MaintenanceType(StrEnum):
    preventive = "preventive"
    corrective = "corrective"


class StockMovementType(StrEnum):
    goods_receipt = "goods_receipt"  # raw material in from a supplier
    production_issue = "production_issue"  # raw material consumed by a run
    production_receipt = "production_receipt"  # finished goods out of a run
    delivery_issue = "delivery_issue"  # finished goods shipped to a customer
    return_receipt = "return_receipt"  # finished goods back from a customer
    adjustment = "adjustment"  # inventory correction (count, scrap, opening balance)


class StockItemType(StrEnum):
    raw_material = "raw_material"
    product = "product"


class ReturnReason(StrEnum):
    damaged = "damaged"
    quality_defect = "quality_defect"
    wrong_delivery = "wrong_delivery"
    overstock = "overstock"


class ReturnStatus(StrEnum):
    requested = "requested"
    received = "received"
    credited = "credited"
    rejected = "rejected"


class GLAccountType(StrEnum):
    asset = "asset"
    liability = "liability"
    equity = "equity"
    revenue = "revenue"
    expense = "expense"


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
    purchase_order_line_id: Mapped[UUID] = mapped_column(ForeignKey("purchase_order_line.id"))
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


# ---------------------------------------------------------------------------
# Master data spine (sales + production side)
#
# These tables are the dimensions the transactional sales, production and IoT
# data hang off. The procurement tables above (supplier .. supplier_invoice)
# cover MM/FI-AP; the entities below open up SD (sales), PP (production) and
# the org structure. SAP module/table hints are noted per class but kept as
# comments only: the column names stay readable rather than mirroring VBAK etc.
# ---------------------------------------------------------------------------


class Plant(Base, TimestampMixin):
    """A production and distribution site. SAP: Werk (T001W), company code BB01."""

    __tablename__ = "plant"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    plant_code: Mapped[str] = mapped_column(String(4), unique=True)  # SAP-style "1000"
    company_code: Mapped[str] = mapped_column(String(4), default="BB01")
    name: Mapped[str] = mapped_column(String(200))
    street: Mapped[str] = mapped_column(String(200))
    postal_code: Mapped[str] = mapped_column(String(20))
    city: Mapped[str] = mapped_column(String(100))
    country: Mapped[str] = mapped_column(String(2), default="DE")

    lines: Mapped[list["ProductionLine"]] = relationship(
        back_populates="plant",
        cascade="all, delete-orphan",
    )


class ProductionLine(Base, TimestampMixin):
    """A bottling or filling line inside a plant. SAP PP: work center (CRHD)."""

    __tablename__ = "production_line"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    line_code: Mapped[str] = mapped_column(String(10), unique=True)
    plant_id: Mapped[UUID] = mapped_column(ForeignKey("plant.id"))
    name: Mapped[str] = mapped_column(String(200))
    line_type: Mapped[ProductionLineType] = mapped_column(_enum(ProductionLineType))
    nominal_speed_bph: Mapped[int] = mapped_column(Integer)  # rated bottles per hour
    commissioned_date: Mapped[date] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(default=True)

    plant: Mapped[Plant] = relationship(back_populates="lines")


class Product(Base, TimestampMixin):
    """A finished beverage SKU. SAP material type FERT.

    Raw materials (ROH) and finished goods (FERT) would both be the MARA
    material master in SAP; they are split into two tables here because their
    attributes barely overlap (a finished good carries pack size, deposit,
    list price; a raw material does not).
    """

    __tablename__ = "product"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    material_number: Mapped[str] = mapped_column(String(30), unique=True)  # "F-10001"
    name: Mapped[str] = mapped_column(String(200))
    brand: Mapped[str] = mapped_column(String(100))
    category: Mapped[ProductCategory] = mapped_column(_enum(ProductCategory))
    container_type: Mapped[ContainerType] = mapped_column(_enum(ContainerType))
    volume_l: Mapped[Decimal] = mapped_column(Numeric(6, 3))  # per single bottle/can
    units_per_case: Mapped[int] = mapped_column(SmallInteger)
    deposit_eur: Mapped[Decimal] = mapped_column(Numeric(6, 2))  # Pfand per unit
    list_price_net_eur: Mapped[Decimal] = mapped_column(Numeric(10, 4))  # per unit
    vat_rate_pct: Mapped[Decimal] = mapped_column(Numeric(4, 2), default=Decimal("19.00"))
    shelf_life_days: Mapped[int] = mapped_column(SmallInteger)
    launched_date: Mapped[date] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(default=True)

    components: Mapped[list["ProductComponent"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )


class ProductComponent(Base):
    """Bill of materials line: a raw material consumed to make a product.

    Quantities are normalised per 1000 litres of finished product so the same
    recipe applies regardless of pack size. SAP PP: BOM (STKO/STPO).
    """

    __tablename__ = "product_component"
    __table_args__ = (UniqueConstraint("product_id", "raw_material_id"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    product_id: Mapped[UUID] = mapped_column(ForeignKey("product.id"))
    raw_material_id: Mapped[UUID] = mapped_column(ForeignKey("raw_material.id"))
    quantity_per_1000l: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    unit_of_measure: Mapped[str] = mapped_column(String(20))
    scrap_pct: Mapped[Decimal] = mapped_column(Numeric(4, 2), default=Decimal("0.00"))

    product: Mapped[Product] = relationship(back_populates="components")
    raw_material: Mapped[RawMaterial] = relationship()


class Customer(Base, TimestampMixin):
    """A B2B customer: retail chains, gastronomy, wholesalers. SAP: KNA1.

    Webshop B2C consumers are modelled separately (high-cardinality, event
    driven) and do not live in this master table.
    """

    __tablename__ = "customer"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    customer_number: Mapped[str] = mapped_column(String(20), unique=True)  # "C-100001"
    name: Mapped[str] = mapped_column(String(200))
    channel: Mapped[CustomerChannel] = mapped_column(_enum(CustomerChannel))
    region: Mapped[str] = mapped_column(String(50))  # German federal state
    street: Mapped[str] = mapped_column(String(200))
    postal_code: Mapped[str] = mapped_column(String(20))
    city: Mapped[str] = mapped_column(String(100))
    country: Mapped[str] = mapped_column(String(2), default="DE")
    vat_id: Mapped[str | None] = mapped_column(String(20))
    payment_terms_days: Mapped[int] = mapped_column(SmallInteger, default=30)
    credit_limit_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    active: Mapped[bool] = mapped_column(default=True)
    onboarded_date: Mapped[date] = mapped_column(Date)


# ---------------------------------------------------------------------------
# Sales and accounts receivable (SD + FI-AR)
#
# The outbound document flow mirrors SAP's Belegfluss: a sales order is
# delivered, the delivery is billed, and the invoice is settled by an incoming
# payment. Each document carries a reference to its predecessor so the chain
# can be walked end to end. The deposit (Pfand) is tracked separately from the
# goods value because it is a returnable charge, not revenue.
# ---------------------------------------------------------------------------


class SalesOrder(Base, TimestampMixin):
    """A customer's order for finished goods. SAP SD: VBAK."""

    __tablename__ = "sales_order"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    sales_order_number: Mapped[str] = mapped_column(String(20), unique=True)  # "SO-2024-000123"
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customer.id"))
    order_date: Mapped[date] = mapped_column(Date)
    requested_delivery_date: Mapped[date] = mapped_column(Date)
    status: Mapped[SalesOrderStatus] = mapped_column(
        _enum(SalesOrderStatus),
        default=SalesOrderStatus.open,
    )
    total_net_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    total_vat_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    total_gross_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    deposit_total_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))

    customer: Mapped[Customer] = relationship()
    lines: Mapped[list["SalesOrderLine"]] = relationship(
        back_populates="sales_order",
        cascade="all, delete-orphan",
    )


class SalesOrderLine(Base):
    __tablename__ = "sales_order_line"
    __table_args__ = (UniqueConstraint("sales_order_id", "line_number"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    sales_order_id: Mapped[UUID] = mapped_column(ForeignKey("sales_order.id"))
    line_number: Mapped[int] = mapped_column(SmallInteger)
    product_id: Mapped[UUID] = mapped_column(ForeignKey("product.id"))
    quantity_units: Mapped[Decimal] = mapped_column(Numeric(12, 3))  # individual bottles/cans
    unit_price_net_eur: Mapped[Decimal] = mapped_column(Numeric(10, 4))  # after channel discount
    vat_rate_pct: Mapped[Decimal] = mapped_column(Numeric(4, 2))
    line_net_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    line_vat_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    line_gross_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    deposit_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))

    sales_order: Mapped[SalesOrder] = relationship(back_populates="lines")
    product: Mapped[Product] = relationship()


class Delivery(Base, TimestampMixin):
    """Outbound delivery against a sales order. SAP SD: LIKP (delivery note)."""

    __tablename__ = "delivery"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    delivery_number: Mapped[str] = mapped_column(String(20), unique=True)  # "DN-2024-000123"
    sales_order_id: Mapped[UUID] = mapped_column(ForeignKey("sales_order.id"))
    plant_id: Mapped[UUID] = mapped_column(ForeignKey("plant.id"))  # shipped from
    delivery_date: Mapped[date] = mapped_column(Date)
    status: Mapped[DeliveryStatus] = mapped_column(
        _enum(DeliveryStatus),
        default=DeliveryStatus.delivered,
    )

    sales_order: Mapped[SalesOrder] = relationship()
    lines: Mapped[list["DeliveryLine"]] = relationship(
        back_populates="delivery",
        cascade="all, delete-orphan",
    )


class DeliveryLine(Base):
    __tablename__ = "delivery_line"
    __table_args__ = (UniqueConstraint("delivery_id", "line_number"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    delivery_id: Mapped[UUID] = mapped_column(ForeignKey("delivery.id"))
    line_number: Mapped[int] = mapped_column(SmallInteger)
    sales_order_line_id: Mapped[UUID] = mapped_column(ForeignKey("sales_order_line.id"))
    product_id: Mapped[UUID] = mapped_column(ForeignKey("product.id"))
    quantity_units: Mapped[Decimal] = mapped_column(Numeric(12, 3))

    delivery: Mapped[Delivery] = relationship(back_populates="lines")
    sales_order_line: Mapped[SalesOrderLine] = relationship()
    product: Mapped[Product] = relationship()


class CustomerInvoice(Base, TimestampMixin):
    """Outgoing invoice billed to a customer. SAP SD billing (VBRK) / FI-AR (BSID)."""

    __tablename__ = "customer_invoice"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    customer_invoice_number: Mapped[str] = mapped_column(String(20), unique=True)  # "AR-2024-..."
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customer.id"))
    sales_order_id: Mapped[UUID] = mapped_column(ForeignKey("sales_order.id"))
    delivery_id: Mapped[UUID] = mapped_column(ForeignKey("delivery.id"))
    invoice_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[CustomerInvoiceStatus] = mapped_column(
        _enum(CustomerInvoiceStatus),
        default=CustomerInvoiceStatus.open,
    )
    total_net_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    total_vat_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    total_gross_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    deposit_total_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    amount_due_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))  # gross + deposit

    customer: Mapped[Customer] = relationship()
    sales_order: Mapped[SalesOrder] = relationship()
    delivery: Mapped[Delivery] = relationship()
    lines: Mapped[list["CustomerInvoiceLine"]] = relationship(
        back_populates="customer_invoice",
        cascade="all, delete-orphan",
    )


class CustomerInvoiceLine(Base):
    __tablename__ = "customer_invoice_line"
    __table_args__ = (UniqueConstraint("customer_invoice_id", "line_number"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    customer_invoice_id: Mapped[UUID] = mapped_column(ForeignKey("customer_invoice.id"))
    line_number: Mapped[int] = mapped_column(SmallInteger)
    product_id: Mapped[UUID] = mapped_column(ForeignKey("product.id"))
    delivery_line_id: Mapped[UUID] = mapped_column(ForeignKey("delivery_line.id"))
    quantity_units: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    unit_price_net_eur: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    vat_rate_pct: Mapped[Decimal] = mapped_column(Numeric(4, 2))
    line_net_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    line_vat_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    line_gross_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    deposit_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))

    customer_invoice: Mapped[CustomerInvoice] = relationship(back_populates="lines")
    product: Mapped[Product] = relationship()
    delivery_line: Mapped[DeliveryLine] = relationship()


class PaymentReceived(Base, TimestampMixin):
    """An incoming payment settling a customer invoice. SAP FI-AR: BSAD.

    The link to the invoice is what the bank-statement (cash application) use
    case has to reconstruct from raw CAMT/MT940 files in the bronze layer.
    """

    __tablename__ = "payment_received"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    payment_number: Mapped[str] = mapped_column(String(20), unique=True)  # "PAY-2024-000123"
    customer_invoice_id: Mapped[UUID] = mapped_column(ForeignKey("customer_invoice.id"))
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customer.id"))
    payment_date: Mapped[date] = mapped_column(Date)
    amount_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    method: Mapped[PaymentMethod] = mapped_column(
        _enum(PaymentMethod),
        default=PaymentMethod.bank_transfer,
    )
    # Free-text payment reference as it appears on the bank statement; may or
    # may not cleanly contain the invoice number (that is the matching problem).
    remittance_info: Mapped[str | None] = mapped_column(String(200))

    customer_invoice: Mapped[CustomerInvoice] = relationship()
    customer: Mapped[Customer] = relationship()


# ---------------------------------------------------------------------------
# Webshop / B2C (Phase 3)
#
# Direct-to-consumer sales through the online shop. Consumers are their own
# master table (high cardinality, distinct from the B2B Customer book). The
# raw clickstream and reviews live as files in the bronze layer; the orders
# below are the conformed transactional record.
# ---------------------------------------------------------------------------


class WebshopCustomer(Base, TimestampMixin):
    """A B2C consumer registered in the online shop."""

    __tablename__ = "webshop_customer"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    customer_ref: Mapped[str] = mapped_column(String(20), unique=True)  # "WC-000123"
    email: Mapped[str] = mapped_column(String(200))
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    postal_code: Mapped[str] = mapped_column(String(20))
    city: Mapped[str] = mapped_column(String(100))
    region: Mapped[str] = mapped_column(String(50))
    signup_date: Mapped[date] = mapped_column(Date)
    marketing_opt_in: Mapped[bool] = mapped_column(default=False)


class OnlineOrder(Base, TimestampMixin):
    """A webshop order. SAP would book this through SD like any sales order."""

    __tablename__ = "online_order"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    order_number: Mapped[str] = mapped_column(String(20), unique=True)  # "WO-2024-000123"
    webshop_customer_id: Mapped[UUID] = mapped_column(ForeignKey("webshop_customer.id"))
    ordered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[WebshopOrderStatus] = mapped_column(
        _enum(WebshopOrderStatus),
        default=WebshopOrderStatus.placed,
    )
    payment_method: Mapped[WebshopPaymentMethod] = mapped_column(_enum(WebshopPaymentMethod))
    total_net_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    total_vat_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    total_gross_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    deposit_total_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    shipping_eur: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0.00"))

    webshop_customer: Mapped[WebshopCustomer] = relationship()
    lines: Mapped[list["OnlineOrderLine"]] = relationship(
        back_populates="online_order",
        cascade="all, delete-orphan",
    )


class OnlineOrderLine(Base):
    __tablename__ = "online_order_line"
    __table_args__ = (UniqueConstraint("online_order_id", "line_number"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    online_order_id: Mapped[UUID] = mapped_column(ForeignKey("online_order.id"))
    line_number: Mapped[int] = mapped_column(SmallInteger)
    product_id: Mapped[UUID] = mapped_column(ForeignKey("product.id"))
    quantity_cases: Mapped[int] = mapped_column(SmallInteger)  # consumers buy by the case
    unit_price_gross_eur: Mapped[Decimal] = mapped_column(Numeric(10, 4))  # per case, gross
    line_gross_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    deposit_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))

    online_order: Mapped[OnlineOrder] = relationship(back_populates="lines")
    product: Mapped[Product] = relationship()


# ---------------------------------------------------------------------------
# Production and quality (PP + QM, Phase 4)
#
# Production runs turn raw materials (per the product BOM) into finished goods.
# Quality checks sample the run; maintenance orders capture line downtime. The
# raw sensor telemetry and machine logs live as files in the bronze layer.
# ---------------------------------------------------------------------------


class ProductionRun(Base, TimestampMixin):
    """One filling run of a product on a line. SAP PP: process/production order."""

    __tablename__ = "production_run"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_number: Mapped[str] = mapped_column(String(20), unique=True)  # "PR-2024-000123"
    product_id: Mapped[UUID] = mapped_column(ForeignKey("product.id"))
    production_line_id: Mapped[UUID] = mapped_column(ForeignKey("production_line.id"))
    batch_number: Mapped[str] = mapped_column(String(30))  # printed on the bottle
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    planned_qty_units: Mapped[int] = mapped_column(Integer)
    produced_qty_units: Mapped[int] = mapped_column(Integer)
    scrap_qty_units: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[ProductionRunStatus] = mapped_column(
        _enum(ProductionRunStatus),
        default=ProductionRunStatus.completed,
    )

    product: Mapped[Product] = relationship()
    production_line: Mapped[ProductionLine] = relationship()
    quality_checks: Mapped[list["QualityCheck"]] = relationship(
        back_populates="production_run",
        cascade="all, delete-orphan",
    )


class QualityCheck(Base):
    """A measured quality parameter sampled during a production run. SAP QM."""

    __tablename__ = "quality_check"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    production_run_id: Mapped[UUID] = mapped_column(ForeignKey("production_run.id"))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    parameter: Mapped[str] = mapped_column(String(50))  # fill_volume_ml, co2_g_per_l, brix, ph
    measured_value: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    target_value: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    lower_tol: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    upper_tol: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    result: Mapped[QualityResult] = mapped_column(_enum(QualityResult))

    production_run: Mapped[ProductionRun] = relationship(back_populates="quality_checks")


class MaintenanceOrder(Base, TimestampMixin):
    """A maintenance event on a production line. SAP PM.

    Corrective orders are the failure ground truth for the predictive
    maintenance use case; the telemetry leading up to them carries the signal.
    """

    __tablename__ = "maintenance_order"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    order_number: Mapped[str] = mapped_column(String(20), unique=True)  # "MN-2024-000123"
    production_line_id: Mapped[UUID] = mapped_column(ForeignKey("production_line.id"))
    type: Mapped[MaintenanceType] = mapped_column(_enum(MaintenanceType))
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    downtime_minutes: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(300))

    production_line: Mapped[ProductionLine] = relationship()


# ---------------------------------------------------------------------------
# Inventory (MM / WM)
#
# A movement ledger plus a current-level snapshot. Movements are posted from the
# events that already exist: goods receipts add raw material, production runs
# consume raw material (per BOM) and yield finished goods, deliveries issue
# finished goods, returns add them back. Stock items are either a raw_material
# or a product; the two nullable FKs plus item_type discriminate which.
# ---------------------------------------------------------------------------


class StockMovement(Base):
    """A single posting against inventory. SAP MM: material document (MSEG)."""

    __tablename__ = "stock_movement"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    movement_number: Mapped[str] = mapped_column(String(20), unique=True)  # "MV-2024-000123"
    item_type: Mapped[StockItemType] = mapped_column(_enum(StockItemType))
    raw_material_id: Mapped[UUID | None] = mapped_column(ForeignKey("raw_material.id"))
    product_id: Mapped[UUID | None] = mapped_column(ForeignKey("product.id"))
    plant_id: Mapped[UUID] = mapped_column(ForeignKey("plant.id"))
    storage_location: Mapped[str] = mapped_column(String(20))  # "RM01", "FG01"
    movement_type: Mapped[StockMovementType] = mapped_column(_enum(StockMovementType))
    posting_date: Mapped[date] = mapped_column(Date)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))  # signed: + in, - out
    unit_of_measure: Mapped[str] = mapped_column(String(20))
    # Free-text pointer to the document that triggered the movement (GR/run/delivery).
    reference: Mapped[str | None] = mapped_column(String(40))


class StockLevel(Base, TimestampMixin):
    """Current on-hand quantity per item and plant. SAP MM: MARD-style snapshot."""

    __tablename__ = "stock_level"
    __table_args__ = (UniqueConstraint("item_type", "raw_material_id", "product_id", "plant_id"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    item_type: Mapped[StockItemType] = mapped_column(_enum(StockItemType))
    raw_material_id: Mapped[UUID | None] = mapped_column(ForeignKey("raw_material.id"))
    product_id: Mapped[UUID | None] = mapped_column(ForeignKey("product.id"))
    plant_id: Mapped[UUID] = mapped_column(ForeignKey("plant.id"))
    storage_location: Mapped[str] = mapped_column(String(20))
    quantity_on_hand: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    unit_of_measure: Mapped[str] = mapped_column(String(20))
    as_of_date: Mapped[date] = mapped_column(Date)


# ---------------------------------------------------------------------------
# Returns and credit notes (SD returns + FI-AR credit memo)
#
# A customer return reverses part of a delivery; a credit note books the
# financial reversal against the original customer invoice. Returns are seeded
# from the quality complaints and the webshop's returned orders.
# ---------------------------------------------------------------------------


class CustomerReturn(Base, TimestampMixin):
    """Goods sent back by a customer. SAP SD: returns order/delivery."""

    __tablename__ = "customer_return"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    return_number: Mapped[str] = mapped_column(String(20), unique=True)  # "RET-2024-000123"
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customer.id"))
    customer_invoice_id: Mapped[UUID | None] = mapped_column(ForeignKey("customer_invoice.id"))
    return_date: Mapped[date] = mapped_column(Date)
    reason: Mapped[ReturnReason] = mapped_column(_enum(ReturnReason))
    status: Mapped[ReturnStatus] = mapped_column(_enum(ReturnStatus), default=ReturnStatus.requested)
    # Optional link to the batch blamed for a quality defect.
    batch_number: Mapped[str | None] = mapped_column(String(30))
    total_net_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    customer: Mapped[Customer] = relationship()
    lines: Mapped[list["CustomerReturnLine"]] = relationship(
        back_populates="customer_return",
        cascade="all, delete-orphan",
    )


class CustomerReturnLine(Base):
    __tablename__ = "customer_return_line"
    __table_args__ = (UniqueConstraint("customer_return_id", "line_number"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    customer_return_id: Mapped[UUID] = mapped_column(ForeignKey("customer_return.id"))
    line_number: Mapped[int] = mapped_column(SmallInteger)
    product_id: Mapped[UUID] = mapped_column(ForeignKey("product.id"))
    quantity_units: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    line_net_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    customer_return: Mapped[CustomerReturn] = relationship(back_populates="lines")
    product: Mapped[Product] = relationship()


class CreditNote(Base, TimestampMixin):
    """A credit memo settling a return against the original invoice. SAP FI-AR."""

    __tablename__ = "credit_note"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    credit_note_number: Mapped[str] = mapped_column(String(20), unique=True)  # "CN-2024-..."
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customer.id"))
    customer_return_id: Mapped[UUID] = mapped_column(ForeignKey("customer_return.id"))
    customer_invoice_id: Mapped[UUID | None] = mapped_column(ForeignKey("customer_invoice.id"))
    credit_date: Mapped[date] = mapped_column(Date)
    total_net_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    total_vat_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    total_gross_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    customer: Mapped[Customer] = relationship()
    customer_return: Mapped[CustomerReturn] = relationship()


# ---------------------------------------------------------------------------
# General ledger and cost centers (FI / CO)
#
# A small chart of accounts and a posting journal. Journal entries are derived
# from the documents that already exist: customer invoices (revenue), supplier
# invoices (expense), payments, payroll. Each entry balances (sum of debits =
# sum of credits) across its lines.
# ---------------------------------------------------------------------------


class CostCenter(Base, TimestampMixin):
    """A cost centre. SAP CO: Kostenstelle (CSKS)."""

    __tablename__ = "cost_center"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    cost_center_code: Mapped[str] = mapped_column(String(20), unique=True)  # "CC-PROD-1000"
    name: Mapped[str] = mapped_column(String(200))
    plant_id: Mapped[UUID | None] = mapped_column(ForeignKey("plant.id"))


class GLAccount(Base, TimestampMixin):
    """A general-ledger account. SAP FI: Sachkonto (SKA1/SKB1)."""

    __tablename__ = "gl_account"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    account_number: Mapped[str] = mapped_column(String(10), unique=True)  # SKR-style "8400"
    name: Mapped[str] = mapped_column(String(200))
    account_type: Mapped[GLAccountType] = mapped_column(_enum(GLAccountType))


class JournalEntry(Base, TimestampMixin):
    """A balanced posting document. SAP FI: Belegkopf (BKPF)."""

    __tablename__ = "journal_entry"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    document_number: Mapped[str] = mapped_column(String(20), unique=True)  # "JE-2024-000123"
    posting_date: Mapped[date] = mapped_column(Date)
    source_module: Mapped[str] = mapped_column(String(10))  # AR, AP, PY, BANK
    reference: Mapped[str | None] = mapped_column(String(40))  # source document number
    description: Mapped[str] = mapped_column(String(200))

    lines: Mapped[list["JournalEntryLine"]] = relationship(
        back_populates="journal_entry",
        cascade="all, delete-orphan",
    )


class JournalEntryLine(Base):
    """One debit or credit line of a journal entry. SAP FI: Belegzeile (BSEG)."""

    __tablename__ = "journal_entry_line"
    __table_args__ = (UniqueConstraint("journal_entry_id", "line_number"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    journal_entry_id: Mapped[UUID] = mapped_column(ForeignKey("journal_entry.id"))
    line_number: Mapped[int] = mapped_column(SmallInteger)
    gl_account_id: Mapped[UUID] = mapped_column(ForeignKey("gl_account.id"))
    cost_center_id: Mapped[UUID | None] = mapped_column(ForeignKey("cost_center.id"))
    debit_eur: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    credit_eur: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))

    journal_entry: Mapped[JournalEntry] = relationship(back_populates="lines")
    gl_account: Mapped[GLAccount] = relationship()
    cost_center: Mapped[CostCenter] = relationship()
