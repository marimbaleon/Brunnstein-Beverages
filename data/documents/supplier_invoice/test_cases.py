"""Generate adversarial test invoices for the validation agent.

Eight scenarios spanning clean matches, IBAN fraud, missing references, and
data discrepancies. Each scenario writes one PDF and one meta.json describing
the expected agent outcome.

    uv run python -m data.pdf.supplier_invoice.test_cases

Output lands in test_invoices/<scenario>/ and is committed so reviewers see
the eval fixtures on GitHub.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from data.erp.load_to_dsql import get_engine
from data.erp.models import (
    ExtractionStatus,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    Supplier,
    SupplierInvoice,
    SupplierInvoiceLine,
    SupplierInvoiceStatus,
)
from data.pdf.supplier_invoice.layouts import Context, render

load_dotenv()

_DEFAULT_OUT = "test_invoices"


@dataclass
class TestCase:
    slug: str
    description: str
    expected_outcome: str
    expected_signals: list[str]
    context: Context


# DB queries used to seed the realistic scenarios.


def _closed_pos_distinct_suppliers(session: Session, n: int) -> list[PurchaseOrder]:
    """Return n closed POs, each from a different supplier.

    Iterates recent closed POs and keeps the first one per supplier so the
    scenarios feature varied suppliers (and therefore varied PDF layouts).
    """
    stmt = (
        select(PurchaseOrder)
        .options(
            selectinload(PurchaseOrder.supplier),
            selectinload(PurchaseOrder.lines),
        )
        .where(PurchaseOrder.status == PurchaseOrderStatus.closed)
        .order_by(PurchaseOrder.order_date.desc())
    )
    seen: set = set()
    selected: list[PurchaseOrder] = []
    for po in session.execute(stmt).scalars():
        if po.supplier_id in seen:
            continue
        seen.add(po.supplier_id)
        selected.append(po)
        if len(selected) >= n:
            break
    return selected


def _open_po_without_receipts(session: Session) -> PurchaseOrder:
    stmt = (
        select(PurchaseOrder)
        .options(
            selectinload(PurchaseOrder.supplier),
            selectinload(PurchaseOrder.lines),
        )
        .where(PurchaseOrder.status == PurchaseOrderStatus.open)
        .order_by(PurchaseOrder.order_date.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one()


# Builders that turn a (Supplier, PurchaseOrder) into a rendered Context.


def _build_invoice(
    supplier: Supplier,
    po: PurchaseOrder,
    invoice_number: str,
    payment_iban: str | None = None,
    quantity_factor: Decimal = Decimal("1.0"),
    price_factor: Decimal = Decimal("1.0"),
    po_number_override: str | None = None,
) -> Context:
    # Pinned so committed test fixtures don't churn day-to-day.
    invoice_date = date(2026, 1, 15)
    due_date = invoice_date + timedelta(days=supplier.payment_terms_days or 30)

    lines: list[SupplierInvoiceLine] = []
    total_net = Decimal("0")
    for po_line in po.lines:
        qty = (po_line.quantity * quantity_factor).quantize(Decimal("0.001"))
        unit_price = (po_line.unit_price_net_eur * price_factor).quantize(Decimal("0.0001"))
        line_net = (qty * unit_price).quantize(Decimal("0.01"))
        line_vat = (line_net * Decimal("0.19")).quantize(Decimal("0.01"))
        line_gross = line_net + line_vat
        total_net += line_net
        lines.append(SupplierInvoiceLine(
            id=uuid4(),
            line_number=po_line.line_number,
            description=po_line.description,
            raw_material_id=po_line.raw_material_id,
            purchase_order_line_id=po_line.id,
            quantity=qty,
            unit_price_net_eur=unit_price,
            vat_rate_pct=Decimal("19.00"),
            line_net_eur=line_net,
            line_vat_eur=line_vat,
            line_gross_eur=line_gross,
        ))

    total_vat = (total_net * Decimal("0.19")).quantize(Decimal("0.01"))
    total_gross = total_net + total_vat

    invoice = SupplierInvoice(
        id=uuid4(),
        supplier_invoice_number=invoice_number,
        supplier_id=supplier.id,
        purchase_order_id=po.id,
        source_s3_key="",
        invoice_date=invoice_date,
        due_date=due_date,
        total_net_eur=total_net,
        total_vat_eur=total_vat,
        total_gross_eur=total_gross,
        payment_iban=payment_iban or supplier.iban,
        status=SupplierInvoiceStatus.received,
        extraction_status=ExtractionStatus.pending,
    )

    # If we want the PDF to reference a non-existent PO number, override the
    # displayed string without changing the FK.
    if po_number_override is not None:
        po = _po_with_number(po, po_number_override)

    return Context(invoice=invoice, supplier=supplier, purchase_order=po, lines=lines)


def _po_with_number(po: PurchaseOrder, new_number: str) -> PurchaseOrder:
    """Return a shallow copy of the PO with a different po_number for display."""
    clone = PurchaseOrder(
        id=po.id,
        po_number=new_number,
        supplier_id=po.supplier_id,
        order_date=po.order_date,
        requested_delivery_date=po.requested_delivery_date,
        status=po.status,
        total_net_eur=po.total_net_eur,
        total_vat_eur=po.total_vat_eur,
        total_gross_eur=po.total_gross_eur,
    )
    clone.supplier = po.supplier
    clone.lines = list(po.lines)
    return clone


def _invent_supplier() -> Supplier:
    """A plausible-looking German supplier that does NOT exist in the master."""
    return Supplier(
        id=uuid4(),
        supplier_number="S-99999",
        name="Hamburger Maschinenbau Schmidt GmbH",
        vat_id="DE999888777",
        iban="DE56340500000000999888",
        bic="DEUTDEDB123",
        payment_terms_days=30,
        street="Hafenstraße 88",
        postal_code="20457",
        city="Hamburg",
        country="DE",
        email="kontakt@hh-maschinenbau-schmidt.de",
        phone="+49 40 99999999",
        active=True,
    )


# Scenarios


def _scenario_clean_match(po: PurchaseOrder) -> TestCase:
    ctx = _build_invoice(po.supplier, po, invoice_number="tc-001-clean")
    return TestCase(
        slug="01_clean_match",
        description=(
            "Invoice cleanly matches an existing PO. Supplier, IBAN, line "
            "quantities and prices all align with master data and goods receipts."
        ),
        expected_outcome="approve",
        expected_signals=[],
        context=ctx,
    )


def _scenario_iban_fraud(po: PurchaseOrder) -> TestCase:
    rogue_iban = "DE89370400440532013000"  # plausible DE iban, not the supplier's
    ctx = _build_invoice(po.supplier, po, invoice_number="tc-002-fraud",
                         payment_iban=rogue_iban)
    return TestCase(
        slug="02_iban_fraud",
        description="Invoice references a completely different IBAN than the supplier master.",
        expected_outcome="flag_for_fraud_review",
        expected_signals=["iban_mismatch_full"],
        context=ctx,
    )


def _scenario_iban_typo(po: PurchaseOrder) -> TestCase:
    iban = po.supplier.iban
    typo = iban[:-2] + iban[-1] + iban[-2]
    ctx = _build_invoice(po.supplier, po, invoice_number="tc-003-typo",
                         payment_iban=typo)
    return TestCase(
        slug="03_iban_typo",
        description="Invoice IBAN has the last two digits swapped. Possible typo or low-effort fraud.",
        expected_outcome="flag_for_review",
        expected_signals=["iban_mismatch_typo"],
        context=ctx,
    )


def _scenario_po_not_found(po: PurchaseOrder) -> TestCase:
    ctx = _build_invoice(po.supplier, po, invoice_number="tc-004-nopo",
                         po_number_override="PO-2099-999999")
    return TestCase(
        slug="04_po_not_found",
        description="Invoice references a PO number that does not exist in the system.",
        expected_outcome="flag_for_review",
        expected_signals=["po_not_found"],
        context=ctx,
    )


def _scenario_supplier_not_in_master(po: PurchaseOrder) -> TestCase:
    unknown_supplier = _invent_supplier()
    # Keep the PO data so the layout has line items, but display a fake PO ref.
    ctx = _build_invoice(unknown_supplier, po, invoice_number="tc-005-unknown",
                         po_number_override="PO-2025-555555")
    return TestCase(
        slug="05_supplier_not_in_master",
        description="Supplier name does not match any record in supplier master data.",
        expected_outcome="flag_for_review",
        expected_signals=["supplier_unknown", "po_not_found"],
        context=ctx,
    )


def _scenario_quantity_discrepancy(po: PurchaseOrder) -> TestCase:
    ctx = _build_invoice(po.supplier, po, invoice_number="tc-006-qty",
                         quantity_factor=Decimal("1.12"))
    return TestCase(
        slug="06_quantity_discrepancy",
        description="Invoice quantities are ~12 percent higher than the goods receipt records.",
        expected_outcome="flag_for_review",
        expected_signals=["quantity_mismatch_vs_goods_receipt"],
        context=ctx,
    )


def _scenario_price_drift(po: PurchaseOrder) -> TestCase:
    ctx = _build_invoice(po.supplier, po, invoice_number="tc-007-price",
                         price_factor=Decimal("1.15"))
    return TestCase(
        slug="07_price_drift",
        description="Invoice unit prices are ~15 percent higher than agreed on the PO.",
        expected_outcome="flag_for_review",
        expected_signals=["unit_price_drift"],
        context=ctx,
    )


def _scenario_early_invoice(po_without_gr: PurchaseOrder) -> TestCase:
    ctx = _build_invoice(po_without_gr.supplier, po_without_gr, invoice_number="tc-008-early")
    return TestCase(
        slug="08_early_invoice",
        description="Supplier is invoicing for a PO that has not yet been received in the warehouse.",
        expected_outcome="hold_for_goods_receipt",
        expected_signals=["no_matching_goods_receipt"],
        context=ctx,
    )


def all_test_cases(session: Session) -> list[TestCase]:
    pos = _closed_pos_distinct_suppliers(session, 7)
    open_po = _open_po_without_receipts(session)
    return [
        _scenario_clean_match(pos[0]),
        _scenario_iban_fraud(pos[1]),
        _scenario_iban_typo(pos[2]),
        _scenario_po_not_found(pos[3]),
        _scenario_supplier_not_in_master(pos[4]),
        _scenario_quantity_discrepancy(pos[5]),
        _scenario_price_drift(pos[6]),
        _scenario_early_invoice(open_po),
    ]


def generate(out_dir: str = _DEFAULT_OUT) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    engine = get_engine()
    with Session(engine) as session:
        cases = all_test_cases(session)

    for case in cases:
        case_dir = out / case.slug
        case_dir.mkdir(parents=True, exist_ok=True)

        invoice_id = case.context.invoice.supplier_invoice_number
        pdf_bytes = render(case.context)
        (case_dir / f"{invoice_id}.pdf").write_bytes(pdf_bytes)

        meta = {
            "slug": case.slug,
            "description": case.description,
            "expected_outcome": case.expected_outcome,
            "expected_signals": case.expected_signals,
            "invoice_number": invoice_id,
            "supplier_displayed": case.context.supplier.name,
            "po_displayed": case.context.purchase_order.po_number,
        }
        (case_dir / f"{invoice_id}.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False) + "\n"
        )

    return {"out_dir": str(out), "count": len(cases)}


if __name__ == "__main__":
    result = generate()
    print(f"wrote {result['count']} test cases to {result['out_dir']}/")
