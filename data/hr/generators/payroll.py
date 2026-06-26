"""Monthly payroll: one run per period, one item per active employee.

Gross pay comes from the employment record valid in that month. German payroll
deductions are approximated: a flat social-security employee share plus a
progressive income-tax (Lohnsteuer) rate by gross band. Net is what is left.
The numbers are realistic in shape rather than tax-code exact.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from data.hr.models import Employee, PayrollItem, PayrollRun

_CENT = Decimal("0.01")
_SOCIAL_SECURITY_RATE = Decimal("0.20")  # employee share, all branches combined

# Progressive monthly income-tax rate by gross band (lower bound -> rate).
_TAX_BANDS: list[tuple[Decimal, Decimal]] = [
    (Decimal("0"), Decimal("0.08")),
    (Decimal("2000"), Decimal("0.14")),
    (Decimal("3500"), Decimal("0.20")),
    (Decimal("5000"), Decimal("0.28")),
    (Decimal("8000"), Decimal("0.35")),
]


def _tax_rate(gross: Decimal) -> Decimal:
    rate = _TAX_BANDS[0][1]
    for threshold, r in _TAX_BANDS:
        if gross >= threshold:
            rate = r
    return rate


def _months(year_range: tuple[int, int], today: date) -> list[tuple[int, int]]:
    months: list[tuple[int, int]] = []
    for year in range(year_range[0], year_range[1] + 1):
        for month in range(1, 13):
            if date(year, month, 1) <= today:
                months.append((year, month))
    return months


def _salary_for(employee: Employee, period_end: date, period_start: date) -> Decimal | None:
    for emp in employee.employments:
        valid_to = emp.valid_to or date.max
        if emp.valid_from <= period_end and valid_to >= period_start:
            return emp.monthly_salary_eur
    return None


def generate_payroll(
    employees: list[Employee],
    year_range: tuple[int, int] = (2023, 2025),
    today: date = date(2026, 1, 15),
    seed: int = 42,
) -> list[PayrollRun]:
    """Build one PayrollRun per period, each with an item per active employee."""
    runs: list[PayrollRun] = []

    for year, month in _months(year_range, today):
        period_start = date(year, month, 1)
        next_month = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        period_end = next_month - timedelta(days=1)
        pay_date = period_end

        run = PayrollRun(
            id=uuid4(),
            period=f"{year}-{month:02d}",
            pay_date=pay_date,
        )

        for employee in employees:
            if employee.hire_date > period_end:
                continue
            if employee.termination_date and employee.termination_date < period_start:
                continue
            gross = _salary_for(employee, period_end, period_start)
            if gross is None:
                continue
            tax = (gross * _tax_rate(gross)).quantize(_CENT)
            sv = (gross * _SOCIAL_SECURITY_RATE).quantize(_CENT)
            net = (gross - tax - sv).quantize(_CENT)
            run.items.append(
                PayrollItem(
                    id=uuid4(),
                    payroll_run_id=run.id,
                    employee_id=employee.id,
                    gross_eur=gross,
                    income_tax_eur=tax,
                    social_security_eur=sv,
                    net_eur=net,
                )
            )
        runs.append(run)

    return runs
