"""Generate incoming supplier invoices, with a small share of discrepancies for the
validation agent to catch later (IBAN drift, price drift, quantity mismatch).
"""

from __future__ import annotations

import random
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from typing import NamedTuple
from uuid import uuid4

from data.erp.generators._text import slugify_company_name
from data.erp.models import (
    ExtractionStatus,
    GoodsReceipt,
    PurchaseOrder,
    PurchaseOrderStatus,
    Supplier,
    SupplierInvoice,
    SupplierInvoiceLine,
    SupplierInvoiceStatus,
)

_VAT_FACTOR = Decimal("0.19")
_DEFAULT_VAT_PCT = Decimal("19.00")

# Discrepancy rates (independent: a single invoice can have several at once).
_RATE_IBAN_TYPO = 0.03
_RATE_IBAN_FRAUD = 0.02
_RATE_PRICE_DRIFT = 0.04
_RATE_QTY_MISMATCH = 0.05


class _InvoiceLineData(NamedTuple):
    po_line: object  # PurchaseOrderLine (avoid import cycle in the type hint)
    quantity: Decimal
    unit_price: Decimal
    net: Decimal
    vat: Decimal
    gross: Decimal


def _payment_iban(supplier: Supplier, rng: random.Random) -> str:
    r = rng.random()
    if r < _RATE_IBAN_FRAUD:
        # Completely different IBAN (fraud signal)
        return "DE" + "".join(str(rng.randint(0, 9)) for _ in range(20))
    if r < _RATE_IBAN_FRAUD + _RATE_IBAN_TYPO:
        # Last two digits swapped (looks like a typo)
        iban = supplier.iban
        return iban[:-2] + iban[-1] + iban[-2]
    return supplier.iban


def _aggregate_received(receipts: list[GoodsReceipt]) -> dict[str, Decimal]:
    """Sum received quantity per PO line across all receipts for a PO."""
    agg: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for gr in receipts:
        for rl in gr.lines:
            agg[str(rl.purchase_order_line_id)] += rl.quantity_received
    return agg


def generate_supplier_invoices(
    goods_receipts: list[GoodsReceipt],
    seed: int = 42,
) -> list[SupplierInvoice]:
    rng = random.Random(seed)

    # Group receipts by PO
    by_po: dict[str, list[GoodsReceipt]] = defaultdict(list)
    for gr in goods_receipts:
        by_po[str(gr.purchase_order_id)].append(gr)

    invoices: list[SupplierInvoice] = []

    for po_id, receipts in by_po.items():
        po: PurchaseOrder = receipts[0].purchase_order
        if po.status == PurchaseOrderStatus.cancelled:
            continue
        supplier = po.supplier

        # Invoice issued by the supplier 0-14 days after the last receipt.
        last_receipt_date = max(gr.received_date for gr in receipts)
        invoice_date = last_receipt_date + timedelta(days=rng.randint(0, 14))
        due_date = invoice_date + timedelta(days=supplier.payment_terms_days or 30)
        year = invoice_date.year

        received_per_line = _aggregate_received(receipts)
        inv_lines_data = _build_invoice_lines(po, received_per_line, rng)
        if not inv_lines_data:
            continue

        invoice_number_seq = len(invoices) + 1
        s3_key = (
            f"invoices/{year}/{slugify_company_name(supplier.name)}/"
            f"{invoice_number_seq:07d}.pdf"
        )

        total_net = sum((row.net for row in inv_lines_data), Decimal("0"))
        total_vat = sum((row.vat for row in inv_lines_data), Decimal("0"))
        total_gross = sum((row.gross for row in inv_lines_data), Decimal("0"))

        inv = SupplierInvoice(
            id=uuid4(),
            supplier_invoice_number=f"RG-{year}-{invoice_number_seq:07d}",
            supplier_id=supplier.id,
            purchase_order_id=po.id,
            source_s3_key=s3_key,
            invoice_date=invoice_date,
            due_date=due_date,
            total_net_eur=total_net,
            total_vat_eur=total_vat,
            total_gross_eur=total_gross,
            payment_iban=_payment_iban(supplier, rng),
            status=SupplierInvoiceStatus.received,
            extraction_status=ExtractionStatus.pending,
            extraction_confidence=None,
            validation_notes=None,
        )
        inv.supplier = supplier
        inv.purchase_order = po

        for line_number, row in enumerate(inv_lines_data, start=1):
            inv.lines.append(SupplierInvoiceLine(
                id=uuid4(),
                supplier_invoice_id=inv.id,
                line_number=line_number,
                description=row.po_line.description,
                raw_material_id=row.po_line.raw_material_id,
                purchase_order_line_id=row.po_line.id,
                quantity=row.quantity,
                unit_price_net_eur=row.unit_price,
                vat_rate_pct=_DEFAULT_VAT_PCT,
                line_net_eur=row.net,
                line_vat_eur=row.vat,
                line_gross_eur=row.gross,
            ))

        invoices.append(inv)

    return invoices


# Magic numbers from "what makes the eval scenarios interesting":
# - QTY_MISMATCH_FACTORS bump or drop quantity by 5-15%
# - PRICE_DRIFT_FACTOR_RANGE pushes unit price up by 3-10%
# - The 0.5 below means: when an invoice is marked as having a qty mismatch,
#   each individual line still has only a 50% chance of being affected, so
#   the mismatch isn't uniform across all lines (more realistic).
_QTY_MISMATCH_FACTORS_PCT = (85, 92, 108, 115)
_QTY_MISMATCH_LINE_PROBABILITY = 0.5
_PRICE_DRIFT_FACTOR_RANGE_PCT = (103, 110)


def _build_invoice_lines(
    po: PurchaseOrder,
    received_per_line: dict[str, Decimal],
    rng: random.Random,
) -> list[_InvoiceLineData]:
    rows: list[_InvoiceLineData] = []
    has_qty_mismatch = rng.random() < _RATE_QTY_MISMATCH
    has_price_drift = rng.random() < _RATE_PRICE_DRIFT

    for po_line in po.lines:
        received_qty = received_per_line.get(str(po_line.id), Decimal("0"))
        if received_qty <= 0:
            continue

        invoiced_qty = received_qty
        unit_price = po_line.unit_price_net_eur

        if has_qty_mismatch and rng.random() < _QTY_MISMATCH_LINE_PROBABILITY:
            factor = Decimal(rng.choice(_QTY_MISMATCH_FACTORS_PCT)) / Decimal(100)
            invoiced_qty = (invoiced_qty * factor).quantize(Decimal("0.001"))
        if has_price_drift:
            lo, hi = _PRICE_DRIFT_FACTOR_RANGE_PCT
            factor = Decimal(rng.randint(lo, hi)) / Decimal(100)
            unit_price = (unit_price * factor).quantize(Decimal("0.0001"))

        net = (invoiced_qty * unit_price).quantize(Decimal("0.01"))
        vat = (net * _VAT_FACTOR).quantize(Decimal("0.01"))
        rows.append(_InvoiceLineData(
            po_line=po_line,
            quantity=invoiced_qty,
            unit_price=unit_price,
            net=net,
            vat=vat,
            gross=net + vat,
        ))
    return rows
