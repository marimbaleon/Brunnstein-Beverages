"""Bronze: raw clock-in/out punches from the shop-floor terminals as CSV.

One row per shift worker per working day, written one CSV per month. The export
is deliberately messy, the way a real terminal feed is: mixed time formats,
missing clock-outs, the odd duplicated row, swapped in/out times and blank break
fields. Office staff do not clock, so only production, logistics and
maintenance employees appear.

Reconciling these punches against the clean ``absence`` records in the HR
database (a punch on a day booked as vacation, or a missing punch on a working
day) is a data-quality use case in its own right.

Files land under ``data/export/bronze/hr_time_tracking/<year>-<month>.csv``.
"""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

from data.erp.models import Plant
from data.export import BRONZE_ROOT
from data.hr.models import Absence, Employee, OrgFunction

_BRONZE_ROOT = BRONZE_ROOT / "hr_time_tracking"

# Only these functions clock in/out at a terminal.
_SHIFT_FUNCTIONS = {OrgFunction.production, OrgFunction.logistics, OrgFunction.maintenance}

# Rotating shift start/end (worked hours before break).
_SHIFTS = [("06:00", "14:00"), ("14:00", "22:00"), ("22:00", "06:00")]

_TERMINALS = ["T-GATE-1", "T-GATE-2", "T-HALLE-A", "T-HALLE-B", "T-LAGER"]


def _shift_workers(employees: list[Employee]) -> list[Employee]:
    return [
        e
        for e in employees
        if e.position is not None
        and e.position.org_unit is not None
        and e.position.org_unit.function in _SHIFT_FUNCTIONS
    ]


def _absence_days(absences: list[Absence]) -> dict:
    by_emp: dict = {}
    for a in absences:
        days = by_emp.setdefault(a.employee_id, set())
        for i in range((a.end_date - a.start_date).days + 1):
            days.add(a.start_date + timedelta(days=i))
    return by_emp


def _fmt_time(hm: str, rng: random.Random) -> str:
    """Most punches are HH:MM; a minority carry seconds or a comma separator."""
    roll = rng.random()
    if roll < 0.12:
        return f"{hm}:{rng.randint(0, 59):02d}"
    if roll < 0.16:
        return hm.replace(":", ",")
    return hm


def write_hr_time_tracking(
    employees: list[Employee],
    absences: list[Absence],
    plants: list[Plant],
    year_range: tuple[int, int] = (2023, 2025),
    today: date = date(2026, 1, 15),
    seed: int = 42,
    out_dir: Path = _BRONZE_ROOT,
) -> list[Path]:
    """Write monthly raw time-tracking CSVs. Returns the paths."""
    rng = random.Random(seed + 17)
    out_dir.mkdir(parents=True, exist_ok=True)

    workers = _shift_workers(employees)
    plant_code = {p.id: p.plant_code for p in plants}
    absent = _absence_days(absences)
    # A stable shift per worker, with occasional rotation handled per-day.
    base_shift = {e.id: i % len(_SHIFTS) for i, e in enumerate(workers)}

    rows_by_month: dict[tuple[int, int], list[dict]] = {}

    day = date(year_range[0], 1, 1)
    end = min(date(year_range[1], 12, 31), today)
    while day <= end:
        if day.weekday() < 5:  # Mon-Fri
            for worker in workers:
                if worker.hire_date > day:
                    continue
                if worker.termination_date and worker.termination_date < day:
                    continue
                # Booked absent: usually no punch, but sometimes a stray one (error).
                if day in absent.get(worker.id, ()):
                    if rng.random() > 0.04:
                        continue

                shift = (base_shift[worker.id] + (1 if rng.random() < 0.15 else 0)) % len(_SHIFTS)
                start_hm, end_hm = _SHIFTS[shift]
                clock_in = _fmt_time(start_hm, rng)
                clock_out = _fmt_time(end_hm, rng)

                # Dirt: missing clock-out, swapped in/out, blank break.
                roll = rng.random()
                if roll < 0.03:
                    clock_out = ""
                elif roll < 0.05:
                    clock_in, clock_out = clock_out, clock_in
                break_minutes = "" if rng.random() < 0.06 else str(rng.choice([30, 30, 45, 60]))

                row = {
                    "punch_date": day.isoformat(),
                    "personnel_number": worker.personnel_number,
                    "plant_code": plant_code.get(worker.plant_id, ""),
                    "clock_in": clock_in,
                    "clock_out": clock_out,
                    "break_minutes": break_minutes,
                    "terminal": rng.choice(_TERMINALS),
                }
                rows_by_month.setdefault((day.year, day.month), []).append(row)
                # Duplicate delivery: the same punch lands twice.
                if rng.random() < 0.015:
                    rows_by_month[(day.year, day.month)].append(dict(row))
        day += timedelta(days=1)

    fields = [
        "punch_date",
        "personnel_number",
        "plant_code",
        "clock_in",
        "clock_out",
        "break_minutes",
        "terminal",
    ]
    written: list[Path] = []
    for (year, month), rows in sorted(rows_by_month.items()):
        path = out_dir / f"{year}-{month:02d}.csv"
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        written.append(path)
    return written
