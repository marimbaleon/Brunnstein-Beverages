"""Dunning notices for overdue customer invoices, as ``.eml`` and ``.html``.

Each overdue invoice gets one notice at the level its age warrants: a friendly
payment reminder (Zahlungserinnerung), a first formal reminder (1. Mahnung) or a
final notice (letzte Mahnung) with a late fee. The ``.eml`` is a parseable
RFC 822 message (the email-intake side of an AR use case); the ``.html`` is the
rendered letter. To keep the output bounded the most overdue invoices are taken
first, up to ``max_notices``.

Files land under ``data/documents/dunning/``.
"""

from __future__ import annotations

import random
from datetime import UTC, date, datetime
from decimal import Decimal
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

from data.erp.models import CustomerInvoice, CustomerInvoiceStatus

_ROOT = Path(__file__).resolve().parent / "dunning"

# (level_key, label, max days overdue, late fee EUR)
_LEVELS = [
    ("reminder", "Zahlungserinnerung", 21, Decimal("0.00")),
    ("first", "1. Mahnung", 45, Decimal("5.00")),
    ("final", "Letzte Mahnung", 10**6, Decimal("10.00")),
]

_INTRO = {
    "reminder": (
        "sicher ist es Ihrer Aufmerksamkeit entgangen: Die folgende Rechnung ist "
        "noch offen. Wir bitten höflich um Ausgleich."
    ),
    "first": (
        "trotz unserer Zahlungserinnerung konnten wir bislang keinen Zahlungseingang "
        "feststellen. Wir fordern Sie auf, den offenen Betrag zu begleichen."
    ),
    "final": (
        "die nachstehende Forderung ist weiterhin offen. Dies ist unsere letzte "
        "Mahnung vor Einleitung weiterer Schritte."
    ),
}


def _slug(text: str) -> str:
    table = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})
    keep = text.lower().translate(table)
    return "".join(c for c in keep if c.isalnum())[:24] or "kunde"


def _level_for(days_overdue: int) -> tuple[str, str, Decimal]:
    for key, label, max_days, fee in _LEVELS:
        if days_overdue <= max_days:
            return key, label, fee
    return _LEVELS[-1][0], _LEVELS[-1][1], _LEVELS[-1][3]


def _body_text(invoice: CustomerInvoice, label: str, key: str, fee: Decimal, days: int) -> str:
    cust = invoice.customer
    total = invoice.amount_due_eur + fee
    fee_line = f"Zzgl. Mahngebühr: {fee:.2f} EUR\n" if fee > 0 else ""
    return (
        f"Sehr geehrte Damen und Herren der {cust.name},\n\n"
        f"{_INTRO[key]}\n\n"
        f"Rechnungsnummer: {invoice.customer_invoice_number}\n"
        f"Rechnungsdatum: {invoice.invoice_date:%d.%m.%Y}\n"
        f"Fällig seit: {invoice.due_date:%d.%m.%Y} ({days} Tage überfällig)\n"
        f"Offener Betrag: {invoice.amount_due_eur:.2f} EUR\n"
        f"{fee_line}"
        f"Zu zahlender Gesamtbetrag: {total:.2f} EUR\n\n"
        f"Bitte überweisen Sie den Betrag innerhalb von 10 Tagen auf unser Konto "
        f"DE12 5001 0517 0648 4898 90 (Verwendungszweck: "
        f"{invoice.customer_invoice_number}).\n\n"
        f"Mit freundlichen Grüßen\n"
        f"Brunnstein Beverages GmbH - Debitorenbuchhaltung"
    )


def _html(invoice: CustomerInvoice, label: str, body: str) -> str:
    safe = body.replace("\n", "<br>\n")
    return (
        '<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">'
        f"<title>{label} {invoice.customer_invoice_number}</title></head>"
        '<body style="font-family:Arial,sans-serif;color:#222;max-width:640px;margin:24px">'
        f'<h2 style="color:#1f3a5f">{label}</h2>'
        f"<p>{safe}</p></body></html>"
    )


def write_dunning(
    customer_invoices: list[CustomerInvoice],
    today: date = date(2026, 1, 15),
    max_notices: int = 250,
    seed: int = 42,
    out_dir: Path = _ROOT,
) -> list[Path]:
    """Write dunning .eml/.html for the most overdue invoices. Returns all paths."""
    rng = random.Random(seed + 27)
    out_dir.mkdir(parents=True, exist_ok=True)

    overdue = [
        inv
        for inv in customer_invoices
        if inv.status == CustomerInvoiceStatus.overdue and inv.due_date < today
    ]
    overdue.sort(key=lambda inv: inv.due_date)  # most overdue first
    selected = overdue[:max_notices]
    if len(overdue) > max_notices:
        print(f"  dunning: {len(overdue)} overdue invoices, capped to {max_notices}")

    written: list[Path] = []
    for inv in selected:
        days = (today - inv.due_date).days
        key, label, fee = _level_for(days)
        body = _body_text(inv, label, key, fee, days)
        stem = f"{inv.customer_invoice_number}_{key}"
        cust_slug = _slug(inv.customer.name)

        msg = EmailMessage()
        msg["From"] = "debitoren@brunnstein.de"
        msg["To"] = f"buchhaltung@{cust_slug}.example"
        msg["Subject"] = f"{label} zu Rechnung {inv.customer_invoice_number}"
        sent = datetime(
            today.year,
            today.month,
            min(today.day, 28),
            rng.randint(8, 17),
            rng.randint(0, 59),
            tzinfo=UTC,
        )
        msg["Date"] = format_datetime(sent)
        msg["X-Dunning-Level"] = key
        msg.set_content(body)

        eml_path = out_dir / f"{stem}.eml"
        eml_path.write_bytes(bytes(msg))
        html_path = out_dir / f"{stem}.html"
        html_path.write_text(_html(inv, label, body), encoding="utf-8")
        written.extend([eml_path, html_path])

    return written
