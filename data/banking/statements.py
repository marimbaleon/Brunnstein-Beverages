"""Bronze: bank account statements carrying the incoming customer payments.

Brunnstein changed its house bank at the end of 2023. Statements from 2023 are
exported in the legacy SWIFT MT940 text format; from 2024 the new bank delivers
ISO 20022 CAMT.053 XML. Same underlying payments, two very different file
formats: parsing both into one ledger is the Bronze -> Silver job, and matching
each credit line back to an open invoice (from the free-text remittance info)
is the cash-application use case.

Each monthly statement also carries one aggregated debit (the month's outgoing
supplier payments) so the running balance stays realistic and parsers have to
handle both credit and debit entries.

Files land under ``data/export/bronze/bank_statements/{mt940,camt053}/``.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET

from data.erp.models import Customer, PaymentReceived
from data.export import BRONZE_ROOT

_BRONZE_ROOT = BRONZE_ROOT / "bank_statements"

_LEGACY_IBAN = "DE12500105170648489890"
_LEGACY_BIC = "SOLADEST600"
_LEGACY_LAST_YEAR = 2023

_NEW_IBAN = "DE91100000000123456789"
_NEW_BIC = "HANDDEFFXXX"

_CAMT_NS = "urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"

_OPENING_BALANCE = Decimal("125000.00")
_DEBIT_SHARE = Decimal("0.80")  # outgoing supplier payments as a share of inflow


def _amount_mt940(value: Decimal) -> str:
    return f"{value:.2f}".replace(".", ",")


def _last_day(year: int, month: int) -> date:
    return date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)


def _group_by_month(
    payments: list[PaymentReceived],
) -> dict[tuple[int, int], list[PaymentReceived]]:
    by_month: dict[tuple[int, int], list[PaymentReceived]] = defaultdict(list)
    for p in payments:
        by_month[(p.payment_date.year, p.payment_date.month)].append(p)
    for entries in by_month.values():
        entries.sort(key=lambda p: p.payment_date)
    return dict(by_month)


def write_bank_statements(
    payments: list[PaymentReceived],
    customers: list[Customer],
    out_dir: Path = _BRONZE_ROOT,
) -> list[Path]:
    """Write monthly statements (MT940 for 2023, CAMT.053 from 2024)."""
    name_by_id = {c.id: c.name for c in customers}
    by_month = _group_by_month(payments)

    mt940_dir = out_dir / "mt940"
    camt_dir = out_dir / "camt053"
    mt940_dir.mkdir(parents=True, exist_ok=True)
    camt_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    balance = _OPENING_BALANCE
    seq = 0
    for year, month in sorted(by_month):
        entries = by_month[(year, month)]
        seq += 1
        credits_total = sum((p.amount_eur for p in entries), Decimal("0"))
        debit_lump = (credits_total * _DEBIT_SHARE).quantize(Decimal("0.01"))
        opening = balance
        closing = opening + credits_total - debit_lump

        legacy = year <= _LEGACY_LAST_YEAR
        if legacy:
            text = _mt940_statement(
                entries, name_by_id, year, month, seq, opening, closing, debit_lump
            )
            path = mt940_dir / f"{year}-{month:02d}_{_LEGACY_IBAN}.sta"
            path.write_text(text, encoding="utf-8")
        else:
            xml = _camt_statement(
                entries, name_by_id, year, month, seq, opening, closing, debit_lump
            )
            path = camt_dir / f"{year}-{month:02d}_{_NEW_IBAN}.xml"
            path.write_text(xml, encoding="utf-8")

        written.append(path)
        balance = closing

    return written


def _mt940_statement(
    entries: list[PaymentReceived],
    name_by_id: dict,
    year: int,
    month: int,
    seq: int,
    opening: Decimal,
    closing: Decimal,
    debit_lump: Decimal,
) -> str:
    last = _last_day(year, month) - timedelta(days=1)
    open_yymmdd = date(year, month, 1).strftime("%y%m%d")
    close_yymmdd = last.strftime("%y%m%d")

    lines: list[str] = []
    lines.append(f":20:STMT{year}{month:02d}")
    lines.append(f":25:{_LEGACY_IBAN} EUR")
    lines.append(f":28C:{seq:05d}/001")
    lines.append(f":60F:C{open_yymmdd}EUR{_amount_mt940(opening)}")

    for p in entries:
        value = p.payment_date.strftime("%y%m%d")
        entry = p.payment_date.strftime("%m%d")
        lines.append(f":61:{value}{entry}CR{_amount_mt940(p.amount_eur)}NTRFNONREF//")
        debtor = name_by_id.get(p.customer_id, "")
        info = p.remittance_info or ""
        detail = info if (debtor and debtor in info) else f"{info} {debtor}".strip()
        lines.append(f":86:{detail}")

    # Aggregated outgoing supplier payments for the month.
    lines.append(
        f":61:{close_yymmdd}{last.strftime('%m%d')}DR{_amount_mt940(debit_lump)}NTRFNONREF//"
    )
    lines.append(":86:Sammelzahlung Kreditoren")
    lines.append(f":62F:C{close_yymmdd}EUR{_amount_mt940(closing)}")
    return "\n".join(lines) + "\n"


def _camt_statement(
    entries: list[PaymentReceived],
    name_by_id: dict,
    year: int,
    month: int,
    seq: int,
    opening: Decimal,
    closing: Decimal,
    debit_lump: Decimal,
) -> str:
    ET.register_namespace("", _CAMT_NS)
    doc = ET.Element(f"{{{_CAMT_NS}}}Document")
    stmt_root = ET.SubElement(doc, f"{{{_CAMT_NS}}}BkToCstmrStmt")

    last = _last_day(year, month) - timedelta(days=1)
    cre_dt = f"{last.isoformat()}T08:00:00"

    grp = ET.SubElement(stmt_root, f"{{{_CAMT_NS}}}GrpHdr")
    _sub(grp, "MsgId", f"CAMT-{year}{month:02d}-{seq:05d}")
    _sub(grp, "CreDtTm", cre_dt)

    stmt = ET.SubElement(stmt_root, f"{{{_CAMT_NS}}}Stmt")
    _sub(stmt, "Id", f"{year}{month:02d}{seq:05d}")
    _sub(stmt, "CreDtTm", cre_dt)

    acct = ET.SubElement(stmt, f"{{{_CAMT_NS}}}Acct")
    acct_id = ET.SubElement(acct, f"{{{_CAMT_NS}}}Id")
    _sub(acct_id, "IBAN", _NEW_IBAN)

    _balance(stmt, "OPBD", opening, date(year, month, 1))
    _balance(stmt, "CLBD", closing, last)

    for p in entries:
        debtor = name_by_id.get(p.customer_id, "")
        _entry(stmt, p.amount_eur, "CRDT", p.payment_date, p.remittance_info, debtor)
    _entry(stmt, debit_lump, "DBIT", last, "Sammelzahlung Kreditoren", None)

    ET.indent(doc, space="  ")
    body = ET.tostring(doc, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + body + "\n"


def _sub(parent: ET.Element, tag: str, text: str) -> ET.Element:
    el = ET.SubElement(parent, f"{{{_CAMT_NS}}}{tag}")
    el.text = text
    return el


def _balance(stmt: ET.Element, code: str, amount: Decimal, when: date) -> None:
    bal = ET.SubElement(stmt, f"{{{_CAMT_NS}}}Bal")
    tp = ET.SubElement(bal, f"{{{_CAMT_NS}}}Tp")
    cd = ET.SubElement(tp, f"{{{_CAMT_NS}}}CdOrPrtry")
    _sub(cd, "Cd", code)
    amt = _sub(bal, "Amt", f"{amount:.2f}")
    amt.set("Ccy", "EUR")
    _sub(bal, "CdtDbtInd", "CRDT")
    dt = ET.SubElement(bal, f"{{{_CAMT_NS}}}Dt")
    _sub(dt, "Dt", when.isoformat())


def _entry(
    stmt: ET.Element,
    amount: Decimal,
    indicator: str,
    when: date,
    remittance: str | None,
    debtor: str | None,
) -> None:
    ntry = ET.SubElement(stmt, f"{{{_CAMT_NS}}}Ntry")
    amt = _sub(ntry, "Amt", f"{amount:.2f}")
    amt.set("Ccy", "EUR")
    _sub(ntry, "CdtDbtInd", indicator)
    _sub(ntry, "Sts", "BOOK")
    bookg = ET.SubElement(ntry, f"{{{_CAMT_NS}}}BookgDt")
    _sub(bookg, "Dt", when.isoformat())

    details = ET.SubElement(ntry, f"{{{_CAMT_NS}}}NtryDtls")
    tx = ET.SubElement(details, f"{{{_CAMT_NS}}}TxDtls")
    if debtor:
        parties = ET.SubElement(tx, f"{{{_CAMT_NS}}}RltdPties")
        dbtr = ET.SubElement(parties, f"{{{_CAMT_NS}}}Dbtr")
        _sub(dbtr, "Nm", debtor)
    if remittance:
        rmt = ET.SubElement(tx, f"{{{_CAMT_NS}}}RmtInf")
        _sub(rmt, "Ustrd", remittance)
