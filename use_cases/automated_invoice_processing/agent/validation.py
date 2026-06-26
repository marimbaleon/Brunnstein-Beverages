"""Validate an extracted invoice against the operational database.

Emits a list of `Signal` codes the decision step turns into a verdict.
The codes match the ones in test_invoices/<scenario>/<id>.json so the
eval suite can compare apples to apples.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy.orm import Session, selectinload

from data.erp.models import (
    GoodsReceipt,
    PurchaseOrder,
    Supplier,
)
from use_cases.automated_invoice_processing.agent.policy import (
    QUANTITY_TOLERANCE,
    UNIT_PRICE_TOLERANCE,
)
from use_cases.automated_invoice_processing.agent.schema import ExtractedInvoice
from use_cases.automated_invoice_processing.agent.signals import Signal

logger = logging.getLogger(__name__)


def validate_invoice(
    session: Session, extracted: ExtractedInvoice,
) -> tuple[list[Signal], list[str]]:
    """Return (signals, human_readable_notes) for the extracted invoice."""
    signals: list[Signal] = []
    notes: list[str] = []

    supplier = _check_supplier(session, extracted, signals, notes)
    po = _check_purchase_order(session, extracted, supplier, signals, notes)

    if po is not None:
        _check_three_way_match(session, extracted, po, signals, notes)

    return signals, notes


def _check_supplier(
    session: Session,
    extracted: ExtractedInvoice,
    signals: list[Signal],
    notes: list[str],
) -> Supplier | None:
    logger.info("looking up supplier by name: %s", extracted.supplier_name)
    supplier = _find_supplier_by_name(session, extracted.supplier_name)

    if supplier is None:
        logger.warning("supplier not found in master data")
        signals.append(Signal.supplier_unknown)
        notes.append(f"No supplier found matching '{extracted.supplier_name}'.")
        return None

    logger.info("supplier matched: %s", supplier.supplier_number)
    iban_signals = _compare_iban_against_master(
        extracted.payment_iban, supplier.iban,
    )
    if iban_signals:
        logger.warning(
            "iban check: %s (pdf=%s master=%s)",
            iban_signals, extracted.payment_iban, supplier.iban,
        )
    else:
        logger.info("iban check: match")
    signals.extend(iban_signals)
    return supplier


def _check_purchase_order(
    session: Session,
    extracted: ExtractedInvoice,
    supplier: Supplier | None,
    signals: list[Signal],
    notes: list[str],
) -> PurchaseOrder | None:
    if extracted.po_number is None:
        return None

    logger.info("looking up purchase order: %s", extracted.po_number)
    po = _find_purchase_order_by_number(session, extracted.po_number)

    if po is None:
        logger.warning("po not found")
        signals.append(Signal.po_not_found)
        notes.append(f"PO {extracted.po_number} does not exist in the system.")
        return None

    logger.info("po matched: status=%s lines=%d", po.status.value, len(po.lines))
    if supplier is not None and po.supplier_id != supplier.id:
        signals.append(Signal.po_supplier_mismatch)
        notes.append(
            f"PO {po.po_number} belongs to {po.supplier.name}, "
            f"not {extracted.supplier_name}."
        )
    return po


def _check_three_way_match(
    session: Session,
    extracted: ExtractedInvoice,
    po: PurchaseOrder,
    signals: list[Signal],
    notes: list[str],
) -> None:
    received_per_line = _sum_received_quantity_per_po_line(session, po.id)
    if not received_per_line:
        logger.warning("no goods receipts recorded for this po")
        signals.append(Signal.no_matching_goods_receipt)
        notes.append(f"PO {po.po_number} has no recorded goods receipts yet.")
        return

    logger.info(
        "comparing %d invoice lines against %d received po lines",
        len(extracted.lines), len(received_per_line),
    )
    _compare_invoice_lines_to_po(
        extracted, po, received_per_line, signals, notes,
    )


def _find_supplier_by_name(session: Session, name: str) -> Supplier | None:
    return session.query(Supplier).filter(Supplier.name == name.strip()).first()


def _find_purchase_order_by_number(
    session: Session, po_number: str,
) -> PurchaseOrder | None:
    return (
        session.query(PurchaseOrder)
        .options(
            selectinload(PurchaseOrder.lines),
            selectinload(PurchaseOrder.supplier),
        )
        .filter(PurchaseOrder.po_number == po_number)
        .first()
    )


def _sum_received_quantity_per_po_line(
    session: Session, po_id,
) -> dict[str, Decimal]:
    """Total quantity received for each PO line across all goods receipts."""
    receipts = (
        session.query(GoodsReceipt)
        .options(selectinload(GoodsReceipt.lines))
        .filter(GoodsReceipt.purchase_order_id == po_id)
        .all()
    )
    totals: dict[str, Decimal] = {}
    for receipt in receipts:
        for line in receipt.lines:
            key = str(line.purchase_order_line_id)
            totals[key] = totals.get(key, Decimal("0")) + line.quantity_received
    return totals


def _compare_iban_against_master(
    invoice_iban: str | None, master_iban: str,
) -> list[Signal]:
    """Empty list if they match. Otherwise the appropriate mismatch signal."""
    if not invoice_iban:
        return [Signal.iban_missing]
    if invoice_iban == master_iban:
        return []
    if _is_last_two_digits_swapped(invoice_iban, master_iban):
        # Canonical low-effort typo or low-effort fraud signal.
        return [Signal.iban_mismatch_typo]
    return [Signal.iban_mismatch_full]


def _is_last_two_digits_swapped(a: str, b: str) -> bool:
    return (
        len(a) == len(b)
        and a[:-2] == b[:-2]
        and a[-1] == b[-2]
        and a[-2] == b[-1]
    )


def _compare_invoice_lines_to_po(
    extracted: ExtractedInvoice,
    po: PurchaseOrder,
    received_per_line: dict[str, Decimal],
    signals: list[Signal],
    notes: list[str],
) -> None:
    po_lines_by_description = {line.description: line for line in po.lines}
    quantity_off = False
    price_off = False

    for invoice_line in extracted.lines:
        po_line = po_lines_by_description.get(invoice_line.description)
        if po_line is None:
            continue

        received_quantity = received_per_line.get(str(po_line.id), Decimal("0"))
        if received_quantity > 0:
            quantity_delta = (
                abs(invoice_line.quantity - received_quantity) / received_quantity
            )
            if quantity_delta > QUANTITY_TOLERANCE:
                quantity_off = True
                notes.append(
                    f"Line '{invoice_line.description}': invoice "
                    f"{invoice_line.quantity} vs goods receipt "
                    f"{received_quantity} ({quantity_delta:.1%} delta)."
                )

        if po_line.unit_price_net_eur > 0:
            price_delta = (
                (invoice_line.unit_price_net_eur - po_line.unit_price_net_eur)
                / po_line.unit_price_net_eur
            )
            if price_delta > UNIT_PRICE_TOLERANCE:
                price_off = True
                notes.append(
                    f"Line '{invoice_line.description}': invoice price "
                    f"{invoice_line.unit_price_net_eur} vs PO "
                    f"{po_line.unit_price_net_eur} ({price_delta:.1%} drift)."
                )

    if quantity_off:
        signals.append(Signal.quantity_mismatch_vs_goods_receipt)
    if price_off:
        signals.append(Signal.unit_price_drift)
