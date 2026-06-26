"""Synthetic plant and production line master data for Brunnstein.

Two southern-German sites, three filling lines each: glass, PET, and a
shared can/keg line. The lines are the anchor for later production runs and
IoT telemetry, so their rated speed and commissioning date are set here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import uuid4

from data.erp.models import Plant, ProductionLine, ProductionLineType


@dataclass(frozen=True)
class _LineSpec:
    suffix: str
    name: str
    line_type: ProductionLineType
    nominal_speed_bph: int
    commissioned: date


@dataclass(frozen=True)
class _PlantSpec:
    plant_code: str
    name: str
    street: str
    postal_code: str
    city: str
    lines: list[_LineSpec]


_PLANTS: list[_PlantSpec] = [
    _PlantSpec(
        plant_code="1000",
        name="Werk Brunnstein-Süd",
        street="Quellenstraße 1",
        postal_code="83646",
        city="Bad Tölz",
        lines=[
            _LineSpec(
                "GL1", "Glaslinie 1 (Mehrweg)", ProductionLineType.glass, 36000, date(2014, 5, 1)
            ),
            _LineSpec("PE1", "PET-Linie 1", ProductionLineType.pet, 48000, date(2018, 3, 1)),
            _LineSpec(
                "KEG", "Fass- und Dosenlinie", ProductionLineType.keg, 9000, date(2016, 9, 1)
            ),
        ],
    ),
    _PlantSpec(
        plant_code="2000",
        name="Werk Donautal",
        street="Industriepark 14",
        postal_code="89079",
        city="Ulm",
        lines=[
            _LineSpec(
                "GL2", "Glaslinie 2 (Mehrweg)", ProductionLineType.glass, 30000, date(2012, 7, 1)
            ),
            _LineSpec("PE2", "PET-Linie 2", ProductionLineType.pet, 54000, date(2021, 4, 1)),
            _LineSpec("CAN", "Dosenlinie", ProductionLineType.can, 60000, date(2020, 6, 1)),
        ],
    ),
]


def generate_plants() -> tuple[list[Plant], list[ProductionLine]]:
    """Build the two plants and their production lines (deterministic, no RNG)."""
    plants: list[Plant] = []
    lines: list[ProductionLine] = []
    for spec in _PLANTS:
        plant = Plant(
            id=uuid4(),
            plant_code=spec.plant_code,
            name=spec.name,
            street=spec.street,
            postal_code=spec.postal_code,
            city=spec.city,
        )
        plants.append(plant)
        for ls in spec.lines:
            lines.append(
                ProductionLine(
                    id=uuid4(),
                    line_code=f"{spec.plant_code}-{ls.suffix}",
                    plant_id=plant.id,
                    name=ls.name,
                    line_type=ls.line_type,
                    nominal_speed_bph=ls.nominal_speed_bph,
                    commissioned_date=ls.commissioned,
                )
            )
    return plants, lines
