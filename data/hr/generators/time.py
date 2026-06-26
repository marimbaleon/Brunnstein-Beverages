"""Absences: vacation, sickness, training and parental leave per employee.

Generated per calendar year an employee is active, within the data window. The
clean HR record produced here is the counterpart to the deliberately dirty raw
clock-in/out punches written to the bronze layer (``hr_time_tracking``): the
reconciliation between the two is its own data-quality use case.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from data.hr.models import Absence, AbsenceType, Employee

# Per active year: vacation is split into a few blocks; sickness is sporadic.
_VACATION_DAYS_PER_YEAR = (24, 30)
_VACATION_BLOCKS = (2, 4)
_SICK_SPELLS_PER_YEAR = (0, 4)
_TRAINING_PROB = 0.35


def _active_in(employee: Employee, year: int, today: date) -> tuple[date, date] | None:
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    if employee.hire_date > end:
        return None
    if employee.termination_date and employee.termination_date < start:
        return None
    lo = max(start, employee.hire_date)
    hi = min(end, today, employee.termination_date or end)
    return (lo, hi) if lo < hi else None


def _working_days(start: date, end: date) -> Decimal:
    days = sum(
        1 for i in range((end - start).days + 1) if (start + timedelta(days=i)).weekday() < 5
    )
    return Decimal(days)


def _block(
    employee: Employee,
    atype: AbsenceType,
    window: tuple[date, date],
    length: int,
    rng: random.Random,
) -> Absence:
    lo, hi = window
    span = max((hi - lo).days - length, 1)
    start = lo + timedelta(days=rng.randint(0, span))
    end = start + timedelta(days=length - 1)
    return Absence(
        id=uuid4(),
        employee_id=employee.id,
        type=atype,
        start_date=start,
        end_date=end,
        working_days=_working_days(start, end),
    )


def generate_absences(
    employees: list[Employee],
    year_range: tuple[int, int] = (2023, 2025),
    today: date = date(2026, 1, 15),
    seed: int = 42,
) -> list[Absence]:
    rng = random.Random(seed + 13)
    absences: list[Absence] = []

    for employee in employees:
        for year in range(year_range[0], year_range[1] + 1):
            window = _active_in(employee, year, today)
            if window is None:
                continue

            # Vacation: total budget split into a handful of blocks.
            total_vac = rng.randint(*_VACATION_DAYS_PER_YEAR)
            n_blocks = rng.randint(*_VACATION_BLOCKS)
            for _ in range(n_blocks):
                length = max(total_vac // n_blocks, 1)
                absences.append(_block(employee, AbsenceType.vacation, window, length, rng))

            # Sickness: short, sporadic spells.
            for _ in range(rng.randint(*_SICK_SPELLS_PER_YEAR)):
                absences.append(_block(employee, AbsenceType.sick, window, rng.randint(1, 5), rng))

            # Occasional training.
            if rng.random() < _TRAINING_PROB:
                absences.append(
                    _block(employee, AbsenceType.training, window, rng.randint(1, 3), rng)
                )

    return absences
