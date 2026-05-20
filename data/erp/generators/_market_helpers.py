"""Shared helpers for the transactional generators: which suppliers sell what,
and how prices land.

Kept private (leading underscore) so only the per-entity generators import this.
"""

from __future__ import annotations

import random
import re
from decimal import Decimal

from data.erp.models import RawMaterial, RawMaterialCategory, Supplier

# Specialization tag inferred from supplier name. Maps to a regex over material names.
# `logistics` suppliers don't sell physical materials and are excluded from PO generation.
_SUPPLIER_SPEC: list[tuple[str, str]] = [
    ("glass", r"Glaswerke|Flaschenmanufaktur|Hohlglas|Glashütte|Glasmanufaktur"),
    ("pet", r"PET-Werk|PolyBottle|Kunststoff Süd"),
    ("caps", r"Verschluss|Kronkorken|Schraubverschluss|CapTech"),
    ("labels", r"Etikett|Label|Folien und Drucke"),
    ("crates", r"Kistenfabrik|Kunststoffkisten|Holzkisten|Mehrweg Verpackung"),
    ("co2", r"Kohlensäure|CO2"),
    ("water", r"Alpenquellen|Mineralextrakte|Quellrechte"),
    ("aroma", r"Aromen|Aromatica|BioAroma|Syrup"),
    ("fruit", r"Beerenmanufaktur|Apfelhof|Saftpressen|Schwarzwaldfrucht"),
    ("sweeteners", r"Zuckerwerke|Naturzucker"),
    ("hops", r"Hopfen"),
    ("cleaning", r"ChemTec|Hygienechemie|Brauereihygiene"),
    ("lubricants", r"Schmierstoffe|TecLub"),
    ("lab", r"Laborbedarf|AnalytikSüd"),
    ("logistics", r"Spedition|Frachtdienste|Süddeutsche Logistik"),
]

_MATERIAL_SPEC: dict[str, str] = {
    "glass": r"Glasflasche",
    "pet": r"PET-Flasche",
    "caps": r"Kronkorken|Verschluss",
    "labels": r"Etikett",
    "crates": r"Kunststoffkasten|palette|Stretchfolie|Schrumpffolie",
    "co2": r"^CO2",
    "water": r"Quellwasser|Mineralextrakt",
    "aroma": r"Sirupkonzentrat|Citrusaroma|Vanillearoma|Minzöl|Kräuterextrakt|Bitterstoff",
    "fruit": r"Fruchtmark",
    "sweeteners": r"Zucker Saccharose|Fructose|Stevia|Glucose",
    "hops": r"Hopfen",
    "cleaning": r"CIP|Desinfektionsmittel|Glasreiniger|Edelstahlpflege|Schaumreiniger",
    "lubricants": r"Lebensmittelschmierstoff|Kettenöl|Pumpenfett|Gleitmittel",
    "lab": r"Titrationslösung|pH-Pufferlösung|Calciumstandard|Mikrobiologie|Indikatorpapier",
}

# Acids / preservatives: sold by chemicals or aroma suppliers, attach broadly
_FALLBACK_AROMA_EXTRAS = r"Zitronensäure|Ascorbinsäure|Kaliumsorbat"


def supplier_spec(supplier: Supplier) -> str | None:
    for tag, pattern in _SUPPLIER_SPEC:
        if re.search(pattern, supplier.name):
            return tag
    return None


def materials_for_supplier(supplier: Supplier, materials: list[RawMaterial]) -> list[RawMaterial]:
    tag = supplier_spec(supplier)
    if tag is None or tag == "logistics":
        return []
    pattern = _MATERIAL_SPEC.get(tag)
    if not pattern:
        return []
    matched = [m for m in materials if re.search(pattern, m.name)]
    if tag == "aroma":
        matched += [m for m in materials if re.search(_FALLBACK_AROMA_EXTRAS, m.name)]
    return matched


# Unit price ranges in EUR per UOM unit, by material category.
_PRICE_RANGES: dict[RawMaterialCategory, tuple[Decimal, Decimal]] = {
    RawMaterialCategory.packaging: (Decimal("0.05"), Decimal("0.80")),
    RawMaterialCategory.ingredient: (Decimal("1.20"), Decimal("12.00")),
    RawMaterialCategory.auxiliary: (Decimal("3.00"), Decimal("25.00")),
}


def pick_unit_price(material: RawMaterial, rng: random.Random) -> Decimal:
    lo, hi = _PRICE_RANGES[material.category]
    span_4dp = int((hi - lo) * 10000)
    offset = rng.randint(0, span_4dp)
    return (lo + Decimal(offset) / Decimal(10000)).quantize(Decimal("0.0001"))


def pick_quantity(material: RawMaterial, rng: random.Random) -> Decimal:
    cat = material.category
    uom = material.unit_of_measure
    if cat == RawMaterialCategory.packaging:
        return Decimal(rng.choice([1000, 2500, 5000, 10000, 20000, 50000]))
    if cat == RawMaterialCategory.ingredient:
        return Decimal(rng.choice([50, 100, 200, 500, 1000, 2000]))
    if cat == RawMaterialCategory.auxiliary:
        if uom == "Stk":
            return Decimal(rng.choice([5, 10, 25, 50, 100]))
        return Decimal(rng.choice([10, 25, 50, 100, 200]))
    return Decimal(50)
