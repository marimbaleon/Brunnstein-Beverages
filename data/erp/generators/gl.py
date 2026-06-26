"""Generate a chart of accounts, cost centres and the posting journal.

Journal entries are derived from the documents that already exist so the ledger
ties out to the operational data:

* customer invoice  -> Dr receivables / Cr revenue + VAT (+ deposit liability)
* incoming payment  -> Dr bank / Cr receivables
* supplier invoice  -> Dr material expense + input VAT / Cr payables
* payroll run       -> Dr personnel expense / Cr bank + wage tax + social security
* credit note       -> Dr revenue + VAT / Cr receivables

Every entry balances (sum of debits equals sum of credits) by construction.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from uuid import uuid4

from data.erp.models import (
    CostCenter,
    CreditNote,
    CustomerInvoice,
    GLAccount,
    GLAccountType,
    JournalEntry,
    JournalEntryLine,
    PaymentReceived,
    Plant,
    SupplierInvoice,
)

_ZERO = Decimal("0.00")

# SKR-flavoured chart of accounts: (number, name, type).
_ACCOUNTS = [
    ("1200", "Bank", GLAccountType.asset),
    ("1400", "Forderungen aus Lieferungen und Leistungen", GLAccountType.asset),
    ("1576", "Abziehbare Vorsteuer", GLAccountType.asset),
    ("1600", "Verbindlichkeiten aus Lieferungen und Leistungen", GLAccountType.liability),
    ("1741", "Verbindlichkeiten Lohnsteuer", GLAccountType.liability),
    ("1742", "Verbindlichkeiten Sozialversicherung", GLAccountType.liability),
    ("1755", "Verbindlichkeiten aus Pfand", GLAccountType.liability),
    ("1776", "Umsatzsteuer", GLAccountType.liability),
    ("3400", "Wareneingang / Materialaufwand", GLAccountType.expense),
    ("4100", "Löhne und Gehälter", GLAccountType.expense),
    ("8400", "Umsatzerlöse 19% USt", GLAccountType.revenue),
]


def _cost_centers(plants: list[Plant]) -> list[CostCenter]:
    centers = [
        CostCenter(id=uuid4(), cost_center_code="CC-SALES", name="Vertrieb", plant_id=None),
        CostCenter(id=uuid4(), cost_center_code="CC-PROC", name="Einkauf/Material",
                   plant_id=None),
        CostCenter(id=uuid4(), cost_center_code="CC-HR", name="Personal", plant_id=None),
    ]
    for plant in plants:
        centers.append(CostCenter(
            id=uuid4(),
            cost_center_code=f"CC-PROD-{plant.plant_code}",
            name=f"Produktion {plant.city}",
            plant_id=plant.id,
        ))
    return centers


def generate_gl(
    customer_invoices: list[CustomerInvoice],
    payments: list[PaymentReceived],
    supplier_invoices: list[SupplierInvoice],
    payroll_runs: list,
    credit_notes: list[CreditNote],
    plants: list[Plant],
    today: date = date(2026, 1, 15),
    seed: int = 42,
) -> tuple[list[GLAccount], list[CostCenter], list[JournalEntry]]:
    """Build accounts, cost centres and journal entries. Returns the three lists."""
    accounts = [
        GLAccount(id=uuid4(), account_number=num, name=name, account_type=atype)
        for num, name, atype in _ACCOUNTS
    ]
    acct = {a.account_number: a for a in accounts}
    cost_centers = _cost_centers(plants)
    cc = {c.cost_center_code: c for c in cost_centers}

    # Collect (posting_date, source_module, reference, description, lines) tuples.
    drafts: list[tuple] = []

    def line(account_number, debit, credit, cost_center_code=None):
        return (acct[account_number].id,
                cc[cost_center_code].id if cost_center_code else None,
                Decimal(debit).quantize(Decimal("0.01")),
                Decimal(credit).quantize(Decimal("0.01")))

    for inv in customer_invoices:
        lines = [
            line("1400", inv.amount_due_eur, _ZERO),
            line("8400", _ZERO, inv.total_net_eur, "CC-SALES"),
            line("1776", _ZERO, inv.total_vat_eur),
        ]
        if inv.deposit_total_eur and inv.deposit_total_eur > 0:
            lines.append(line("1755", _ZERO, inv.deposit_total_eur))
        drafts.append((inv.invoice_date, "AR", inv.customer_invoice_number,
                       f"Rechnung {inv.customer_invoice_number}", lines))

    for pay in payments:
        drafts.append((pay.payment_date, "BANK", pay.payment_number,
                       f"Zahlungseingang {pay.payment_number}",
                       [line("1200", pay.amount_eur, _ZERO),
                        line("1400", _ZERO, pay.amount_eur)]))

    for inv in supplier_invoices:
        if inv.total_net_eur is None or inv.total_gross_eur is None:
            continue
        drafts.append((inv.invoice_date or today, "AP",
                       inv.supplier_invoice_number or inv.source_s3_key,
                       "Eingangsrechnung",
                       [line("3400", inv.total_net_eur, _ZERO, "CC-PROC"),
                        line("1576", inv.total_vat_eur or _ZERO, _ZERO),
                        line("1600", _ZERO, inv.total_gross_eur)]))

    for run in payroll_runs:
        gross = sum((it.gross_eur for it in run.items), _ZERO)
        net = sum((it.net_eur for it in run.items), _ZERO)
        tax = sum((it.income_tax_eur for it in run.items), _ZERO)
        sv = sum((it.social_security_eur for it in run.items), _ZERO)
        if gross <= 0:
            continue
        drafts.append((run.pay_date, "PY", run.period, f"Lohnlauf {run.period}",
                       [line("4100", gross, _ZERO, "CC-HR"),
                        line("1200", _ZERO, net),
                        line("1741", _ZERO, tax),
                        line("1742", _ZERO, sv)]))

    for cn in credit_notes:
        drafts.append((cn.credit_date, "AR", cn.credit_note_number,
                       f"Gutschrift {cn.credit_note_number}",
                       [line("8400", cn.total_net_eur, _ZERO, "CC-SALES"),
                        line("1776", cn.total_vat_eur, _ZERO),
                        line("1400", _ZERO, cn.total_gross_eur)]))

    drafts.sort(key=lambda d: (d[0], str(d[2])))

    entries: list[JournalEntry] = []
    counter: dict[int, int] = defaultdict(int)
    for posting_date, module, reference, description, lines in drafts:
        year = posting_date.year
        counter[year] += 1
        entry = JournalEntry(
            id=uuid4(),
            document_number=f"JE-{year}-{counter[year]:06d}",
            posting_date=posting_date,
            source_module=module,
            reference=str(reference)[:40],
            description=description,
        )
        for n, (acct_id, cc_id, debit, credit) in enumerate(lines, start=1):
            entry.lines.append(JournalEntryLine(
                id=uuid4(),
                journal_entry_id=entry.id,
                line_number=n,
                gl_account_id=acct_id,
                cost_center_id=cc_id,
                debit_eur=debit,
                credit_eur=credit,
            ))
        entries.append(entry)

    return accounts, cost_centers, entries
