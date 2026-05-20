"""German number, date, and IBAN formatting for invoice PDFs."""

from __future__ import annotations

from datetime import date
from decimal import Decimal


def format_eur(value: Decimal | None) -> str:
    """Format as German currency: 1.234,56 EUR."""
    if value is None:
        return ""
    s = f"{value:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".") + " EUR"


def format_qty(value: Decimal) -> str:
    """Format quantity with German decimal separator. Drops trailing zeros."""
    s = f"{value:.3f}".rstrip("0").rstrip(".")
    return s.replace(".", ",")


def format_iban(iban: str) -> str:
    """Group IBAN into space-separated quartets."""
    return " ".join(iban[i:i + 4] for i in range(0, len(iban), 4))


def format_date(d: date) -> str:
    """Format date as DD.MM.YYYY."""
    return d.strftime("%d.%m.%Y")
