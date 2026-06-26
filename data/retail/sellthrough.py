"""Bronze: weekly point-of-sale sell-through files from retail partners.

Each named retail chain sends Brunnstein a periodic export of what end
consumers bought from its stores. Crucially, every partner uses a *different*
file layout: delimiter, decimal separator, date format, column names,
language and even encoding vary. That heterogeneity is the point: harmonising
these into one conformed table is the Bronze -> Silver job for the
demand-sensing use case.

Sell-through is a separate signal from Brunnstein's own sales orders (it is
the retailer's downstream sales), but it follows the same seasonal demand
curve, so the two correlate without being copies.

The files are written under ``data/export/bronze/retail_sellthrough/<partner>/``.
Nothing here touches the database.
"""

from __future__ import annotations

import csv
import math
import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from data.erp.models import Customer, CustomerChannel, Product, ProductCategory
from data.export import BRONZE_ROOT

_BRONZE_ROOT = BRONZE_ROOT / "retail_sellthrough"

# Same seasonal shape the sales generator uses, so sell-through tracks demand.
_CATEGORY_SEASON_AMP: dict[ProductCategory, float] = {
    ProductCategory.mineral_water: 0.50,
    ProductCategory.soft_drink: 0.35,
    ProductCategory.spritzer: 0.45,
    ProductCategory.craft: 0.15,
    ProductCategory.specialty: 0.25,
}
_CATEGORY_BASE: dict[ProductCategory, float] = {
    ProductCategory.mineral_water: 900,
    ProductCategory.soft_drink: 750,
    ProductCategory.spritzer: 450,
    ProductCategory.craft: 180,
    ProductCategory.specialty: 240,
}


@dataclass(frozen=True)
class _Profile:
    """A partner's idiosyncratic file format."""

    key: str
    delimiter: str
    decimal: str  # "." or ","
    encoding: str
    headers: list[str]
    period_fmt: str  # how the reporting week is written
    product_key: str  # which product identifier the partner reports by


# Four distinct layouts; partners are assigned round-robin.
_PROFILES: list[_Profile] = [
    _Profile(
        key="iso_comma",
        delimiter=",",
        decimal=".",
        encoding="utf-8",
        headers=["week_start", "sku", "product_name", "units_sold", "gross_sales_eur"],
        period_fmt="iso",  # 2024-02-05
        product_key="material_number",
    ),
    _Profile(
        key="de_semicolon",
        delimiter=";",
        decimal=",",
        encoding="utf-8",
        headers=["KW", "Artikelnr", "Bezeichnung", "Menge", "Umsatz_Brutto"],
        period_fmt="kw",  # 2024-KW06
        product_key="material_number",
    ),
    _Profile(
        key="tab_legacy",
        delimiter="\t",
        decimal=".",
        encoding="latin-1",
        headers=["PERIOD", "PRODUCT", "QTY", "VALUE"],
        period_fmt="dmy",  # 05.02.2024
        product_key="name",
    ),
    _Profile(
        key="de_monthly",
        delimiter=";",
        decimal=",",
        encoding="utf-8",
        headers=["Monat", "Artikel", "Bezeichnung", "Absatz_Stueck", "Umsatz"],
        period_fmt="month",  # 2024-02
        product_key="material_number",
    ),
]


def _season(category: ProductCategory, month: int) -> float:
    amp = _CATEGORY_SEASON_AMP[category]
    return 1.0 + amp * math.cos((month - 7) * math.pi / 6.0)


def _fmt_decimal(value: Decimal, decimal_sep: str) -> str:
    s = f"{value:.2f}"
    return s if decimal_sep == "." else s.replace(".", ",")


def _fmt_period(week_start: date, fmt: str) -> str:
    if fmt == "iso":
        return week_start.isoformat()
    if fmt == "kw":
        return f"{week_start.isocalendar().year}-KW{week_start.isocalendar().week:02d}"
    if fmt == "dmy":
        return week_start.strftime("%d.%m.%Y")
    if fmt == "month":
        return week_start.strftime("%Y-%m")
    raise ValueError(fmt)


def _weeks(start_year: int, end_year: int, today: date) -> list[date]:
    start = date(start_year, 1, 1)
    start -= timedelta(days=start.weekday())  # back to Monday
    weeks: list[date] = []
    cur = start
    end = date(end_year, 12, 31)
    while cur <= end:
        if start_year <= cur.year and cur <= today:
            weeks.append(cur)
        cur += timedelta(days=7)
    return weeks


def _partner_slug(name: str) -> str:
    keep = [c.lower() if c.isalnum() else "_" for c in name]
    slug = "".join(keep)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_")


def write_retail_sellthrough(
    products: list[Product],
    customers: list[Customer],
    year_range: tuple[int, int] = (2023, 2025),
    today: date = date(2026, 1, 15),
    seed: int = 42,
    out_dir: Path = _BRONZE_ROOT,
) -> list[Path]:
    """Write one CSV per partner per year. Returns the paths written."""
    rng = random.Random(seed)
    catalogue = [p for p in products if p.active]
    partners = [c for c in customers if c.channel == CustomerChannel.retail_chain and c.active]
    # The big named chains are the ones that report sell-through.
    partners = [c for c in partners if "GmbH" in c.name or "AG" in c.name or "eG" in c.name][:10]

    weeks = _weeks(year_range[0], year_range[1], today)
    written: list[Path] = []

    for idx, partner in enumerate(partners):
        profile = _PROFILES[idx % len(_PROFILES)]
        partner_scale = rng.uniform(0.6, 2.2)  # store-network size
        carried = [p for p in catalogue if rng.random() < 0.85]  # not every SKU listed
        if not carried:
            carried = catalogue

        partner_dir = out_dir / _partner_slug(partner.name)
        partner_dir.mkdir(parents=True, exist_ok=True)

        # A few SKUs ship without a readable name in this partner's feed.
        name_for = {p.id: ("" if rng.random() < 0.05 else p.name) for p in carried}

        # Accumulate by reporting period. Weekly profiles get one row per week;
        # the monthly profile collapses the weeks of a month into one row.
        acc: dict[tuple[int, str, str, str], list] = {}
        for week_start in weeks:
            for product in carried:
                base = _CATEGORY_BASE[product.category] * partner_scale
                seasonal = _season(product.category, week_start.month)
                units = int(base * seasonal * rng.uniform(0.7, 1.3))
                if units <= 0:
                    continue
                if rng.random() < 0.01:  # occasional consumer-return week
                    units = -rng.randint(1, 12)
                consumer_price = (
                    product.list_price_net_eur
                    * Decimal("1.19")
                    * Decimal(str(round(rng.uniform(1.45, 1.85), 3)))
                )
                gross = (Decimal(units) * consumer_price).quantize(Decimal("0.01"))

                period = _fmt_period(week_start, profile.period_fmt)
                ident = getattr(product, profile.product_key)
                key = (week_start.year, period, ident, name_for[product.id])
                bucket = acc.setdefault(key, [0, Decimal("0")])
                bucket[0] += units
                bucket[1] += gross

        rows_by_year: dict[int, list[list[str]]] = {}
        for (year, period, ident, name), (units, gross) in acc.items():
            row = _row(profile, period, ident, name, units, gross)
            rows_by_year.setdefault(year, []).append(row)

        for year, rows in rows_by_year.items():
            path = partner_dir / f"sellthrough_{year}.csv"
            with path.open("w", encoding=profile.encoding, newline="") as fh:
                writer = csv.writer(fh, delimiter=profile.delimiter)
                writer.writerow(profile.headers)
                writer.writerows(rows)
            written.append(path)

    return written


def _row(
    profile: _Profile,
    period: str,
    ident: str,
    name: str,
    units: int,
    gross: Decimal,
) -> list[str]:
    value = _fmt_decimal(gross, profile.decimal)
    # Column order follows each profile's header order.
    if profile.key == "tab_legacy":
        return [period, name or ident, str(units), value]
    return [period, ident, name, str(units), value]
