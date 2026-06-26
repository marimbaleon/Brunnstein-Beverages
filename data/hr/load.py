"""Generate the HR data and load it into the database.

``generate_hr`` builds the whole HR object graph from the ERP plants and lines
(it does not own master data, it hangs off it). ``load_hr`` inserts that graph
into an open session. The standalone ``main`` is for iterating on HR alone: it
builds its own plants and lines so the resulting database is self-consistent,
but the canonical full load is ``data.data_generator`` which shares one set of
plants across ERP and HR.

Run HR-only as a script:
    uv run python -m data.hr.load
"""

from __future__ import annotations

from datetime import date
from typing import Any

from dotenv import load_dotenv
from sqlalchemy.orm import Session

from data.erp.generators.plants import generate_plants
from data.erp.load_to_dsql import get_engine, load_table, strip_foreign_keys
from data.erp.models import Base, Plant, ProductionLine
from data.hr.generators.employees import generate_employees
from data.hr.generators.org import generate_org
from data.hr.generators.payroll import generate_payroll
from data.hr.generators.time import generate_absences

load_dotenv()


def generate_hr(
    plants: list[Plant],
    lines: list[ProductionLine],
    year_range: tuple[int, int] = (2023, 2025),
    today: date = date(2026, 1, 15),
    seed: int = 42,
) -> dict[str, list]:
    """Build the HR object graph hanging off the given plants and lines."""
    lines_per_plant: dict = {}
    for line in lines:
        lines_per_plant.setdefault(line.plant_id, []).append(line)

    org_units, positions, staffing = generate_org(plants, lines_per_plant)
    employees = generate_employees(staffing, plants, today=today, seed=seed)
    absences = generate_absences(employees, year_range=year_range, today=today, seed=seed)
    payroll_runs = generate_payroll(employees, year_range=year_range, today=today, seed=seed)

    return {
        "org_units": org_units,
        "positions": positions,
        "employees": employees,
        "absences": absences,
        "payroll_runs": payroll_runs,
    }


def load_hr(session: Session, hr: dict[str, list]) -> None:
    """Insert the HR graph. Employees cascade to their employment records."""
    load_table(session, hr["org_units"])
    load_table(session, hr["positions"])
    load_table(session, hr["employees"])  # cascades to employment
    load_table(session, hr["absences"])
    load_table(session, hr["payroll_runs"])  # cascades to payroll_item


def main(
    seed: int = 42,
    year_range: tuple[int, int] = (2023, 2025),
    reset: bool = True,
) -> dict[str, Any]:
    engine = get_engine()
    strip_foreign_keys(Base.metadata)

    plants, lines = generate_plants()
    hr = generate_hr(plants, lines, year_range=year_range, seed=seed)

    if reset:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    n_employments = sum(len(e.employments) for e in hr["employees"])
    n_payroll_items = sum(len(r.items) for r in hr["payroll_runs"])

    with Session(engine) as session:
        load_table(session, plants)
        load_table(session, lines)
        load_hr(session, hr)
        session.commit()

    return {
        "url": str(engine.url),
        "org_units": len(hr["org_units"]),
        "positions": len(hr["positions"]),
        "employees": len(hr["employees"]),
        "employments": n_employments,
        "absences": len(hr["absences"]),
        "payroll_runs": len(hr["payroll_runs"]),
        "payroll_items": n_payroll_items,
    }


if __name__ == "__main__":
    counts = main()
    print("loaded into", counts.pop("url"))
    for k, v in counts.items():
        print(f"  {k}: {v}")
