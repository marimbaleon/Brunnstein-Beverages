"""Bronze: webshop product reviews as JSON.

Free-text German reviews with a star rating, written so the language matches
the score (a 5-star review reads positive, a 1-star review complains about a
concrete problem). That gives the sentiment / aspect-extraction use case real
signal, and the negative reviews tie naturally to quality issues from the
production side.

One JSON array file per year under ``data/export/bronze/reviews/``.
"""

from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path

from data.erp.models import Product, WebshopCustomer
from data.export import BRONZE_ROOT

_BRONZE_ROOT = BRONZE_ROOT / "reviews"

# Rating distribution: skewed positive, with a real negative tail.
_RATINGS = [5, 4, 3, 2, 1]
_RATING_WEIGHTS = [44, 28, 12, 9, 7]

_TITLES: dict[int, list[str]] = {
    5: ["Top!", "Absolute Empfehlung", "Schmeckt hervorragend", "Wie immer klasse"],
    4: ["Gut", "Solide", "Fast perfekt", "Gerne wieder"],
    3: ["Geht so", "Mittelmaß", "Okay für den Preis"],
    2: ["Enttäuschend", "Nicht überzeugend", "Schon mal besser gehabt"],
    1: ["Mangelhaft", "Reklamation nötig", "Nicht empfehlenswert"],
}
_BODIES: dict[int, list[str]] = {
    5: [
        "Schmeckt frisch und spritzig, die Lieferung kam schon am nächsten Tag.",
        "Beste Qualität, das Pfandsystem klappt reibungslos. Klare Kaufempfehlung.",
        "Unser Lieblingsgetränk, bestellen wir regelmäßig. Top Preis-Leistung.",
    ],
    4: [
        "Guter Geschmack, nur die Lieferung hat etwas länger gedauert.",
        "Solides Produkt, beim nächsten Mal gerne wieder. Preis ist in Ordnung.",
        "Insgesamt zufrieden, eine Flasche war etwas weniger spritzig.",
    ],
    3: [
        "Mittelmäßig, hatte mir mehr Geschmack erwartet. Lieferung war okay.",
        "Geht in Ordnung, aber nichts Besonderes für das Geld.",
    ],
    2: [
        "Der Geschmack hat im Vergleich zu früher nachgelassen, schade.",
        "Zwei Flaschen waren beim Auspacken undicht, Karton klebrig.",
    ],
    1: [
        "Die Kiste kam beschädigt an, drei Flaschen waren kaputt. Sehr ärgerlich.",
        "Eine Flasche war bereits geöffnet, das geht gar nicht. Musste reklamieren.",
        "Schmeckt abgestanden, vermutlich ein altes Los. Bekomme ich so nicht wieder.",
    ],
}


def _review_text(rating: int, product: Product, rng: random.Random) -> tuple[str, str]:
    title = rng.choice(_TITLES[rating])
    body = rng.choice(_BODIES[rating])
    if rng.random() < 0.4:
        body = f"{product.name}: {body}"
    return title, body


def write_reviews(
    customers: list[WebshopCustomer],
    products: list[Product],
    year_range: tuple[int, int] = (2023, 2025),
    today: date = date(2026, 1, 15),
    n: int = 1500,
    seed: int = 42,
    out_dir: Path = _BRONZE_ROOT,
) -> list[Path]:
    """Write product reviews grouped into one JSON array per year."""
    rng = random.Random(seed + 3)
    catalogue = [p for p in products if p.active]
    out_dir.mkdir(parents=True, exist_ok=True)

    earliest = date(year_range[0], 4, 1)  # first reviews land after launch ramps up
    span = max((today - earliest).days, 1)

    by_year: dict[int, list[dict]] = {}
    for i in range(1, n + 1):
        product = rng.choice(catalogue)
        customer = rng.choice(customers)
        rating = rng.choices(_RATINGS, weights=_RATING_WEIGHTS, k=1)[0]
        created = earliest + timedelta(days=rng.randint(0, span))
        if created > today:
            continue
        title, body = _review_text(rating, product, rng)
        review = {
            "review_id": f"R-{i:06d}",
            "product_sku": product.material_number,
            "product_name": product.name,
            "customer_ref": customer.customer_ref,
            "rating": rating,
            "title": title,
            "body": body,
            "language": "de",
            "verified_purchase": rng.random() < 0.8,
            "helpful_votes": rng.randint(0, 40),
            "created_at": created.isoformat(),
        }
        by_year.setdefault(created.year, []).append(review)

    written: list[Path] = []
    for year, reviews in by_year.items():
        path = out_dir / f"reviews_{year}.json"
        path.write_text(json.dumps(reviews, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(path)
    return written
