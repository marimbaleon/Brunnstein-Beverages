"""Persist an approved invoice into the supplier_invoice table.

Looks up supplier and purchase order by the identifiers printed on the
invoice. The caller is responsible for invoking this only after validation
has confirmed those references resolve; we use `.one()` rather than
`.one_or_none()` so a programming bug here fails loud rather than writing
a partial row.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.orm import Session

from data.erp.models import (
    ExtractionStatus,
    PurchaseOrder,
    Supplier,
    SupplierInvoice,
    SupplierInvoiceLine,
    SupplierInvoiceStatus,
)
from use_cases.automated_invoice_processing.agent.schema import ExtractedInvoice

logger = logging.getLogger(__name__)

# Single-rate VAT for the demo. In a real deployment this comes from the
# raw_material master (each line item has its own rate) or from a tax
# determination service for cross-border cases.
_VAT_RATE = Decimal("0.19")
_VAT_RATE_PCT = Decimal("19.00")
_CENT = Decimal("0.01")


def persist_approved_invoice(
    session: Session,
    extracted: ExtractedInvoice,
    source_s3_key: str,
) -> SupplierInvoice:
    supplier = _load_supplier_or_raise(session, extracted.supplier_name)
    purchase_order = _load_purchase_order_or_raise(session, extracted.po_number)

    invoice = SupplierInvoice(
        id=uuid4(),
        supplier_invoice_number=extracted.invoice_number,
        supplier_id=supplier.id,
        purchase_order_id=purchase_order.id,
        source_s3_key=source_s3_key,
        invoice_date=extracted.invoice_date,
        due_date=extracted.due_date,
        total_net_eur=extracted.total_net_eur,
        total_vat_eur=extracted.total_vat_eur,
        total_gross_eur=extracted.total_gross_eur,
        payment_iban=extracted.payment_iban,
        status=SupplierInvoiceStatus.approved,
        extraction_status=ExtractionStatus.extracted,
    )
    for line in extracted.lines:
        invoice.lines.append(_build_invoice_line(invoice.id, line))
    session.add(invoice)
    session.commit()
    logger.info(
        "persisted supplier_invoice id=%s number=%s",
        invoice.id, invoice.supplier_invoice_number,
    )
    return invoice


def _load_supplier_or_raise(session: Session, name: str) -> Supplier:
    return session.query(Supplier).filter(Supplier.name == name).one()


def _load_purchase_order_or_raise(
    session: Session, po_number: str | None,
) -> PurchaseOrder:
    if po_number is None:
        raise ValueError("cannot persist an approved invoice without a PO number")
    return session.query(PurchaseOrder).filter(
        PurchaseOrder.po_number == po_number,
    ).one()


def _build_invoice_line(
    invoice_id, line,
) -> SupplierInvoiceLine:
    line_vat = (line.line_net_eur * _VAT_RATE).quantize(_CENT)
    return SupplierInvoiceLine(
        id=uuid4(),
        supplier_invoice_id=invoice_id,
        line_number=line.line_number,
        description=line.description,
        quantity=line.quantity,
        unit_price_net_eur=line.unit_price_net_eur,
        line_net_eur=line.line_net_eur,
        vat_rate_pct=_VAT_RATE_PCT,
        line_vat_eur=line_vat,
        line_gross_eur=line.line_net_eur + line_vat,
    )
