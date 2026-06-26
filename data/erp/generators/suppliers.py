"""Synthetic supplier master data for Brunnstein.

50 fictional German company names covering packaging, ingredients,
auxiliaries, and logistics. Faker fills in the rest.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from uuid import uuid4

from faker import Faker

from data.erp.generators._text import slugify_company_name
from data.erp.models import Supplier


@dataclass(frozen=True)
class _Template:
    name: str
    city: str
    size: str  # small | mid | large


_TEMPLATES: list[_Template] = [
    # Glass bottles
    _Template("Süddeutsche Glaswerke GmbH", "München", "large"),
    _Template("Bayerische Flaschenmanufaktur AG", "Regensburg", "large"),
    _Template("Schwarzwald Glas KG", "Freiburg", "mid"),
    _Template("Mainfränkische Hohlglas GmbH", "Würzburg", "mid"),
    _Template("Glashütte Allgäu GmbH", "Kempten", "small"),
    _Template("Donautal Glaswerke AG", "Ulm", "large"),
    _Template("Norddeutsche Flaschenwerke GmbH", "Bremen", "large"),
    _Template("Glasmanufaktur Lehmann GmbH", "Augsburg", "small"),
    # PET
    _Template("PET-Werk Sigmaringen GmbH", "Sigmaringen", "mid"),
    _Template("Kunststoff Süd AG", "Stuttgart", "large"),
    _Template("PolyBottle Bayern GmbH", "Nürnberg", "mid"),
    # Closures
    _Template("Verschlusswerke Bodensee AG", "Konstanz", "mid"),
    _Template("Kronkorken Krause GmbH", "Heilbronn", "mid"),
    _Template("Schraubverschlüsse Süd GmbH", "Karlsruhe", "small"),
    _Template("CapTech München GmbH", "München", "mid"),
    # Labels
    _Template("Etikettendruckerei Reichelt GmbH", "Augsburg", "mid"),
    _Template("Donau Etiketten GmbH", "Regensburg", "small"),
    _Template("Folien und Drucke Stuttgart GmbH", "Stuttgart", "mid"),
    _Template("Schwarzwald Label KG", "Offenburg", "small"),
    # Crates and secondary packaging
    _Template("Allgäuer Kistenfabrik GmbH", "Memmingen", "small"),
    _Template("Kunststoffkisten Bayern AG", "Ingolstadt", "large"),
    _Template("Holzkisten Müller OHG", "Rosenheim", "small"),
    _Template("Mehrweg Verpackung Süd GmbH", "München", "mid"),
    # CO2
    _Template("Bayerische Kohlensäure KG", "München", "mid"),
    _Template("CO2-Werke Mannheim GmbH", "Mannheim", "large"),
    # Mineral / water rights
    _Template("Alpenquellen Lizenz GmbH", "Bad Tölz", "small"),
    _Template("Mineralextrakte Hessen GmbH", "Frankfurt", "mid"),
    _Template("Quellrechte Bodensee GmbH", "Friedrichshafen", "small"),
    # Syrups and aromas
    _Template("Würzburger Aromenwerk GmbH", "Würzburg", "mid"),
    _Template("Dr. Becker Syrup GmbH", "Stuttgart", "mid"),
    _Template("BioAroma Süd GmbH", "Freiburg", "small"),
    _Template("Aromatica Bayern KG", "München", "mid"),
    _Template("Schwarzwaldfrucht GmbH", "Lahr", "mid"),
    # Fruit
    _Template("Pfälzer Fruchtsaftpressen GmbH", "Neustadt an der Weinstraße", "mid"),
    _Template("Bodensee Apfelhof eG", "Meersburg", "small"),
    _Template("Bayerische Beerenmanufaktur GmbH", "Coburg", "small"),
    # Sweeteners
    _Template("Zuckerwerke Heilbronn AG", "Heilbronn", "large"),
    _Template("Naturzucker Süd GmbH", "Stuttgart", "mid"),
    # Hops (for craft beverages)
    _Template("Hopfen-Ernte Tettnang eG", "Tettnang", "mid"),
    _Template("Spalter Hopfenkontor GmbH", "Spalt", "small"),
    # Cleaning chemistry
    _Template("ChemTec Reinigungssysteme GmbH", "Mannheim", "mid"),
    _Template("Hygienechemie Süd GmbH", "Karlsruhe", "mid"),
    _Template("Brauereihygiene Bavaria GmbH", "München", "small"),
    # Lubricants
    _Template("Münchener Schmierstoffe AG", "München", "large"),
    _Template("TecLub Industrie GmbH", "Nürnberg", "mid"),
    # Lab and QC supplies
    _Template("Laborbedarf Köhler GmbH", "Heidelberg", "small"),
    _Template("AnalytikSüd GmbH", "Tübingen", "mid"),
    # Logistics
    _Template("Spedition Brenner-Express GmbH", "Rosenheim", "mid"),
    _Template("Bayerische Frachtdienste GmbH", "Augsburg", "mid"),
    _Template("Süddeutsche Logistik AG", "Stuttgart", "large"),
]


_PAYMENT_TERMS_BY_SIZE = {"small": 14, "mid": 30, "large": 45}
_INACTIVE_RATE = 0.08


def _vat_id(rng: random.Random) -> str:
    return "DE" + "".join(str(rng.randint(0, 9)) for _ in range(9))


def generate_suppliers(seed: int = 42) -> list[Supplier]:
    faker = Faker("de_DE")
    Faker.seed(seed)
    rng = random.Random(seed)

    suppliers: list[Supplier] = []
    for i, tpl in enumerate(_TEMPLATES, start=1):
        suppliers.append(
            Supplier(
                id=uuid4(),
                supplier_number=f"S-{i:05d}",
                name=tpl.name,
                vat_id=_vat_id(rng),
                iban=faker.iban(),
                bic=faker.swift(length=11),
                payment_terms_days=_PAYMENT_TERMS_BY_SIZE[tpl.size],
                street=faker.street_address(),
                postal_code=faker.postcode(),
                city=tpl.city,
                country="DE",
                email=f"info@{slugify_company_name(tpl.name)}.de",
                phone=faker.phone_number(),
                active=rng.random() > _INACTIVE_RATE,
            )
        )
    return suppliers
