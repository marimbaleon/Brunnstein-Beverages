"""Product specification sheets, one PDF per finished-goods SKU.

Each sheet states the master attributes (pack, deposit, shelf life, a synthetic
EAN), the ingredient list resolved from the product's bill of materials, a
per-100 ml nutrition table and storage notes. Values are coherent with the ERP
product and BOM, so extraction or RAG over these sheets lines up with the
structured catalogue.

Files land under ``data/documents/spec_sheets/``.
"""

from __future__ import annotations

import random
from decimal import Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from data.documents._pdf import build, styles
from data.erp.models import Product, ProductCategory, ProductComponent, RawMaterial

_ROOT = Path(__file__).resolve().parent / "spec_sheets"

# Per-100 ml nutrition profile by category: (energy_kcal, sugar_g, of which simple).
_NUTRITION: dict[ProductCategory, tuple[float, float]] = {
    ProductCategory.mineral_water: (0.0, 0.0),
    ProductCategory.soft_drink: (42.0, 10.5),
    ProductCategory.spritzer: (24.0, 5.8),
    ProductCategory.craft: (43.0, 3.2),
    ProductCategory.specialty: (28.0, 6.6),
}


def _ean(rng: random.Random) -> str:
    return "40" + "".join(str(rng.randint(0, 9)) for _ in range(11))


def _ingredients(
    product: Product, components: list[ProductComponent], materials: dict
) -> list[str]:
    names = []
    for comp in components:
        if comp.product_id != product.id:
            continue
        mat = materials.get(comp.raw_material_id)
        if mat is None or mat.category.value != "ingredient":
            continue
        names.append(mat.name)
    return names or ["Quellwasser Brunnstein"]


def _table(rows: list[list[str]], s) -> Table:
    table = Table(rows, colWidths=[55 * mm, 100 * mm])
    table.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#1f3a5f")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.lightgrey),
            ]
        )
    )
    return table


def write_spec_sheets(
    products: list[Product],
    components: list[ProductComponent],
    materials: list[RawMaterial],
    seed: int = 42,
    out_dir: Path = _ROOT,
) -> list[Path]:
    """Write one spec-sheet PDF per product. Returns the paths."""
    rng = random.Random(seed + 29)
    out_dir.mkdir(parents=True, exist_ok=True)
    material_by_id = {m.id: m for m in materials}
    s = styles()

    written: list[Path] = []
    for product in sorted(products, key=lambda p: p.material_number):
        energy, sugar = _NUTRITION[product.category]
        volume_ml = (product.volume_l * Decimal(1000)).quantize(Decimal("1"))
        ingredients = _ingredients(product, components, material_by_id)

        story = [
            Paragraph(product.name, s["title"]),
            Paragraph(
                f"{product.brand} · Produktspezifikation · {product.material_number}", s["subtitle"]
            ),
            Paragraph("Stammdaten", s["heading"]),
            _table(
                [
                    ["Artikelnummer", product.material_number],
                    ["EAN", _ean(rng)],
                    ["Kategorie", product.category.value],
                    ["Gebinde", product.container_type.value],
                    ["Füllmenge", f"{volume_ml} ml"],
                    ["Einheiten je Kasten", str(product.units_per_case)],
                    ["Pfand", f"{product.deposit_eur:.2f} EUR"],
                    ["Mindesthaltbarkeit", f"{product.shelf_life_days} Tage"],
                ],
                s,
            ),
            Paragraph("Zutaten", s["heading"]),
            Paragraph(", ".join(ingredients) + ".", s["body"]),
            Paragraph("Nährwerte je 100 ml", s["heading"]),
            _table(
                [
                    ["Energie", f"{energy:.0f} kcal"],
                    ["davon Zucker", f"{sugar:.1f} g"],
                    ["Kohlenhydrate", f"{sugar + rng.uniform(0, 0.5):.1f} g"],
                    ["Fett", "0 g"],
                    ["Eiweiß", "0 g"],
                    ["Salz", f"{rng.uniform(0.0, 0.05):.2f} g"],
                ],
                s,
            ),
            Paragraph("Lagerung & Handhabung", s["heading"]),
            Paragraph(
                "Kühl und trocken lagern, vor direkter Sonneneinstrahlung schützen. "
                "Nach dem Öffnen gekühlt aufbewahren und innerhalb weniger Tage "
                "verbrauchen. Charge und Mindesthaltbarkeitsdatum siehe Aufdruck.",
                s["body"],
            ),
            Spacer(1, 12),
            Paragraph("Brunnstein Beverages GmbH · Quellenstraße 1 · 83646 Bad Tölz", s["small"]),
        ]
        path = out_dir / f"{product.material_number}.pdf"
        build(path, story, f"Spezifikation {product.name}")
        written.append(path)

    return written
