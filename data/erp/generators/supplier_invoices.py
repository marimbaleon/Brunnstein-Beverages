"""Generate incoming supplier invoices, with a small share of discrepancies for the
validation agent to catch later (IBAN drift, price drift, quantity mismatch).
"""

from __future__ import annotations

import random
import re
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

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


def _slug(name: str) -> str:
    s = name.lower()
    s = s.translate(str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}))
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


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
    inv_counter = 0

    for po_id, receipts in by_po.items():
        po: PurchaseOrder = receipts[0].purchase_order
        if po.status == PurchaseOrderStatus.cancelled:
            continue
        supplier = po.supplier

        inv_counter += 1
        # Invoice issued by the supplier 0-14 days after the last receipt.
        last_receipt_date = max(gr.received_date for gr in receipts)
        invoice_date = last_receipt_date + timedelta(days=rng.randint(0, 14))
        due_date = invoice_date + timedelta(days=supplier.payment_terms_days or 30)
        year = invoice_date.year

        s3_key = f"invoices/{year}/{_slug(supplier.name)}/{inv_counter:07d}.pdf"

        # Per-line invoiced quantities: usually match received, occasionally drift.
        received_per_line = _aggregate_received(receipts)

        inv_lines_data: list[tuple] = []
        price_drift = rng.random() < _RATE_PRICE_DRIFT
        qty_mismatch = rng.random() < _RATE_QTY_MISMATCH

        for po_line in po.lines:
            received_qty = received_per_line.get(str(po_line.id), Decimal("0"))
            if received_qty <= 0:
                continue
            invoiced_qty = received_qty
            unit_price = po_line.unit_price_net_eur
            if qty_mismatch and rng.random() < 0.5:
                # Bump or drop quantity by 5-15%
                factor = Decimal(rng.choice([85, 92, 108, 115])) / Decimal(100)
                invoiced_qty = (invoiced_qty * factor).quantize(Decimal("0.001"))
            if price_drift:
                # Price up by 3-10%
                factor = Decimal(rng.randint(103, 110)) / Decimal(100)
                unit_price = (unit_price * factor).quantize(Decimal("0.0001"))
            net = (invoiced_qty * unit_price).quantize(Decimal("0.01"))
            vat = (net * _VAT_FACTOR).quantize(Decimal("0.01"))
            gross = net + vat
            inv_lines_data.append((po_line, invoiced_qty, unit_price, net, vat, gross))

        if not inv_lines_data:
            inv_counter -= 1
            continue

        total_net = sum((row[3] for row in inv_lines_data), Decimal("0"))
        total_vat = sum((row[4] for row in inv_lines_data), Decimal("0"))
        total_gross = sum((row[5] for row in inv_lines_data), Decimal("0"))

        inv = SupplierInvoice(
            id=uuid4(),
            supplier_invoice_number=f"RG-{year}-{inv_counter:07d}",
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

        for i, (po_line, qty, price, net, vat, gross) in enumerate(inv_lines_data, start=1):
            line = SupplierInvoiceLine(
                id=uuid4(),
                supplier_invoice_id=inv.id,
                line_number=i,
                description=po_line.description,
                raw_material_id=po_line.raw_material_id,
                purchase_order_line_id=po_line.id,
                quantity=qty,
                unit_price_net_eur=price,
                vat_rate_pct=_DEFAULT_VAT_PCT,
                line_net_eur=net,
                line_vat_eur=vat,
                line_gross_eur=gross,
            )
            inv.lines.append(line)

        invoices.append(inv)

    return invoices
