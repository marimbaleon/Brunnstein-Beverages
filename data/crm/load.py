"""Generate the CRM data and load it into the database.

``generate_crm`` builds leads, opportunities and activities from the existing
B2B customers and the HR sales reps (it does not own that master data). The
standalone ``main`` regenerates the customers and HR it needs so an HR+CRM
database is self-consistent; the canonical full load is ``data.data_generator``.

Run CRM-only as a script:
    uv run python -m data.crm.load
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from data.crm.generators.pipeline import (
    generate_activities,
    generate_leads,
    generate_opportunities,
)
from data.erp.generators.customers import generate_customers
from data.erp.generators.plants import generate_plants
from data.erp.load_to_dsql import get_engine, load_table, strip_foreign_keys
from data.erp.models import Base, Customer
from data.hr.load import generate_hr, load_hr
from data.hr.models import OrgFunction


def _sales_employees(employees: list) -> list:
    sales = [
        e
        for e in employees
        if e.active
        and e.position is not None
        and e.position.org_unit is not None
        and e.position.org_unit.function == OrgFunction.sales
    ]
    return sales or [e for e in employees if e.active]


def generate_crm(
    customers: list[Customer],
    employees: list,
    year_range: tuple[int, int] = (2023, 2025),
    today: date = date(2026, 1, 15),
    n_leads: int = 400,
    seed: int = 42,
) -> dict[str, list]:
    """Build the CRM object graph from customers and HR sales reps."""
    sales = _sales_employees(employees)
    leads = generate_leads(sales, year_range, today, n_leads, seed)
    opportunities = generate_opportunities(leads, customers, sales, today, seed)
    activities = generate_activities(opportunities, leads, sales, today, seed)
    return {"leads": leads, "opportunities": opportunities, "activities": activities}


def load_crm(session: Session, crm: dict[str, list]) -> None:
    """Insert the CRM graph. Opportunities cascade to their activities."""
    load_table(session, crm["leads"])
    load_table(session, crm["opportunities"])
    load_table(session, crm["activities"])


def main(
    seed: int = 42,
    year_range: tuple[int, int] = (2023, 2025),
    reset: bool = True,
) -> dict[str, Any]:
    engine = get_engine()
    strip_foreign_keys(Base.metadata)

    plants, lines = generate_plants()
    customers = generate_customers(seed=seed)
    hr = generate_hr(plants, lines, year_range=year_range, seed=seed)
    crm = generate_crm(customers, hr["employees"], year_range=year_range, seed=seed)

    if reset:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        load_table(session, plants)
        load_table(session, lines)
        load_table(session, customers)
        load_hr(session, hr)
        load_crm(session, crm)
        session.commit()

    return {
        "url": str(engine.url),
        "leads": len(crm["leads"]),
        "opportunities": len(crm["opportunities"]),
        "activities": len(crm["activities"]),
    }


if __name__ == "__main__":
    counts = main()
    print("loaded into", counts.pop("url"))
    for k, v in counts.items():
        print(f"  {k}: {v}")
