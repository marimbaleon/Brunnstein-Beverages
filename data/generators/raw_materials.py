"""Synthetic raw material master data for Brunnstein.

Templated across packaging, ingredients, and auxiliaries. About 100 SKUs.
"""

from __future__ import annotations

import random
from uuid import uuid4

from data.models import RawMaterial, RawMaterialCategory

_INACTIVE_RATE = 0.05


def _packaging() -> list[tuple[str, RawMaterialCategory, str]]:
    items: list[tuple[str, RawMaterialCategory, str]] = []
    # Glass bottles
    for size in ["0,25 L", "0,33 L", "0,5 L", "0,7 L", "1,0 L"]:
        for kind in ["Mehrweg", "Einweg"]:
            items.append((f"Glasflasche {size} {kind}", RawMaterialCategory.packaging, "Stk"))
    # PET bottles
    for size in ["0,5 L", "1,0 L", "1,5 L"]:
        items.append((f"PET-Flasche {size}", RawMaterialCategory.packaging, "Stk"))
    # Crown caps
    for color in ["gold", "silber", "rot", "blau", "grün", "schwarz"]:
        items.append((f"Kronkorken {color}", RawMaterialCategory.packaging, "Stk"))
    # Screw caps
    for kind in ["PCO 28mm", "PCO 38mm", "Aluminium 28mm", "Schraubverschluss Glas 28mm"]:
        items.append((f"Verschluss {kind}", RawMaterialCategory.packaging, "Stk"))
    # Labels
    for product in [
        "Mineralwasser still",
        "Mineralwasser medium",
        "Mineralwasser classic",
        "Cola",
        "Limonade Zitrone",
        "Limonade Orange",
        "Apfelschorle",
        "Holunderschorle",
        "Craft IPA",
        "Craft Pils",
        "Bio-Eistee",
        "Tonic Water",
    ]:
        items.append((f"Etikett {product}", RawMaterialCategory.packaging, "Stk"))
    # Crates
    for layout in ["12 x 0,5 L", "20 x 0,5 L", "6 x 1,0 L", "24 x 0,33 L", "12 x 0,7 L"]:
        items.append((f"Kunststoffkasten {layout}", RawMaterialCategory.packaging, "Stk"))
    # Pallets and films
    items.append(("Europalette", RawMaterialCategory.packaging, "Stk"))
    items.append(("Halbpalette", RawMaterialCategory.packaging, "Stk"))
    items.append(("Stretchfolie transparent", RawMaterialCategory.packaging, "kg"))
    items.append(("Schrumpffolie Tray", RawMaterialCategory.packaging, "kg"))
    return items


def _ingredients() -> list[tuple[str, RawMaterialCategory, str]]:
    items: list[tuple[str, RawMaterialCategory, str]] = []
    # CO2 grades
    items.append(("CO2 Lebensmittelqualität", RawMaterialCategory.ingredient, "kg"))
    items.append(("CO2 technisch", RawMaterialCategory.ingredient, "kg"))
    # Water and minerals
    items.append(("Quellwasser Brunnstein", RawMaterialCategory.ingredient, "L"))
    items.append(("Mineralextrakt Calcium-Magnesium", RawMaterialCategory.ingredient, "kg"))
    items.append(("Mineralextrakt Natrium-Bicarbonat", RawMaterialCategory.ingredient, "kg"))
    # Syrups
    for flavor in [
        "Cola",
        "Zitrone",
        "Orange",
        "Apfel",
        "Holunder",
        "Kirsche",
        "Birne",
        "Multifrucht",
        "Tonic",
        "Ingwer",
    ]:
        items.append((f"Sirupkonzentrat {flavor}", RawMaterialCategory.ingredient, "kg"))
    # Aromas
    for aroma in [
        "Citrusaroma natürlich",
        "Vanillearoma",
        "Minzöl",
        "Kräuterextrakt Alpenkräuter",
        "Bitterstoff Chinin",
    ]:
        items.append((aroma, RawMaterialCategory.ingredient, "L"))
    # Fruit pulps
    for fruit in [
        "Apfel",
        "Birne",
        "Holunder",
        "Sauerkirsche",
        "Schwarze Johannisbeere",
        "Heidelbeere",
    ]:
        items.append((f"Fruchtmark {fruit}", RawMaterialCategory.ingredient, "kg"))
    # Sweeteners
    items.append(("Zucker Saccharose", RawMaterialCategory.ingredient, "kg"))
    items.append(("Fructose-Sirup", RawMaterialCategory.ingredient, "kg"))
    items.append(("Stevia-Extrakt", RawMaterialCategory.ingredient, "kg"))
    items.append(("Glucose-Sirup", RawMaterialCategory.ingredient, "kg"))
    # Hops (craft beverages)
    for hop in ["Tettnanger", "Hallertauer Mittelfrüh", "Spalter Select", "Perle", "Saphir"]:
        items.append((f"Hopfen {hop}", RawMaterialCategory.ingredient, "kg"))
    # Acids and preservatives
    items.append(("Zitronensäure", RawMaterialCategory.ingredient, "kg"))
    items.append(("Ascorbinsäure", RawMaterialCategory.ingredient, "kg"))
    items.append(("Kaliumsorbat", RawMaterialCategory.ingredient, "kg"))
    return items


def _auxiliaries() -> list[tuple[str, RawMaterialCategory, str]]:
    items: list[tuple[str, RawMaterialCategory, str]] = []
    for chem in [
        "CIP Lauge",
        "CIP Säure",
        "Desinfektionsmittel Peressigsäure",
        "Glasreiniger",
        "Edelstahlpflege",
        "Schaumreiniger alkalisch",
    ]:
        items.append((chem, RawMaterialCategory.auxiliary, "L"))
    for lub in [
        "Lebensmittelschmierstoff H1",
        "Kettenöl Lebensmittelqualität",
        "Pumpenfett NSF",
        "Gleitmittel Bandschmierung",
    ]:
        items.append((lub, RawMaterialCategory.auxiliary, "kg"))
    for lab in [
        "Titrationslösung Säure",
        "pH-Pufferlösung 4,0",
        "pH-Pufferlösung 7,0",
        "Calciumstandard",
        "Mikrobiologie-Nährboden",
        "Indikatorpapier",
    ]:
        items.append((lab, RawMaterialCategory.auxiliary, "Stk"))
    return items


def generate_raw_materials(seed: int = 42) -> list[RawMaterial]:
    rng = random.Random(seed)
    specs = _packaging() + _ingredients() + _auxiliaries()
    materials: list[RawMaterial] = []
    for i, (name, category, uom) in enumerate(specs, start=1):
        materials.append(
            RawMaterial(
                id=uuid4(),
                material_number=f"M-{i:05d}",
                name=name,
                category=category,
                unit_of_measure=uom,
                active=rng.random() > _INACTIVE_RATE,
            )
        )
    return materials
