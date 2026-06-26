"""Organisational structure: org units, positions and target headcount.

Builds a central HQ (management, administration, sales) plus, for every ERP
plant, the shop-floor functions (production, quality, maintenance, logistics).
Each position carries a job level (1 operator .. 6 executive) that drives the
salary band used downstream. The function returns the units, the positions and
a staffing plan (how many people each position should hold) so the employee
generator can fill them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from data.erp.models import Plant
from data.hr.models import OrgFunction, OrgUnit, Position


@dataclass(frozen=True)
class _Role:
    title: str
    level: int
    headcount: int
    is_management: bool = False


@dataclass(frozen=True)
class _Unit:
    key: str
    name: str
    function: OrgFunction
    roles: list[_Role] = field(default_factory=list)


# Central (company-wide) units, not tied to a plant.
_CENTRAL: list[_Unit] = [
    _Unit(
        "MGT",
        "Geschäftsführung",
        OrgFunction.management,
        [
            _Role("Geschäftsführer", 6, 1, is_management=True),
            _Role("Bereichsleiter", 5, 3, is_management=True),
            _Role("Assistenz der Geschäftsführung", 2, 1),
        ],
    ),
    _Unit(
        "FIN",
        "Finanzen & Controlling",
        OrgFunction.administration,
        [
            _Role("Leiter Finanzen", 4, 1, is_management=True),
            _Role("Controller", 3, 3),
            _Role("Buchhalter", 2, 4),
        ],
    ),
    _Unit(
        "HR",
        "Personal",
        OrgFunction.administration,
        [
            _Role("Leiter Personal", 4, 1, is_management=True),
            _Role("HR Business Partner", 3, 2),
            _Role("Personalsachbearbeiter", 2, 3),
        ],
    ),
    _Unit(
        "IT",
        "IT & Digitalisierung",
        OrgFunction.administration,
        [
            _Role("Leiter IT", 4, 1, is_management=True),
            _Role("Systemadministrator", 3, 3),
            _Role("IT-Support", 2, 2),
        ],
    ),
    _Unit(
        "PUR",
        "Einkauf",
        OrgFunction.administration,
        [
            _Role("Leiter Einkauf", 4, 1, is_management=True),
            _Role("Strategischer Einkäufer", 3, 3),
            _Role("Operativer Einkäufer", 2, 3),
        ],
    ),
    _Unit(
        "MKT",
        "Marketing",
        OrgFunction.administration,
        [
            _Role("Leiter Marketing", 4, 1, is_management=True),
            _Role("Marketing Manager", 3, 2),
            _Role("Marketing Specialist", 2, 2),
        ],
    ),
    _Unit(
        "SLS",
        "Vertrieb",
        OrgFunction.sales,
        [
            _Role("Vertriebsleiter", 4, 1, is_management=True),
            _Role("Key Account Manager", 3, 6),
            _Role("Außendienstmitarbeiter", 3, 12),
            _Role("Vertriebsinnendienst", 2, 8),
        ],
    ),
]

# Per-plant units. Production roles scale with the number of filling lines.
_PLANT_UNITS: list[_Unit] = [
    _Unit(
        "PROD",
        "Produktion",
        OrgFunction.production,
        [
            _Role("Werkleiter", 5, 1, is_management=True),
            _Role("Schichtleiter", 4, 3, is_management=True),
            _Role("Maschinenführer", 2, 0),  # headcount filled from line count
            _Role("Produktionshelfer", 1, 0),
        ],
    ),
    _Unit(
        "QM",
        "Qualitätssicherung",
        OrgFunction.quality,
        [
            _Role("Leiter Qualitätssicherung", 4, 1, is_management=True),
            _Role("QS-Techniker", 3, 3),
            _Role("Laborant", 2, 3),
        ],
    ),
    _Unit(
        "MNT",
        "Instandhaltung",
        OrgFunction.maintenance,
        [
            _Role("Leiter Instandhaltung", 4, 1, is_management=True),
            _Role("Mechatroniker", 3, 5),
            _Role("Elektriker", 3, 2),
        ],
    ),
    _Unit(
        "LOG",
        "Logistik & Lager",
        OrgFunction.logistics,
        [
            _Role("Lagerleiter", 4, 1, is_management=True),
            _Role("Staplerfahrer", 1, 6),
            _Role("Versandmitarbeiter", 2, 3),
        ],
    ),
]


def _make_unit(unit: _Unit, code: str, plant_id, parent: OrgUnit | None) -> OrgUnit:
    return OrgUnit(
        id=uuid4(),
        org_code=code,
        name=unit.name,
        function=unit.function,
        parent_id=parent.id if parent else None,
        plant_id=plant_id,
    )


def generate_org(
    plants: list[Plant],
    lines_per_plant: dict,
) -> tuple[list[OrgUnit], list[Position], list[tuple[Position, int]]]:
    """Build org units and positions. Returns (units, positions, staffing plan)."""
    units: list[OrgUnit] = []
    positions: list[Position] = []
    staffing: list[tuple[Position, int]] = []
    pos_seq = 1

    root = None

    def add_unit(spec: _Unit, code: str, plant_id, parent, line_count: int) -> None:
        nonlocal pos_seq
        unit = _make_unit(spec, code, plant_id, parent)
        units.append(unit)
        for role in spec.roles:
            headcount = role.headcount
            if role.title == "Maschinenführer":
                headcount = line_count * 3 * 2  # 3 shifts, ~2 operators per line
            elif role.title == "Produktionshelfer":
                headcount = line_count * 3
            if headcount <= 0:
                continue
            position = Position(
                id=uuid4(),
                position_code=f"POS-{pos_seq:05d}",
                title=role.title,
                org_unit_id=unit.id,
                job_level=role.level,
                is_management=role.is_management,
            )
            position.org_unit = unit
            positions.append(position)
            staffing.append((position, headcount))
            pos_seq += 1

    # Central units hang under the management unit.
    for spec in _CENTRAL:
        code = f"ORG-{spec.key}"
        add_unit(spec, code, None, root, 0)
        if spec.key == "MGT":
            root = units[-1]

    # Plant units hang under their plant's production unit's plant scope.
    for plant in plants:
        line_count = len(lines_per_plant.get(plant.id, []))
        for spec in _PLANT_UNITS:
            code = f"ORG-{spec.key}-{plant.plant_code}"
            add_unit(spec, code, plant.id, root, line_count)

    return units, positions, staffing
