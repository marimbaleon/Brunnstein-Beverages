"""Bronze: raw webshop clickstream as line-delimited JSON.

One JSON object per line, each a browsing session with a nested event array and
nested device / utm / geo context. The stream is deliberately messy: a slice of
traffic is bots (rapid, never converting, flagged by user agent), and a small
fraction of events are duplicated (at-least-once delivery). Flattening these
sessions into a conformed event table is the Bronze -> Silver job; the funnel
(view -> cart -> checkout -> purchase) drives conversion analytics.

Files land under ``data/export/bronze/webshop_events/`` (one per month).
"""

from __future__ import annotations

import json
import math
import random
from datetime import date, datetime, timedelta
from pathlib import Path

from data.erp.models import Product, WebshopCustomer
from data.export import BRONZE_ROOT

_BRONZE_ROOT = BRONZE_ROOT / "webshop_events"

_BASE_SESSIONS_PER_YEAR = 20000
_YEAR_GROWTH: dict[int, float] = {2023: 1.00, 2024: 1.40, 2025: 1.80}

_DEVICES = [
    ({"type": "mobile", "os": "iOS", "browser": "Safari"}, 38),
    ({"type": "mobile", "os": "Android", "browser": "Chrome"}, 30),
    ({"type": "desktop", "os": "Windows", "browser": "Chrome"}, 18),
    ({"type": "desktop", "os": "macOS", "browser": "Safari"}, 9),
    ({"type": "tablet", "os": "iPadOS", "browser": "Safari"}, 5),
]
_UTM_SOURCES = [
    ({"source": "google", "medium": "organic", "campaign": None}, 35),
    ({"source": "google", "medium": "cpc", "campaign": "brand_search"}, 15),
    ({"source": "instagram", "medium": "social", "campaign": "sommer_aktion"}, 14),
    ({"source": "newsletter", "medium": "email", "campaign": "monatsangebot"}, 12),
    ({"source": "direct", "medium": "none", "campaign": None}, 24),
]
_REGIONS = [
    "Bayern",
    "Baden-Württemberg",
    "Nordrhein-Westfalen",
    "Hessen",
    "Berlin",
    "Niedersachsen",
    "Sachsen",
    "Hamburg",
]
_BOT_AGENTS = ["AhrefsBot/7.0", "SemrushBot/7", "python-requests/2.31", "Bytespider"]

_BOT_RATE = 0.08
_DUP_RATE = 0.015


def _seasonality(month: int) -> float:
    return 1.0 + 0.35 * math.cos((month - 7) * math.pi / 6.0)


def _pick(options: list[tuple[dict, int]], rng: random.Random) -> dict:
    items = [o for o, _ in options]
    weights = [w for _, w in options]
    return rng.choices(items, weights=weights, k=1)[0]


def _session(
    started: datetime,
    customer: WebshopCustomer | None,
    catalogue: list[Product],
    rng: random.Random,
) -> dict:
    is_bot = rng.random() < _BOT_RATE
    ts = started
    events: list[dict] = []

    def add(event_type: str, **payload) -> None:
        nonlocal ts
        ts = ts + timedelta(seconds=rng.randint(2, 90))
        event = {"ts": ts.isoformat(timespec="seconds"), "type": event_type, **payload}
        events.append(event)
        if rng.random() < _DUP_RATE:  # at-least-once duplicate
            events.append(dict(event))

    add("session_start", landing="/")
    for _ in range(rng.randint(1, 4) if not is_bot else rng.randint(8, 25)):
        add("page_view", url=rng.choice(["/", "/sortiment", "/angebote", "/marken", "/kontakt"]))

    viewed: list[Product] = []
    if not is_bot and rng.random() < 0.6:
        for product in rng.sample(catalogue, k=min(rng.randint(1, 4), len(catalogue))):
            viewed.append(product)
            add("product_view", sku=product.material_number, name=product.name)
    if not is_bot and rng.random() < 0.3:
        add("search", query=rng.choice(["wasser", "cola kiste", "craft", "apfelschorle", "tonic"]))

    in_cart: list[Product] = []
    if viewed and rng.random() < 0.35:
        for product in rng.sample(viewed, k=min(rng.randint(1, 2), len(viewed))):
            in_cart.append(product)
            add("add_to_cart", sku=product.material_number, cases=rng.randint(1, 3))

    purchased = False
    if in_cart and rng.random() < 0.5:
        add("begin_checkout", cart_items=len(in_cart))
        if rng.random() < 0.6:
            value = round(sum(float(p.list_price_net_eur) * 1.19 * 1.6 * 2 for p in in_cart), 2)
            add("purchase", value_eur=value, items=len(in_cart))
            purchased = True

    session = {
        "session_id": f"s-{started.strftime('%Y%m%d')}-{rng.randint(10**7, 10**8 - 1)}",
        "customer_ref": None if (is_bot or customer is None) else customer.customer_ref,
        "started_at": started.isoformat(timespec="seconds"),
        "ended_at": ts.isoformat(timespec="seconds"),
        "device": _pick(_DEVICES, rng),
        "geo": {"region": rng.choice(_REGIONS), "country": "DE"},
        "utm": _pick(_UTM_SOURCES, rng),
        "is_bot": is_bot,
        "user_agent": rng.choice(_BOT_AGENTS) if is_bot else "Mozilla/5.0",
        "converted": purchased,
        "events": events,
    }
    return session


def write_webshop_events(
    customers: list[WebshopCustomer],
    products: list[Product],
    year_range: tuple[int, int] = (2023, 2025),
    today: date = date(2026, 1, 15),
    seed: int = 42,
    out_dir: Path = _BRONZE_ROOT,
) -> list[Path]:
    """Write one JSONL file of sessions per month. Returns the paths written."""
    rng = random.Random(seed + 2)
    catalogue = [p for p in products if p.active]
    out_dir.mkdir(parents=True, exist_ok=True)

    month_weights = [_seasonality(m) for m in range(1, 13)]
    monthly_share = [w / sum(month_weights) for w in month_weights]

    written: list[Path] = []
    for year in range(year_range[0], year_range[1] + 1):
        n_year = int(_BASE_SESSIONS_PER_YEAR * _YEAR_GROWTH.get(year, 1.0))
        for month in range(1, 13):
            n_month = round(n_year * monthly_share[month - 1])
            sessions: list[dict] = []
            for _ in range(n_month):
                started = datetime(
                    year, month, rng.randint(1, 28), rng.randint(0, 23), rng.randint(0, 59)
                )
                if started.date() > today:
                    continue
                # ~55% of sessions are tied to a known (logged-in) customer.
                customer = rng.choice(customers) if rng.random() < 0.55 else None
                sessions.append(_session(started, customer, catalogue, rng))

            if not sessions:
                continue
            path = out_dir / f"events_{year}-{month:02d}.jsonl"
            with path.open("w", encoding="utf-8") as fh:
                for session in sessions:
                    fh.write(json.dumps(session, ensure_ascii=False) + "\n")
            written.append(path)

    return written
