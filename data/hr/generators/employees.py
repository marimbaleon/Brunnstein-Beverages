"""Fill the staffing plan with people, contracts and salaries.

For every (position, headcount) the org generator produced, this creates that
many employees with a hire date spread across the company's history, a small
share of leavers (fluctuation), and one open employment record carrying the
contract type, weekly hours and monthly gross salary. Salary follows the
position's job level; part-time contracts are paid pro rata.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from faker import Faker

from data.erp.models import Plant
from data.hr.models import (
    ContractType,
    Employee,
    Employment,
    EmploymentType,
    Gender,
    Position,
)

# Monthly gross salary band (EUR) by job level.
_SALARY_BAND: dict[int, tuple[int, int]] = {
    1: (2400, 3000),
    2: (2900, 3800),
    3: (3600, 5200),
    4: (5200, 7500),
    5: (8000, 12000),
    6: (18000, 25000),
}

_FULL_TIME_HOURS = Decimal("40.00")
_PART_TIME_RATE = 0.16  # share of staff on part-time
_LEAVER_RATE = 0.12  # share whose contract has already ended
_FIXED_TERM_RATE = 0.10

# Company history window for hire dates.
_FIRST_HIRE = date(2011, 1, 1)


def _gender(rng: random.Random) -> Gender:
    if rng.random() < 0.015:
        return Gender.diverse
    return Gender.male if rng.random() < 0.58 else Gender.female


def _birth_date(rng: random.Random, hire: date) -> date:
    # Aged 19..58 at hire.
    age_at_hire = rng.randint(19, 58)
    return date(hire.year - age_at_hire, rng.randint(1, 12), rng.randint(1, 28))


def _email(first: str, last: str, used: set[str]) -> str:
    def norm(s: str) -> str:
        table = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})
        return s.lower().translate(table).replace(" ", "").replace("-", "")

    base = f"{norm(first)}.{norm(last)}"
    candidate = f"{base}@brunnstein.de"
    n = 2
    while candidate in used:
        candidate = f"{base}{n}@brunnstein.de"
        n += 1
    used.add(candidate)
    return candidate


def generate_employees(
    staffing: list[tuple[Position, int]],
    plants: list[Plant],
    today: date = date(2026, 1, 15),
    seed: int = 42,
) -> list[Employee]:
    """Create employees and their open employment records from the staffing plan."""
    faker = Faker("de_DE")
    Faker.seed(seed)
    rng = random.Random(seed + 11)

    hq_plant = plants[0]
    plant_by_id = {p.id: p for p in plants}
    used_emails: set[str] = set()

    employees: list[Employee] = []
    emp_seq = 1

    for position, headcount in staffing:
        unit = position.org_unit
        plant = plant_by_id.get(unit.plant_id, hq_plant)
        lo, hi = _SALARY_BAND[position.job_level]

        for _ in range(headcount):
            gender = _gender(rng)
            if gender == Gender.male:
                first = faker.first_name_male()
            elif gender == Gender.female:
                first = faker.first_name_female()
            else:
                first = faker.first_name()
            last = faker.last_name()

            # Hire spread: more recent years carry more hires (the company grew).
            span = (today - _FIRST_HIRE).days
            hire = _FIRST_HIRE + timedelta(days=int(span * rng.random() ** 0.6))
            birth = _birth_date(rng, hire)

            is_part_time = rng.random() < _PART_TIME_RATE and position.job_level <= 3
            weekly = Decimal(rng.choice([20, 25, 30])) if is_part_time else _FULL_TIME_HOURS
            ratio = weekly / _FULL_TIME_HOURS
            base = Decimal(rng.randint(lo, hi))
            salary = (base * ratio).quantize(Decimal("0.01"))

            if position.job_level <= 2 and rng.random() < 0.06:
                contract = (
                    ContractType.apprentice
                    if rng.random() < 0.5
                    else (ContractType.working_student)
                )
            elif rng.random() < _FIXED_TERM_RATE:
                contract = ContractType.fixed_term
            else:
                contract = ContractType.permanent

            # A share of contracts have already ended.
            termination = None
            if rng.random() < _LEAVER_RATE:
                min_end = hire + timedelta(days=rng.randint(180, 365 * 6))
                if min_end < today:
                    termination = min_end

            employee = Employee(
                id=uuid4(),
                personnel_number=f"E-{100000 + emp_seq}",
                first_name=first,
                last_name=last,
                gender=gender,
                birth_date=birth,
                email=_email(first, last, used_emails),
                plant_id=plant.id,
                org_unit_id=unit.id,
                position_id=position.id,
                hire_date=hire,
                termination_date=termination,
                active=termination is None,
            )
            employee.position = position
            employee.employments.append(
                Employment(
                    id=uuid4(),
                    employee_id=employee.id,
                    valid_from=hire,
                    valid_to=termination,
                    employment_type=(
                        EmploymentType.part_time if is_part_time else EmploymentType.full_time
                    ),
                    contract_type=contract,
                    weekly_hours=weekly,
                    monthly_salary_eur=salary,
                )
            )
            employees.append(employee)
            emp_seq += 1

    return employees
