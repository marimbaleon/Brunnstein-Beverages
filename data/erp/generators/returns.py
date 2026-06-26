"""Generate B2B customer returns and the credit notes that settle them.

A small share of customer invoices trigger a return: some lines come back for a
quality defect, damage, a wrong delivery or overstock. Quality-defect returns
quote a batch that actually failed a production quality check (when one exists
for that product), so the return joins back to the run that caused it. Every
received return is settled with a credit note reversing net + VAT.
"""

from __future__ import annotations

import random
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from data.erp.models import (
    CreditNote,
    CustomerInvoice,
    CustomerReturn,
    CustomerReturnLine,
    ProductionRun,
    QualityResult,
    ReturnReason,
    ReturnStatus,
)

_VAT = Decimal("0.19")
_CENT = Decimal("0.01")
_RETURN_RATE = 0.04  # share of invoices that see a return

_REASON_WEIGHTS = [
    (ReturnReason.damaged, 38),
    (ReturnReason.quality_defect, 30),
    (ReturnReason.wrong_delivery, 18),
    (ReturnReason.overstock, 14),
]
# Most returns are accepted and credited; a few are rejected or still in flight.
_STATUS_WEIGHTS = [
    (ReturnStatus.credited, 64),
    (ReturnStatus.received, 18),
    (ReturnStatus.requested, 10),
    (ReturnStatus.rejected, 8),
]


def _defective_batches_by_product(runs: list[ProductionRun]) -> dict:
    by_product: dict = defaultdict(list)
    for run in runs:
        if any(c.result == QualityResult.fail for c in run.quality_checks):
            by_product[run.product_id].append(run.batch_number)
    return by_product


def generate_returns(
    customer_invoices: list[CustomerInvoice],
    production_runs: list[ProductionRun],
    today: date = date(2026, 1, 15),
    seed: int = 42,
) -> tuple[list[CustomerReturn], list[CreditNote]]:
    """Build customer returns and their credit notes. Returns (returns, credit_notes)."""
    rng = random.Random(seed + 35)
    defective = _defective_batches_by_product(production_runs)
    reasons = [r for r, _ in _REASON_WEIGHTS]
    reason_w = [w for _, w in _REASON_WEIGHTS]
    statuses = [s for s, _ in _STATUS_WEIGHTS]
    status_w = [w for _, w in _STATUS_WEIGHTS]

    returns: list[CustomerReturn] = []
    credit_notes: list[CreditNote] = []
    ret_counter: dict[int, int] = defaultdict(int)
    cn_counter: dict[int, int] = defaultdict(int)

    for invoice in sorted(customer_invoices, key=lambda i: i.customer_invoice_number):
        if not invoice.lines or rng.random() > _RETURN_RATE:
            continue

        return_date = invoice.invoice_date + timedelta(days=rng.randint(5, 45))
        if return_date > today:
            continue

        reason = rng.choices(reasons, weights=reason_w, k=1)[0]
        n_lines = min(rng.randint(1, 2), len(invoice.lines))
        picked = rng.sample(invoice.lines, n_lines)

        year = return_date.year
        ret_counter[year] += 1
        ret = CustomerReturn(
            id=uuid4(),
            return_number=f"RET-{year}-{ret_counter[year]:06d}",
            customer_id=invoice.customer_id,
            customer_invoice_id=invoice.id,
            return_date=return_date,
            reason=reason,
            status=rng.choices(statuses, weights=status_w, k=1)[0],
            batch_number=None,
            total_net_eur=Decimal("0.00"),
        )
        ret.customer = invoice.customer

        total_net = Decimal("0.00")
        for n, inv_line in enumerate(picked, start=1):
            # Return a fraction of the invoiced quantity.
            frac = Decimal(str(rng.choice([0.25, 0.5, 0.5, 1.0])))
            qty = (inv_line.quantity_units * frac).quantize(Decimal("0.001"))
            line_net = (inv_line.unit_price_net_eur * qty).quantize(_CENT)
            total_net += line_net
            ret.lines.append(CustomerReturnLine(
                id=uuid4(),
                customer_return_id=ret.id,
                line_number=n,
                product_id=inv_line.product_id,
                quantity_units=qty,
                line_net_eur=line_net,
            ))
            if reason == ReturnReason.quality_defect and ret.batch_number is None:
                batches = defective.get(inv_line.product_id)
                if batches:
                    ret.batch_number = rng.choice(batches)

        ret.total_net_eur = total_net.quantize(_CENT)
        returns.append(ret)

        if ret.status == ReturnStatus.credited:
            cn_counter[year] += 1
            vat = (total_net * _VAT).quantize(_CENT)
            credit_notes.append(CreditNote(
                id=uuid4(),
                credit_note_number=f"CN-{year}-{cn_counter[year]:06d}",
                customer_id=invoice.customer_id,
                customer_return_id=ret.id,
                customer_invoice_id=invoice.id,
                credit_date=return_date + timedelta(days=rng.randint(1, 10)),
                total_net_eur=total_net.quantize(_CENT),
                total_vat_eur=vat,
                total_gross_eur=(total_net + vat).quantize(_CENT),
            ))

    return returns, credit_notes
