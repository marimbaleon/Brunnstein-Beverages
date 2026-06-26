"""Generate the sales and accounts-receivable document flow.

Demand is simulated per month from category popularity, a summer-peaked
seasonal factor (beverage sales swing hard with the weather), and
year-over-year growth. Each sales order spawns the downstream chain a healthy
order-to-cash process produces: delivery, invoice, incoming payment. The chain
is truncated at ``today`` so recent orders are still in flight and a realistic
share of invoices are open or overdue.

The generator returns the four document levels separately; line items are
attached to their parents via relationships and load by cascade.
"""

from __future__ import annotations

import math
import random
from datetime import date, timedelta
from decimal import Decimal
from typing import NamedTuple
from uuid import uuid4

from data.erp.models import (
    Customer,
    CustomerChannel,
    CustomerInvoice,
    CustomerInvoiceLine,
    CustomerInvoiceStatus,
    Delivery,
    DeliveryLine,
    DeliveryStatus,
    PaymentMethod,
    PaymentReceived,
    Plant,
    Product,
    ProductCategory,
    SalesOrder,
    SalesOrderLine,
    SalesOrderStatus,
)

_VAT_FACTOR = Decimal("0.19")
_CENT = Decimal("0.01")

_BASE_ORDERS_PER_YEAR = 2000
_YEAR_GROWTH: dict[int, float] = {2023: 1.00, 2024: 1.15, 2025: 1.30}

# How likely a customer of each channel is to be the one placing a given order,
# and the commercial terms that channel gets.
_CHANNEL_ORDER_WEIGHT: dict[CustomerChannel, float] = {
    CustomerChannel.retail_chain: 8.0,
    CustomerChannel.wholesaler: 6.0,
    CustomerChannel.convenience: 3.0,
    CustomerChannel.gastronomy: 1.5,
}
_CHANNEL_DISCOUNT: dict[CustomerChannel, str] = {
    CustomerChannel.retail_chain: "0.70",
    CustomerChannel.wholesaler: "0.76",
    CustomerChannel.convenience: "0.86",
    CustomerChannel.gastronomy: "0.92",
}
_CHANNEL_LINES: dict[CustomerChannel, tuple[int, int]] = {
    CustomerChannel.retail_chain: (4, 10),
    CustomerChannel.wholesaler: (4, 10),
    CustomerChannel.convenience: (2, 6),
    CustomerChannel.gastronomy: (2, 6),
}
_CHANNEL_CASES: dict[CustomerChannel, tuple[int, int]] = {
    CustomerChannel.retail_chain: (20, 120),
    CustomerChannel.wholesaler: (30, 200),
    CustomerChannel.convenience: (3, 15),
    CustomerChannel.gastronomy: (1, 8),
}
_CHANNEL_LEAD_DAYS: dict[CustomerChannel, tuple[int, int]] = {
    CustomerChannel.retail_chain: (2, 5),
    CustomerChannel.wholesaler: (2, 5),
    CustomerChannel.convenience: (1, 3),
    CustomerChannel.gastronomy: (1, 3),
}

# Baseline popularity and how strongly each category swings with the season.
_CATEGORY_POPULARITY: dict[ProductCategory, float] = {
    ProductCategory.mineral_water: 5.0,
    ProductCategory.soft_drink: 4.0,
    ProductCategory.spritzer: 2.5,
    ProductCategory.craft: 1.2,
    ProductCategory.specialty: 1.5,
}
_CATEGORY_SEASON_AMP: dict[ProductCategory, float] = {
    ProductCategory.mineral_water: 0.50,
    ProductCategory.soft_drink: 0.35,
    ProductCategory.spritzer: 0.45,
    ProductCategory.craft: 0.15,
    ProductCategory.specialty: 0.25,
}

# Payment behaviour buckets. The rest (1 - paid_on_time - paid_late) of due
# invoices stay open, feeding the dunning / cash-application use cases.
_PAID_ON_TIME = 0.70
_PAID_LATE = 0.18
_CANCEL_RATE = 0.02


class _LineData(NamedTuple):
    product: Product
    quantity: Decimal
    unit_price: Decimal
    net: Decimal
    vat: Decimal
    gross: Decimal
    deposit: Decimal


def _seasonality(month: int) -> float:
    """Order-volume seasonality: cosine peak in July, trough in January."""
    return 1.0 + 0.35 * math.cos((month - 7) * math.pi / 6.0)


def _category_factor(category: ProductCategory, month: int) -> float:
    amp = _CATEGORY_SEASON_AMP[category]
    return 1.0 + amp * math.cos((month - 7) * math.pi / 6.0)


def _plant_for(customer: Customer, plants: list[Plant], rng: random.Random) -> Plant:
    """Ship southern customers from Bad Tölz (1000), the rest from Ulm (2000)."""
    by_code = {p.plant_code: p for p in plants}
    if customer.region == "Bayern" and "1000" in by_code:
        return by_code["1000"]
    if "2000" in by_code:
        return by_code["2000"]
    return rng.choice(plants)


def _remittance(invoice_number: str, customer: Customer, rng: random.Random) -> str:
    """Payment reference as printed on the bank statement.

    Deliberately varied: some references quote the invoice number cleanly,
    some bury it, some omit it entirely. That spread is the matching problem
    the cash-application use case has to solve.
    """
    roll = rng.random()
    if roll < 0.55:
        return f"Rechnung {invoice_number}"
    if roll < 0.75:
        return f"{invoice_number} {customer.name[:30]}"
    if roll < 0.90:
        return f"RG {invoice_number.replace('AR-', '')} Zahlung"
    return f"Zahlung Kundennr {customer.customer_number}"


def _build_lines(
    products: list[Product],
    weights: list[float],
    channel: CustomerChannel,
    rng: random.Random,
) -> list[_LineData]:
    lo, hi = _CHANNEL_LINES[channel]
    n_lines = rng.randint(lo, hi)
    discount = Decimal(_CHANNEL_DISCOUNT[channel])
    case_lo, case_hi = _CHANNEL_CASES[channel]

    picked = _weighted_sample(products, weights, min(n_lines, len(products)), rng)
    rows: list[_LineData] = []
    for product in picked:
        cases = rng.randint(case_lo, case_hi)
        qty = Decimal(cases * product.units_per_case)
        unit_price = (product.list_price_net_eur * discount).quantize(Decimal("0.0001"))
        net = (qty * unit_price).quantize(_CENT)
        vat = (net * _VAT_FACTOR).quantize(_CENT)
        deposit = (qty * product.deposit_eur).quantize(_CENT)
        rows.append(_LineData(product, qty, unit_price, net, vat, net + vat, deposit))
    return rows


def _weighted_sample(
    items: list[Product], weights: list[float], k: int, rng: random.Random
) -> list[Product]:
    """Sample k distinct products with probability proportional to weight."""
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


def generate_sales(
    customers: list[Customer],
    products: list[Product],
    plants: list[Plant],
    year_range: tuple[int, int] = (2023, 2025),
    today: date = date(2026, 1, 15),
    seed: int = 42,
) -> tuple[list[SalesOrder], list[Delivery], list[CustomerInvoice], list[PaymentReceived]]:
    rng = random.Random(seed)

    active_customers = [c for c in customers if c.active]
    active_products = [p for p in products if p.active]
    if not active_customers or not active_products or not plants:
        return [], [], [], []

    customer_weights = [_CHANNEL_ORDER_WEIGHT[c.channel] for c in active_customers]

    month_weights = [_seasonality(m) for m in range(1, 13)]
    monthly_share = [w / sum(month_weights) for w in month_weights]

    orders: list[SalesOrder] = []
    deliveries: list[Delivery] = []
    invoices: list[CustomerInvoice] = []
    payments: list[PaymentReceived] = []

    counters = {"so": 0, "dn": 0, "ar": 0, "pay": 0}
    start_year, end_year = year_range

    for year in range(start_year, end_year + 1):
        n_year = int(_BASE_ORDERS_PER_YEAR * _YEAR_GROWTH.get(year, 1.0))
        # Product weights shift month to month with the season.
        for month in range(1, 13):
            n_month = round(n_year * monthly_share[month - 1])
            product_weights = [
                _CATEGORY_POPULARITY[p.category] * _category_factor(p.category, month)
                for p in active_products
            ]
            for _ in range(n_month):
                customer = rng.choices(active_customers, weights=customer_weights, k=1)[0]
                order_date = date(year, month, rng.randint(1, 28))
                if order_date < customer.onboarded_date or order_date > today:
                    continue

                lines_data = _build_lines(active_products, product_weights, customer.channel, rng)
                if not lines_data:
                    continue

                counters["so"] += 1
                so = _assemble_order(year, counters, customer, order_date, lines_data)
                orders.append(so)

                if rng.random() < _CANCEL_RATE and (today - order_date).days < 20:
                    so.status = SalesOrderStatus.cancelled
                    continue

                _flow(
                    so, lines_data, customer, plants, today, year, counters, rng,
                    deliveries, invoices, payments,
                )

    return orders, deliveries, invoices, payments


def _assemble_order(
    year: int,
    counters: dict[str, int],
    customer: Customer,
    order_date: date,
    lines_data: list[_LineData],
) -> SalesOrder:
    total_net = sum((r.net for r in lines_data), Decimal("0"))
    total_vat = sum((r.vat for r in lines_data), Decimal("0"))
    total_gross = sum((r.gross for r in lines_data), Decimal("0"))
    total_deposit = sum((r.deposit for r in lines_data), Decimal("0"))
    lead = (order_date + timedelta(days=4))

    so = SalesOrder(
        id=uuid4(),
        sales_order_number=f"SO-{year}-{counters['so']:06d}",
        customer_id=customer.id,
        order_date=order_date,
        requested_delivery_date=lead,
        status=SalesOrderStatus.open,
        total_net_eur=total_net,
        total_vat_eur=total_vat,
        total_gross_eur=total_gross,
        deposit_total_eur=total_deposit,
    )
    so.customer = customer
    for i, row in enumerate(lines_data, start=1):
        line = SalesOrderLine(
            id=uuid4(),
            sales_order_id=so.id,
            line_number=i,
            product_id=row.product.id,
            quantity_units=row.quantity,
            unit_price_net_eur=row.unit_price,
            vat_rate_pct=Decimal("19.00"),
            line_net_eur=row.net,
            line_vat_eur=row.vat,
            line_gross_eur=row.gross,
            deposit_eur=row.deposit,
        )
        line.product = row.product
        so.lines.append(line)
    return so


def _flow(
    so: SalesOrder,
    lines_data: list[_LineData],
    customer: Customer,
    plants: list[Plant],
    today: date,
    year: int,
    counters: dict[str, int],
    rng: random.Random,
    deliveries: list[Delivery],
    invoices: list[CustomerInvoice],
    payments: list[PaymentReceived],
) -> None:
    """Walk one order through delivery, invoice and payment, stopping at today."""
    lead_lo, lead_hi = _CHANNEL_LEAD_DAYS[customer.channel]
    delivery_date = so.order_date + timedelta(days=rng.randint(lead_lo, lead_hi))
    if delivery_date > today:
        so.status = SalesOrderStatus.confirmed
        return

    so.status = SalesOrderStatus.delivered
    counters["dn"] += 1
    plant = _plant_for(customer, plants, rng)
    delivery = Delivery(
        id=uuid4(),
        delivery_number=f"DN-{year}-{counters['dn']:06d}",
        sales_order_id=so.id,
        plant_id=plant.id,
        delivery_date=delivery_date,
        status=DeliveryStatus.delivered,
    )
    delivery.sales_order = so
    for i, (so_line, row) in enumerate(zip(so.lines, lines_data, strict=True), start=1):
        dl = DeliveryLine(
            id=uuid4(),
            delivery_id=delivery.id,
            line_number=i,
            sales_order_line_id=so_line.id,
            product_id=row.product.id,
            quantity_units=row.quantity,
        )
        dl.sales_order_line = so_line
        dl.product = row.product
        delivery.lines.append(dl)
    deliveries.append(delivery)

    invoice_date = delivery_date + timedelta(days=rng.randint(0, 2))
    if invoice_date > today:
        return

    so.status = SalesOrderStatus.invoiced
    counters["ar"] += 1
    due_date = invoice_date + timedelta(days=customer.payment_terms_days)
    amount_due = so.total_gross_eur + so.deposit_total_eur
    invoice = CustomerInvoice(
        id=uuid4(),
        customer_invoice_number=f"AR-{year}-{counters['ar']:06d}",
        customer_id=customer.id,
        sales_order_id=so.id,
        delivery_id=delivery.id,
        invoice_date=invoice_date,
        due_date=due_date,
        status=CustomerInvoiceStatus.open,
        total_net_eur=so.total_net_eur,
        total_vat_eur=so.total_vat_eur,
        total_gross_eur=so.total_gross_eur,
        deposit_total_eur=so.deposit_total_eur,
        amount_due_eur=amount_due,
    )
    invoice.customer = customer
    invoice.sales_order = so
    invoice.delivery = delivery
    for i, (dl, row) in enumerate(zip(delivery.lines, lines_data, strict=True), start=1):
        il = CustomerInvoiceLine(
            id=uuid4(),
            customer_invoice_id=invoice.id,
            line_number=i,
            product_id=row.product.id,
            delivery_line_id=dl.id,
            quantity_units=row.quantity,
            unit_price_net_eur=row.unit_price,
            vat_rate_pct=Decimal("19.00"),
            line_net_eur=row.net,
            line_vat_eur=row.vat,
            line_gross_eur=row.gross,
            deposit_eur=row.deposit,
        )
        il.product = row.product
        il.delivery_line = dl
        invoice.lines.append(il)
    invoices.append(invoice)

    _settle(invoice, customer, today, year, counters, rng, payments)


def _settle(
    invoice: CustomerInvoice,
    customer: Customer,
    today: date,
    year: int,
    counters: dict[str, int],
    rng: random.Random,
    payments: list[PaymentReceived],
) -> None:
    """Decide whether and when this invoice gets paid."""
    roll = rng.random()
    if roll < _PAID_ON_TIME:
        payment_date = invoice.due_date - timedelta(days=rng.randint(0, 5))
    elif roll < _PAID_ON_TIME + _PAID_LATE:
        payment_date = invoice.due_date + timedelta(days=rng.randint(3, 25))
    else:
        payment_date = None  # stays unpaid

    if payment_date is None or payment_date > today:
        invoice.status = (
            CustomerInvoiceStatus.overdue
            if invoice.due_date < today
            else CustomerInvoiceStatus.open
        )
        return

    invoice.status = CustomerInvoiceStatus.paid
    counters["pay"] += 1
    method = (
        PaymentMethod.direct_debit
        if customer.channel == CustomerChannel.gastronomy and rng.random() < 0.4
        else PaymentMethod.bank_transfer
    )
    payments.append(
        PaymentReceived(
            id=uuid4(),
            payment_number=f"PAY-{year}-{counters['pay']:06d}",
            customer_invoice_id=invoice.id,
            customer_id=customer.id,
            payment_date=payment_date,
            amount_eur=invoice.amount_due_eur,
            method=method,
            remittance_info=_remittance(invoice.customer_invoice_number, customer, rng),
        )
    )
