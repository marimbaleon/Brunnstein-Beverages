"""Synthetic finished-goods catalogue and bills of materials for Brunnstein.

Twelve base beverages (the same names the raw-material labels reference) are
each offered in one or more pack variants, giving ~22 sellable SKUs. Every
SKU carries a bill of materials that resolves against the existing
``raw_material`` rows by name, so procurement and production stay consistent:
the syrups, bottles, caps, labels and crates a product consumes are the same
ones Brunnstein buys.

Quantities in the BOM are normalised per 1000 litres of finished product.
Packaging quantities follow from the pack: a 0,33 L bottle needs ~3030 bottles
(and caps and labels) per 1000 L, plus crates at one per case.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import uuid4

from data.erp.models import (
    ContainerType,
    Product,
    ProductCategory,
    ProductComponent,
    RawMaterial,
)


@dataclass(frozen=True)
class _Pack:
    container_type: ContainerType
    volume_l: str  # single-bottle volume
    units_per_case: int
    deposit_eur: str  # Pfand per unit
    bottle: str  # raw_material name
    cap: str  # raw_material name
    crate: str  # raw_material name


# Pack templates. Each names the exact raw materials it consumes so the BOM
# joins cleanly to the procurement catalogue.
_GLASS_033 = _Pack(
    ContainerType.glass_returnable,
    "0.330",
    24,
    "0.08",
    "Glasflasche 0,33 L Mehrweg",
    "Kronkorken gold",
    "Kunststoffkasten 24 x 0,33 L",
)
_GLASS_05 = _Pack(
    ContainerType.glass_returnable,
    "0.500",
    12,
    "0.08",
    "Glasflasche 0,5 L Mehrweg",
    "Kronkorken silber",
    "Kunststoffkasten 12 x 0,5 L",
)
_GLASS_07 = _Pack(
    ContainerType.glass_returnable,
    "0.700",
    12,
    "0.15",
    "Glasflasche 0,7 L Mehrweg",
    "Kronkorken gold",
    "Kunststoffkasten 12 x 0,7 L",
)
_PET_05 = _Pack(
    ContainerType.pet,
    "0.500",
    12,
    "0.25",
    "PET-Flasche 0,5 L",
    "Verschluss PCO 28mm",
    "Kunststoffkasten 12 x 0,5 L",
)
_PET_10 = _Pack(
    ContainerType.pet,
    "1.000",
    6,
    "0.25",
    "PET-Flasche 1,0 L",
    "Verschluss PCO 28mm",
    "Kunststoffkasten 6 x 1,0 L",
)


@dataclass(frozen=True)
class _Beverage:
    name: str
    category: ProductCategory
    brand: str
    launched: date
    shelf_life_days: int
    price_per_litre: str  # net list price basis
    packs: list[_Pack]
    # recipe: (raw_material name, quantity per 1000 L, unit of measure)
    recipe: list[tuple[str, str, str]]


_BEVERAGES: list[_Beverage] = [
    _Beverage(
        "Mineralwasser still",
        ProductCategory.mineral_water,
        "Brunnstein",
        date(2015, 1, 1),
        365,
        "0.55",
        [_GLASS_07, _PET_10],
        [
            ("Quellwasser Brunnstein", "1005", "L"),
            ("Mineralextrakt Calcium-Magnesium", "0.400", "kg"),
        ],
    ),
    _Beverage(
        "Mineralwasser medium",
        ProductCategory.mineral_water,
        "Brunnstein",
        date(2015, 1, 1),
        365,
        "0.55",
        [_GLASS_07, _PET_10, _PET_05],
        [
            ("Quellwasser Brunnstein", "1005", "L"),
            ("Mineralextrakt Calcium-Magnesium", "0.400", "kg"),
            ("CO2 Lebensmittelqualität", "4.500", "kg"),
        ],
    ),
    _Beverage(
        "Mineralwasser classic",
        ProductCategory.mineral_water,
        "Brunnstein",
        date(2015, 1, 1),
        365,
        "0.55",
        [_GLASS_05, _PET_10],
        [
            ("Quellwasser Brunnstein", "1005", "L"),
            ("Mineralextrakt Calcium-Magnesium", "0.400", "kg"),
            ("CO2 Lebensmittelqualität", "8.000", "kg"),
        ],
    ),
    _Beverage(
        "Cola",
        ProductCategory.soft_drink,
        "Brunnstein",
        date(2016, 3, 1),
        270,
        "1.20",
        [_GLASS_033, _PET_05, _PET_10],
        [
            ("Quellwasser Brunnstein", "880", "L"),
            ("CO2 Lebensmittelqualität", "6.000", "kg"),
            ("Sirupkonzentrat Cola", "120", "kg"),
            ("Zucker Saccharose", "105", "kg"),
            ("Zitronensäure", "1.200", "kg"),
        ],
    ),
    _Beverage(
        "Limonade Zitrone",
        ProductCategory.soft_drink,
        "Brunnstein",
        date(2016, 3, 1),
        270,
        "1.10",
        [_GLASS_033, _PET_05],
        [
            ("Quellwasser Brunnstein", "890", "L"),
            ("CO2 Lebensmittelqualität", "5.500", "kg"),
            ("Sirupkonzentrat Zitrone", "110", "kg"),
            ("Zucker Saccharose", "100", "kg"),
            ("Zitronensäure", "1.800", "kg"),
            ("Citrusaroma natürlich", "0.500", "L"),
        ],
    ),
    _Beverage(
        "Limonade Orange",
        ProductCategory.soft_drink,
        "Brunnstein",
        date(2016, 3, 1),
        270,
        "1.10",
        [_GLASS_033, _PET_05],
        [
            ("Quellwasser Brunnstein", "890", "L"),
            ("CO2 Lebensmittelqualität", "5.500", "kg"),
            ("Sirupkonzentrat Orange", "110", "kg"),
            ("Zucker Saccharose", "100", "kg"),
            ("Zitronensäure", "1.500", "kg"),
            ("Citrusaroma natürlich", "0.500", "L"),
        ],
    ),
    _Beverage(
        "Apfelschorle",
        ProductCategory.spritzer,
        "Brunnstein",
        date(2017, 4, 1),
        240,
        "1.00",
        [_GLASS_05, _PET_05],
        [
            ("Quellwasser Brunnstein", "600", "L"),
            ("CO2 Lebensmittelqualität", "5.000", "kg"),
            ("Fruchtmark Apfel", "400", "kg"),
            ("Zitronensäure", "0.600", "kg"),
        ],
    ),
    _Beverage(
        "Holunderschorle",
        ProductCategory.spritzer,
        "Brunnstein",
        date(2019, 5, 1),
        240,
        "1.05",
        [_GLASS_05],
        [
            ("Quellwasser Brunnstein", "650", "L"),
            ("CO2 Lebensmittelqualität", "5.000", "kg"),
            ("Fruchtmark Holunder", "320", "kg"),
            ("Sirupkonzentrat Holunder", "60", "kg"),
            ("Zitronensäure", "0.600", "kg"),
        ],
    ),
    _Beverage(
        "Craft IPA",
        ProductCategory.craft,
        "Brunnstein Bräu",
        date(2021, 6, 1),
        180,
        "2.80",
        [_GLASS_033],
        [
            ("Quellwasser Brunnstein", "1000", "L"),
            ("Hopfen Tettnanger", "2.500", "kg"),
            ("CO2 Lebensmittelqualität", "4.000", "kg"),
        ],
    ),
    _Beverage(
        "Craft Pils",
        ProductCategory.craft,
        "Brunnstein Bräu",
        date(2020, 6, 1),
        180,
        "2.40",
        [_GLASS_05],
        [
            ("Quellwasser Brunnstein", "1000", "L"),
            ("Hopfen Hallertauer Mittelfrüh", "1.800", "kg"),
            ("CO2 Lebensmittelqualität", "4.500", "kg"),
        ],
    ),
    _Beverage(
        "Bio-Eistee",
        ProductCategory.specialty,
        "Brunnstein Selektion",
        date(2022, 4, 1),
        300,
        "1.80",
        [_PET_05, _GLASS_033],
        [
            ("Quellwasser Brunnstein", "940", "L"),
            ("Zucker Saccharose", "70", "kg"),
            ("Kräuterextrakt Alpenkräuter", "1.500", "L"),
            ("Citrusaroma natürlich", "0.400", "L"),
            ("Zitronensäure", "1.000", "kg"),
        ],
    ),
    _Beverage(
        "Tonic Water",
        ProductCategory.specialty,
        "Brunnstein Selektion",
        date(2020, 9, 1),
        300,
        "1.90",
        [_GLASS_033],
        [
            ("Quellwasser Brunnstein", "880", "L"),
            ("CO2 Lebensmittelqualität", "7.000", "kg"),
            ("Zucker Saccharose", "90", "kg"),
            ("Bitterstoff Chinin", "0.070", "kg"),
            ("Zitronensäure", "1.500", "kg"),
        ],
    ),
]

# Per-1000 L scrap rates by packaging role (filling and labelling losses).
_BOTTLE_SCRAP = "1.50"
_CAP_SCRAP = "0.50"
_LABEL_SCRAP = "2.00"


_CONTAINER_LABEL: dict[ContainerType, str] = {
    ContainerType.glass_returnable: "Glas Mehrweg",
    ContainerType.glass_oneway: "Glas Einweg",
    ContainerType.pet: "PET",
    ContainerType.can: "Dose",
}


def _pack_label(volume_l: str, container: ContainerType) -> str:
    litres = format(Decimal(volume_l).normalize(), "f")
    litres = f"{litres},0" if "." not in litres else litres.replace(".", ",")
    return f"{litres} L {_CONTAINER_LABEL[container]}"


def _by_name(materials: list[RawMaterial]) -> dict[str, RawMaterial]:
    index = {m.name: m for m in materials}
    return index


def generate_products(
    materials: list[RawMaterial],
) -> tuple[list[Product], list[ProductComponent]]:
    """Build the finished-goods catalogue and BOMs from the raw-material master.

    Every BOM line references a raw material by name; an unknown name is a
    catalogue/recipe mismatch and raises immediately rather than producing a
    silently broken bill of materials.
    """
    index = _by_name(materials)

    def resolve(name: str) -> RawMaterial:
        try:
            return index[name]
        except KeyError as exc:
            raise KeyError(f"BOM references unknown raw material: {name!r}") from exc

    products: list[Product] = []
    components: list[ProductComponent] = []
    material_seq = 10001

    for bev in _BEVERAGES:
        for pack in bev.packs:
            volume = Decimal(pack.volume_l)
            unit_price = (Decimal(bev.price_per_litre) * volume).quantize(Decimal("0.0001"))
            product = Product(
                id=uuid4(),
                material_number=f"F-{material_seq}",
                name=f"{bev.name} {_pack_label(pack.volume_l, pack.container_type)}",
                brand=bev.brand,
                category=bev.category,
                container_type=pack.container_type,
                volume_l=volume,
                units_per_case=pack.units_per_case,
                deposit_eur=Decimal(pack.deposit_eur),
                list_price_net_eur=unit_price,
                vat_rate_pct=Decimal("19.00"),
                shelf_life_days=bev.shelf_life_days,
                launched_date=bev.launched,
                active=True,
            )
            products.append(product)
            material_seq += 1

            # Liquid recipe.
            for mat_name, qty, uom in bev.recipe:
                components.append(
                    ProductComponent(
                        id=uuid4(),
                        product_id=product.id,
                        raw_material_id=resolve(mat_name).id,
                        quantity_per_1000l=Decimal(qty),
                        unit_of_measure=uom,
                        scrap_pct=Decimal("0.00"),
                    )
                )

            # Packaging, derived from the pack and bottle volume.
            bottles_per_1000l = (Decimal(1000) / volume).quantize(Decimal("0.001"))
            crates_per_1000l = (bottles_per_1000l / pack.units_per_case).quantize(Decimal("0.001"))
            packaging = [
                (pack.bottle, bottles_per_1000l, "Stk", _BOTTLE_SCRAP),
                (pack.cap, bottles_per_1000l, "Stk", _CAP_SCRAP),
                (f"Etikett {bev.name}", bottles_per_1000l, "Stk", _LABEL_SCRAP),
                (pack.crate, crates_per_1000l, "Stk", "0.00"),
            ]
            for mat_name, qty, uom, scrap in packaging:
                components.append(
                    ProductComponent(
                        id=uuid4(),
                        product_id=product.id,
                        raw_material_id=resolve(mat_name).id,
                        quantity_per_1000l=qty,
                        unit_of_measure=uom,
                        scrap_pct=Decimal(scrap),
                    )
                )

    return products, components
