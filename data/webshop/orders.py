"""Generate the B2C webshop master data and online orders.

Consumers buy finished goods by the case through the online shop. The shop
launched at the start of the data window and grows year over year, with the
same summer-peaked seasonality as the rest of the business. Orders carry B2C
gross pricing, a shipping fee (free over a threshold) and a status that
depends on how recent the order is, including a small return rate.

The raw clickstream and product reviews are written separately as bronze
files; the orders here are the conformed transactional record.
"""

from __future__ import annotations

import math
import random
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import NamedTuple
from uuid import uuid4

from faker import Faker

from data.erp.models import (
    OnlineOrder,
    OnlineOrderLine,
    Product,
    ProductCategory,
    WebshopCustomer,
    WebshopOrderStatus,
    WebshopPaymentMethod,
)

_VAT = Decimal("1.19")
_CENT = Decimal("0.01")
_FREE_SHIPPING_OVER = Decimal("50.00")
_SHIPPING_FEE = Decimal("4.90")

_BASE_ORDERS_PER_YEAR = 3000
_YEAR_GROWTH: dict[int, float] = {2023: 1.00, 2024: 1.40, 2025: 1.80}

_REGIONS = [
    "Bayern",
    "Baden-Württemberg",
    "Nordrhein-Westfalen",
    "Hessen",
    "Berlin",
    "Niedersachsen",
    "Sachsen",
    "Rheinland-Pfalz",
    "Hamburg",
    "Thüringen",
]
_PAYMENT_WEIGHTS: dict[WebshopPaymentMethod, int] = {
    WebshopPaymentMethod.paypal: 45,
    WebshopPaymentMethod.credit_card: 25,
    WebshopPaymentMethod.sepa_direct_debit: 20,
    WebshopPaymentMethod.invoice: 10,
}
_CATEGORY_POPULARITY: dict[ProductCategory, float] = {
    ProductCategory.mineral_water: 3.0,
    ProductCategory.soft_drink: 4.0,
    ProductCategory.spritzer: 3.0,
    ProductCategory.craft: 3.5,  # craft over-indexes online vs retail
    ProductCategory.specialty: 3.0,
}
_CATEGORY_SEASON_AMP: dict[ProductCategory, float] = {
    ProductCategory.mineral_water: 0.45,
    ProductCategory.soft_drink: 0.35,
    ProductCategory.spritzer: 0.45,
    ProductCategory.craft: 0.15,
    ProductCategory.specialty: 0.25,
}
_RETURN_RATE = 0.05


class _LineData(NamedTuple):
    product: Product
    cases: int
    unit_price_gross: Decimal
    line_gross: Decimal
    deposit: Decimal


def _seasonality(month: int) -> float:
    return 1.0 + 0.35 * math.cos((month - 7) * math.pi / 6.0)


def _category_factor(category: ProductCategory, month: int) -> float:
    return 1.0 + _CATEGORY_SEASON_AMP[category] * math.cos((month - 7) * math.pi / 6.0)


def generate_webshop_customers(
    n: int = 3000,
    year_range: tuple[int, int] = (2023, 2025),
    seed: int = 42,
) -> list[WebshopCustomer]:
    faker = Faker("de_DE")
    Faker.seed(seed)
    rng = random.Random(seed)

    earliest = date(year_range[0], 1, 1)
    span = (date(year_range[1], 12, 31) - earliest).days

    customers: list[WebshopCustomer] = []
    for i in range(1, n + 1):
        first = faker.first_name()
        last = faker.last_name()
        domain = rng.choice(["gmail.com", "web.de", "gmx.de", "t-online.de", "outlook.de"])
        customers.append(
            WebshopCustomer(
                id=uuid4(),
                customer_ref=f"WC-{i:06d}",
                email=f"{first.lower()}.{last.lower()}{rng.randint(1, 99)}@{domain}",
                first_name=first,
                last_name=last,
                postal_code=faker.postcode(),
                city=faker.city(),
                region=rng.choice(_REGIONS),
                signup_date=earliest + timedelta(days=rng.randint(0, span)),
                marketing_opt_in=rng.random() < 0.45,
            )
        )
    return customers


def _build_lines(
    products: list[Product],
    weights: list[float],
    rng: random.Random,
) -> list[_LineData]:
    n_lines = rng.choices([1, 2, 3, 4], weights=[40, 35, 18, 7], k=1)[0]
    picked = _sample(products, weights, min(n_lines, len(products)), rng)
    rows: list[_LineData] = []
    for product in picked:
        cases = rng.choices([1, 2, 3, 6], weights=[55, 25, 12, 8], k=1)[0]
        markup = Decimal(str(round(rng.uniform(1.50, 1.70), 3)))
        unit_price = (product.list_price_net_eur * _VAT * markup).quantize(Decimal("0.0001"))
        line_gross = (Decimal(cases) * unit_price).quantize(_CENT)
        deposit = (Decimal(cases * product.units_per_case) * product.deposit_eur).quantize(_CENT)
        rows.append(_LineData(product, cases, unit_price, line_gross, deposit))
    return rows


def _sample(
    items: list[Product], weights: list[float], k: int, rng: random.Random
) -> list[Product]:
    pool = list(zip(items, weights, strict=True))
    chosen: list[Product] = []
    for _ in range(k):
        if not pool:
            break
        picks = [p for p, _ in pool]
        wts = [w for _, w in pool]
        product = rng.choices(picks, weights=wts, k=1)[0]
        chosen.append(product)
        pool = [(p, w) for p, w in pool if p.id != product.id]
    return chosen


def _status(ordered_at: datetime, today: date, rng: random.Random) -> WebshopOrderStatus:
    age = (today - ordered_at.date()).days
    if age <= 1:
        return rng.choices(
            [WebshopOrderStatus.placed, WebshopOrderStatus.paid],
            weights=[40, 60],
            k=1,
        )[0]
    if age <= 4:
        return rng.choices(
            [WebshopOrderStatus.paid, WebshopOrderStatus.shipped],
            weights=[30, 70],
            k=1,
        )[0]
    if rng.random() < _RETURN_RATE:
        return WebshopOrderStatus.returned
    return WebshopOrderStatus.delivered


def generate_online_orders(
    customers: list[WebshopCustomer],
    products: list[Product],
    year_range: tuple[int, int] = (2023, 2025),
    today: date = date(2026, 1, 15),
    seed: int = 42,
) -> list[OnlineOrder]:
    rng = random.Random(seed + 1)
    catalogue = [p for p in products if p.active]
    if not customers or not catalogue:
        return []

    payment_methods = list(_PAYMENT_WEIGHTS)
    payment_weights = list(_PAYMENT_WEIGHTS.values())

    month_weights = [_seasonality(m) for m in range(1, 13)]
    monthly_share = [w / sum(month_weights) for w in month_weights]

    orders: list[OnlineOrder] = []
    counter = 0
    for year in range(year_range[0], year_range[1] + 1):
        n_year = int(_BASE_ORDERS_PER_YEAR * _YEAR_GROWTH.get(year, 1.0))
        for month in range(1, 13):
            n_month = round(n_year * monthly_share[month - 1])
            product_weights = [
                _CATEGORY_POPULARITY[p.category] * _category_factor(p.category, month)
                for p in catalogue
            ]
            for _ in range(n_month):
                ordered_at = datetime(
                    year, month, rng.randint(1, 28), rng.randint(7, 23), rng.randint(0, 59)
                )
                if ordered_at.date() > today:
                    continue
                customer = rng.choice(customers)
                if ordered_at.date() < customer.signup_date:
                    continue

                lines_data = _build_lines(catalogue, product_weights, rng)
                if not lines_data:
                    continue

                counter += 1
                gross = sum((r.line_gross for r in lines_data), Decimal("0"))
                deposit = sum((r.deposit for r in lines_data), Decimal("0"))
                net = (gross / _VAT).quantize(_CENT)
                vat = gross - net
                shipping = Decimal("0.00") if gross >= _FREE_SHIPPING_OVER else _SHIPPING_FEE

                order = OnlineOrder(
                    id=uuid4(),
                    order_number=f"WO-{year}-{counter:06d}",
                    webshop_customer_id=customer.id,
                    ordered_at=ordered_at,
                    status=_status(ordered_at, today, rng),
                    payment_method=rng.choices(payment_methods, weights=payment_weights, k=1)[0],
                    total_net_eur=net,
                    total_vat_eur=vat,
                    total_gross_eur=gross,
                    deposit_total_eur=deposit,
                    shipping_eur=shipping,
                )
                order.webshop_customer = customer
                for i, row in enumerate(lines_data, start=1):
                    line = OnlineOrderLine(
                        id=uuid4(),
                        online_order_id=order.id,
                        line_number=i,
                        product_id=row.product.id,
                        quantity_cases=row.cases,
                        unit_price_gross_eur=row.unit_price_gross,
                        line_gross_eur=row.line_gross,
                        deposit_eur=row.deposit,
                    )
                    line.product = row.product
                    order.lines.append(line)
                orders.append(order)

    return orders
