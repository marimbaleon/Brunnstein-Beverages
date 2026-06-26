"""Images: programmatic PNGs now, photorealistic prompts for later.

Two kinds of asset are produced:

* **Rendered offline with Pillow** — functional artwork that is deterministic
  and free to make: a product label mock-up per SKU (brand, name, volume, a
  faux barcode) and a sign per plant. These are real PNG files.
* **Prompt manifest** (``prompts.jsonl``) — for photorealistic assets that a
  text model cannot draw (product beauty shots, the damage photos referenced by
  complaints). Each entry is a detailed prompt plus target path and size, ready
  to feed to an image model in a separate, optional step.

Files land under ``data/documents/images/``.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from data.erp.models import Plant, Product, ProductCategory

_ROOT = Path(__file__).resolve().parent / "images"

_CATEGORY_COLOR: dict[ProductCategory, tuple[int, int, int]] = {
    ProductCategory.mineral_water: (38, 110, 180),
    ProductCategory.soft_drink: (200, 60, 50),
    ProductCategory.spritzer: (70, 150, 80),
    ProductCategory.craft: (150, 100, 40),
    ProductCategory.specialty: (110, 70, 150),
}

_FONT = ImageFont.load_default()


def _barcode(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, rng: random.Random) -> None:
    cx = x
    while cx < x + w:
        bar = rng.choice([2, 2, 3, 4])
        if rng.random() < 0.55:
            draw.rectangle([cx, y, cx + bar, y + h], fill=(20, 20, 20))
        cx += bar + rng.choice([1, 2])


def _label_png(product: Product, path: Path, rng: random.Random) -> None:
    w, h = 600, 400
    color = _CATEGORY_COLOR[product.category]
    img = Image.new("RGB", (w, h), (245, 245, 242))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, w, 90], fill=color)
    draw.text((24, 34), product.brand.upper(), fill=(255, 255, 255), font=_FONT)
    draw.text((24, 150), product.name, fill=(30, 30, 30), font=_FONT)
    volume = f"{product.volume_l:.3f} L".replace(".", ",")
    draw.text(
        (24, 190), f"{volume}  ·  {product.container_type.value}", fill=(80, 80, 80), font=_FONT
    )
    draw.text(
        (24, 230),
        f"Art.-Nr. {product.material_number}  ·  Pfand {product.deposit_eur:.2f} EUR",
        fill=(80, 80, 80),
        font=_FONT,
    )
    _barcode(draw, 24, 300, 320, 60, rng)
    draw.rectangle([0, h - 14, w, h], fill=color)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def _sign_png(plant: Plant, path: Path) -> None:
    w, h = 600, 300
    img = Image.new("RGB", (w, h), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, w, h], outline=(31, 58, 95), width=8)
    draw.text((40, 90), "BRUNNSTEIN BEVERAGES", fill=(31, 58, 95), font=_FONT)
    draw.text((40, 140), f"{plant.name}  (Werk {plant.plant_code})", fill=(40, 40, 40), font=_FONT)
    draw.text(
        (40, 180),
        f"{plant.street}, {plant.postal_code} {plant.city}",
        fill=(90, 90, 90),
        font=_FONT,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


_DAMAGE_PROMPT = {
    "foreign_object": (
        "close-up product photo of a clear beverage bottle with a small dark foreign "
        "particle floating inside, neutral kitchen background, smartphone snapshot, "
        "natural light, slightly blurry"
    ),
    "packaging_damage": (
        "photo of a damaged beverage cardboard tray with one broken glass bottle, spilled "
        "liquid, dented packaging, on a wooden floor, smartphone snapshot, harsh flash"
    ),
}


def write_images(
    products: list[Product],
    plants: list[Plant],
    complaints_ndjson: Path | None = None,
    seed: int = 42,
    out_dir: Path = _ROOT,
) -> dict[str, int]:
    """Render labels and signage, and write the photorealistic prompt manifest."""
    rng = random.Random(seed + 31)
    out_dir.mkdir(parents=True, exist_ok=True)
    rendered = 0

    for product in sorted(products, key=lambda p: p.material_number):
        _label_png(product, out_dir / "labels" / f"{product.material_number}.png", rng)
        rendered += 1
    for plant in plants:
        _sign_png(plant, out_dir / "signage" / f"{plant.plant_code}.png")
        rendered += 1

    prompts: list[dict] = []
    for product in sorted(products, key=lambda p: p.material_number):
        prompts.append(
            {
                "asset_id": f"beauty-{product.material_number}",
                "kind": "product_beauty_shot",
                "target_path": f"images/beauty/{product.material_number}.jpg",
                "width": 1024,
                "height": 1024,
                "seed": rng.randint(1, 10**9),
                "prompt": (
                    f"professional studio product photograph of a {product.container_type.value} "
                    f"bottle of {product.name} by {product.brand}, condensation droplets, "
                    f"soft gradient background, crisp commercial lighting, high detail"
                ),
                "negative_prompt": "text artifacts, watermark, deformed bottle, extra labels",
            }
        )

    if complaints_ndjson and complaints_ndjson.exists():
        for line in complaints_ndjson.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            if not rec.get("has_image"):
                continue
            prompt = _DAMAGE_PROMPT.get(rec["category"])
            if not prompt:
                continue
            prompts.append(
                {
                    "asset_id": rec["complaint_id"],
                    "kind": "complaint_photo",
                    "target_path": rec["image_path"],
                    "width": 768,
                    "height": 768,
                    "seed": rng.randint(1, 10**9),
                    "prompt": prompt,
                    "negative_prompt": "studio lighting, professional, clean, watermark",
                }
            )

    (out_dir / "prompts.jsonl").write_text(
        "\n".join(json.dumps(p, ensure_ascii=False) for p in prompts) + "\n",
        encoding="utf-8",
    )
    return {"rendered_png": rendered, "prompt_manifest_entries": len(prompts)}
