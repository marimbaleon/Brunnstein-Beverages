"""SQLAlchemy models for Brunnstein's HR (human-capital) source system.

A separate logical system from the ERP, but modelled on the same SQLAlchemy
``Base`` so it lands in one database for the demo. The shape follows SAP HCM
object types: organisational unit (O), position (S) and person (P), plus the
contract, absence and payroll records that hang off an employee. Names are kept
readable rather than mirroring SAP infotype numbers.

Employees reference an ERP ``plant``; that cross-system link is intentional and
is enforced in application code (the database does not enforce foreign keys).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import Date, ForeignKey, Numeric, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from data.erp.models import Base, TimestampMixin, _enum


class OrgFunction(StrEnum):
    production = "production"
    quality = "quality"
    maintenance = "maintenance"
    logistics = "logistics"
    sales = "sales"
    administration = "administration"
    management = "management"


class EmploymentType(StrEnum):
    full_time = "full_time"
    part_time = "part_time"


class ContractType(StrEnum):
    permanent = "permanent"
    fixed_term = "fixed_term"
    working_student = "working_student"
    apprentice = "apprentice"


class AbsenceType(StrEnum):
    vacation = "vacation"
    sick = "sick"
    training = "training"
    parental = "parental"


class Gender(StrEnum):
    female = "female"
    male = "male"
    diverse = "diverse"


class OrgUnit(Base, TimestampMixin):
    """A department or team. SAP HCM object type O. Hierarchical via parent."""

    __tablename__ = "org_unit"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    org_code: Mapped[str] = mapped_column(String(20), unique=True)  # "ORG-PROD-1000"
    name: Mapped[str] = mapped_column(String(200))
    function: Mapped[OrgFunction] = mapped_column(_enum(OrgFunction))
    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey("org_unit.id"))
    # Plant the unit belongs to; NULL for central/HQ functions.
    plant_id: Mapped[UUID | None] = mapped_column(ForeignKey("plant.id"))

    parent: Mapped[OrgUnit | None] = relationship(remote_side="OrgUnit.id")


class Position(Base, TimestampMixin):
    """A staffable post. SAP HCM object type S. Tied to an org unit."""

    __tablename__ = "position"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    position_code: Mapped[str] = mapped_column(String(20), unique=True)  # "POS-000123"
    title: Mapped[str] = mapped_column(String(200))
    org_unit_id: Mapped[UUID] = mapped_column(ForeignKey("org_unit.id"))
    # 1 (operator) .. 6 (executive); drives the salary band.
    job_level: Mapped[int] = mapped_column(SmallInteger)
    is_management: Mapped[bool] = mapped_column(default=False)

    org_unit: Mapped[OrgUnit] = relationship()


class Employee(Base, TimestampMixin):
    """A person employed by Brunnstein. SAP HCM object type P (PA0002)."""

    __tablename__ = "employee"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    personnel_number: Mapped[str] = mapped_column(String(20), unique=True)  # "E-100123"
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    gender: Mapped[Gender] = mapped_column(_enum(Gender))
    birth_date: Mapped[date] = mapped_column(Date)
    email: Mapped[str] = mapped_column(String(200))

    plant_id: Mapped[UUID] = mapped_column(ForeignKey("plant.id"))
    org_unit_id: Mapped[UUID] = mapped_column(ForeignKey("org_unit.id"))
    position_id: Mapped[UUID] = mapped_column(ForeignKey("position.id"))

    hire_date: Mapped[date] = mapped_column(Date)
    termination_date: Mapped[date | None] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(default=True)

    position: Mapped[Position] = relationship()
    employments: Mapped[list[Employment]] = relationship(
        back_populates="employee",
        cascade="all, delete-orphan",
    )


class Employment(Base, TimestampMixin):
    """A contract period for an employee. SAP HCM: org assignment (PA0001/0008).

    One employee can have several (a promotion, a switch full- to part-time).
    Exactly one is open (``valid_to`` NULL) while the person is active.
    """

    __tablename__ = "employment"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    employee_id: Mapped[UUID] = mapped_column(ForeignKey("employee.id"))
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    employment_type: Mapped[EmploymentType] = mapped_column(_enum(EmploymentType))
    contract_type: Mapped[ContractType] = mapped_column(_enum(ContractType))
    weekly_hours: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    monthly_salary_eur: Mapped[Decimal] = mapped_column(Numeric(10, 2))  # gross, full period

    employee: Mapped[Employee] = relationship(back_populates="employments")


class Absence(Base, TimestampMixin):
    """A recorded absence. SAP HCM time management (PA2001)."""

    __tablename__ = "absence"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    employee_id: Mapped[UUID] = mapped_column(ForeignKey("employee.id"))
    type: Mapped[AbsenceType] = mapped_column(_enum(AbsenceType))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    working_days: Mapped[Decimal] = mapped_column(Numeric(5, 2))

    employee: Mapped[Employee] = relationship()


class PayrollRun(Base, TimestampMixin):
    """A monthly payroll cycle for the whole company. SAP HCM: PY period."""

    __tablename__ = "payroll_run"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    period: Mapped[str] = mapped_column(String(7), unique=True)  # "2024-06"
    pay_date: Mapped[date] = mapped_column(Date)

    items: Mapped[list[PayrollItem]] = relationship(
        back_populates="payroll_run",
        cascade="all, delete-orphan",
    )


class PayrollItem(Base):
    """One employee's pay for one period. SAP HCM: payroll result (RT)."""

    __tablename__ = "payroll_item"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    payroll_run_id: Mapped[UUID] = mapped_column(ForeignKey("payroll_run.id"))
    employee_id: Mapped[UUID] = mapped_column(ForeignKey("employee.id"))
    gross_eur: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    income_tax_eur: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    social_security_eur: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    net_eur: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    payroll_run: Mapped[PayrollRun] = relationship(back_populates="items")
    employee: Mapped[Employee] = relationship()
