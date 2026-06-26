"""Pydantic types shared by extraction, validation, and the eval suite."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from use_cases.automated_invoice_processing.agent.signals import Decision, Signal


class ExtractedLine(BaseModel):
    line_number: int
    description: str
    quantity: Decimal
    unit_price_net_eur: Decimal
    line_net_eur: Decimal


class ExtractedInvoice(BaseModel):
    supplier_name: str
    supplier_vat_id: str | None = None
    invoice_number: str
    invoice_date: date | None = None
    due_date: date | None = None
    po_number: str | None = None
    payment_iban: str | None = None
    lines: list[ExtractedLine]
    total_net_eur: Decimal
    total_vat_eur: Decimal
    total_gross_eur: Decimal


class AgentVerdict(BaseModel):
    """Final output of the agent for one invoice."""

    decision: Decision
    signals: list[Signal] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    extracted: ExtractedInvoice | None = None
