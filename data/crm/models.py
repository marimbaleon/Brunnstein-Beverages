"""SQLAlchemy models for Brunnstein's CRM source system.

A sales-pipeline system distinct from the ERP: leads, opportunities and the
activities (calls, visits, e-mails) sales reps log against them. Opportunities
either chase a brand-new lead or expand an existing B2B ``customer``; both link
to the owning sales employee in HR. Modelled on the shared ``Base`` so it lands
in the one demo database; cross-system links are enforced in application code.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import Date, ForeignKey, Numeric, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from data.erp.models import Base, TimestampMixin, _enum


class LeadSource(StrEnum):
    web_form = "web_form"
    trade_fair = "trade_fair"
    referral = "referral"
    cold_call = "cold_call"
    inbound_call = "inbound_call"


class LeadStatus(StrEnum):
    new = "new"
    qualified = "qualified"
    converted = "converted"
    lost = "lost"


class OpportunityStage(StrEnum):
    prospecting = "prospecting"
    qualification = "qualification"
    proposal = "proposal"
    negotiation = "negotiation"
    won = "won"
    lost = "lost"


class ActivityType(StrEnum):
    call = "call"
    visit = "visit"
    email = "email"
    meeting = "meeting"


class Lead(Base, TimestampMixin):
    """A potential new customer. SAP CRM / C4C: lead."""

    __tablename__ = "lead"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    lead_number: Mapped[str] = mapped_column(String(20), unique=True)  # "LD-2024-000123"
    company_name: Mapped[str] = mapped_column(String(200))
    contact_name: Mapped[str] = mapped_column(String(150))
    email: Mapped[str] = mapped_column(String(200))
    region: Mapped[str] = mapped_column(String(50))
    channel_hint: Mapped[str] = mapped_column(String(30))  # likely customer channel
    source: Mapped[LeadSource] = mapped_column(_enum(LeadSource))
    status: Mapped[LeadStatus] = mapped_column(_enum(LeadStatus), default=LeadStatus.new)
    created_date: Mapped[date] = mapped_column(Date)
    owner_employee_id: Mapped[UUID] = mapped_column(ForeignKey("employee.id"))
    estimated_annual_volume_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))


class Opportunity(Base, TimestampMixin):
    """A sales opportunity against a lead or an existing customer. SAP CRM."""

    __tablename__ = "opportunity"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    opportunity_number: Mapped[str] = mapped_column(String(20), unique=True)  # "OP-2024-..."
    title: Mapped[str] = mapped_column(String(200))
    lead_id: Mapped[UUID | None] = mapped_column(ForeignKey("lead.id"))
    customer_id: Mapped[UUID | None] = mapped_column(ForeignKey("customer.id"))
    owner_employee_id: Mapped[UUID] = mapped_column(ForeignKey("employee.id"))
    stage: Mapped[OpportunityStage] = mapped_column(_enum(OpportunityStage))
    amount_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    probability_pct: Mapped[int] = mapped_column(SmallInteger)
    created_date: Mapped[date] = mapped_column(Date)
    expected_close_date: Mapped[date] = mapped_column(Date)
    closed_date: Mapped[date | None] = mapped_column(Date)

    activities: Mapped[list[SalesActivity]] = relationship(
        back_populates="opportunity",
        cascade="all, delete-orphan",
    )


class SalesActivity(Base, TimestampMixin):
    """A logged interaction. SAP CRM: activity (BUS2000126)."""

    __tablename__ = "sales_activity"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    activity_number: Mapped[str] = mapped_column(String(20), unique=True)  # "AC-2024-000123"
    type: Mapped[ActivityType] = mapped_column(_enum(ActivityType))
    subject: Mapped[str] = mapped_column(String(200))
    activity_date: Mapped[date] = mapped_column(Date)
    owner_employee_id: Mapped[UUID] = mapped_column(ForeignKey("employee.id"))
    customer_id: Mapped[UUID | None] = mapped_column(ForeignKey("customer.id"))
    lead_id: Mapped[UUID | None] = mapped_column(ForeignKey("lead.id"))
    opportunity_id: Mapped[UUID | None] = mapped_column(ForeignKey("opportunity.id"))
    notes: Mapped[str | None] = mapped_column(Text)

    opportunity: Mapped[Opportunity | None] = relationship(back_populates="activities")
