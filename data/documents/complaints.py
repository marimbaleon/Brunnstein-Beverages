"""Consumer complaints submitted through the website contact form, as JSON.

One JSON file per complaint plus a ``complaints.ndjson`` roll-up. A little over
half of them quote a batch that actually failed a quality check in production,
so a root-cause use case can join a complaint back to the run, line and shift
that produced it; the rest cite healthy batches (noise). The free-text body is
German of deliberately mixed quality (typos, shouting, terse one-liners) to give
classification and routing models something realistic.

Files land under ``data/documents/complaints/``.
"""

from __future__ import annotations

import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path

from data.erp.models import Customer, Product, ProductionRun, QualityResult, WebshopCustomer

_ROOT = Path(__file__).resolve().parent / "complaints"

# Category -> (weight, default severity, body templates with mixed quality).
_CATEGORIES: dict[str, tuple[int, str, list[str]]] = {
    "taste_off": (
        28,
        "high",
        [
            "Das Getränk schmeckt abgestanden und irgendwie metallisch. Sehr enttäuschend.",
            "hab die flasche aufgemacht und es schmeckte komplett anders als sonst!! bitte prüfen",
            "Geschmack weicht stark ab, vermutlich ein fehlerhaftes Los. Charge siehe unten.",
        ],
    ),
    "foreign_object": (
        10,
        "critical",
        [
            "In der Flasche befand sich ein dunkler Partikel. Das ist inakzeptabel!!!",
            "Fremdkörper im Produkt gefunden, ich habe Fotos gemacht. Bitte um Rückmeldung.",
            "da schwamm was drin. ekelhaft. will mein geld zurück",
        ],
    ),
    "packaging_damage": (
        24,
        "medium",
        [
            "Zwei Flaschen waren undicht, der ganze Karton war klebrig und nass.",
            "Etikett löste sich ab und die Verschlusskappe war locker. Qualität lässt nach.",
            "kiste kam beschädigt an, eine flasche gebrochen",
        ],
    ),
    "carbonation": (
        16,
        "medium",
        [
            "Die Kohlensäure ist fast komplett weg, schmeckt schal.",
            "Viel zu wenig Sprudel, das Wasser ist quasi still obwohl medium drauf steht.",
            "zu wenig co2, enttäuschend für den preis",
        ],
    ),
    "delivery": (
        14,
        "low",
        [
            "Lieferung kam erst nach zwei Wochen, das ist deutlich zu lang.",
            "Ware wurde an den falschen Nachbarn geliefert, niemand erreichbar.",
            "paket viel zu spät, brauche das für eine feier gewesen",
        ],
    ),
    "wrong_product": (
        8,
        "low",
        [
            "Ich habe Apfelschorle bestellt und Limonade Orange erhalten.",
            "Falsche Sorte geliefert, bitte um Austausch.",
            "das war nicht was ich bestellt habe",
        ],
    ),
}

_SUBJECTS = {
    "taste_off": "Geschmacksabweichung",
    "foreign_object": "Fremdkörper im Produkt",
    "packaging_damage": "Beschädigte Verpackung",
    "carbonation": "Zu wenig Kohlensäure",
    "delivery": "Problem mit der Lieferung",
    "wrong_product": "Falsches Produkt erhalten",
}
_RESOLUTIONS = ["refund", "replacement", "apology", "callback"]
_STATUSES = [("new", 35), ("in_review", 25), ("resolved", 32), ("rejected", 8)]


def _defective_batches(runs: list[ProductionRun]) -> list[ProductionRun]:
    return [r for r in runs if any(c.result == QualityResult.fail for c in r.quality_checks)]


def write_complaints(
    production_runs: list[ProductionRun],
    products: list[Product],
    webshop_customers: list[WebshopCustomer],
    customers: list[Customer],
    n: int = 420,
    today: date = date(2026, 1, 15),
    seed: int = 42,
    out_dir: Path = _ROOT,
) -> list[Path]:
    """Write complaint JSON files and the ndjson roll-up. Returns the JSON paths."""
    rng = random.Random(seed + 23)
    out_dir.mkdir(parents=True, exist_ok=True)

    product_by_id = {p.id: p for p in products}
    defective = _defective_batches(production_runs)
    cat_keys = list(_CATEGORIES)
    cat_weights = [_CATEGORIES[k][0] for k in cat_keys]
    status_keys = [s for s, _ in _STATUSES]
    status_weights = [w for _, w in _STATUSES]

    records: list[dict] = []
    written: list[Path] = []

    for i in range(1, n + 1):
        category = rng.choices(cat_keys, weights=cat_weights, k=1)[0]
        _, severity, bodies = _CATEGORIES[category]

        # ~55% of product/quality complaints quote a genuinely defective batch.
        product_related = category in ("taste_off", "foreign_object", "carbonation")
        if product_related and defective and rng.random() < 0.55:
            run = rng.choice(defective)
        else:
            run = rng.choice(production_runs)
        product = product_by_id[run.product_id]

        # Complaint lands some days after the batch was produced, bounded by today.
        earliest = run.started_at.date() + timedelta(days=rng.randint(7, 120))
        if earliest > today:
            earliest = today
        submitted = datetime.combine(earliest, datetime.min.time()) + timedelta(
            hours=rng.randint(7, 21), minutes=rng.randint(0, 59)
        )

        # Mostly B2C webshop consumers; a minority are B2B accounts.
        if rng.random() < 0.85 and webshop_customers:
            wc = rng.choice(webshop_customers)
            customer = {
                "type": "consumer",
                "ref": wc.customer_ref,
                "name": f"{wc.first_name} {wc.last_name}",
                "email": wc.email,
                "postal_code": wc.postal_code,
            }
        else:
            bc = rng.choice(customers)
            customer = {
                "type": "business",
                "ref": bc.customer_number,
                "name": bc.name,
                "email": f"einkauf@{bc.customer_number.lower()}.example",
                "postal_code": bc.postal_code,
            }

        has_image = category in ("foreign_object", "packaging_damage") and rng.random() < 0.6
        complaint_id = f"CMP-{submitted.year}-{i:05d}"
        record = {
            "complaint_id": complaint_id,
            "submitted_at": submitted.isoformat(),
            "channel": "web_form",
            "customer": customer,
            "product_sku": product.material_number,
            "product_name": product.name,
            "batch_number": run.batch_number,
            "category": category,
            "severity": severity,
            "subject": _SUBJECTS[category],
            "message": rng.choice(bodies),
            "desired_resolution": rng.choice(_RESOLUTIONS),
            "has_image": has_image,
            "image_path": (f"images/complaints/{complaint_id}.jpg" if has_image else None),
            "status": rng.choices(status_keys, weights=status_weights, k=1)[0],
            "gdpr_consent": True,
        }
        records.append(record)
        path = out_dir / f"{complaint_id}.json"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(path)

    (out_dir / "complaints.ndjson").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )
    return written
