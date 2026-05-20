"""Generate purchase orders against the master data.

Multi-year span, seasonal weighting (peak around May/June), YoY growth.
"""

from __future__ import annotations

import math
import random
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from data.generators._market_helpers import (
    materials_for_supplier,
    pick_quantity,
    pick_unit_price,
    supplier_spec,
)
from data.models import (
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    RawMaterial,
    Supplier,
)

_DEFAULT_VAT = Decimal("19.00")
_VAT_FACTOR = Decimal("0.19")

# Base POs per year before growth and seasonality.
_BASE_POS_PER_YEAR = 600

# Year-over-year growth (Brunnstein gaining market share).
_YEAR_GROWTH: dict[int, float] = {2023: 1.00, 2024: 1.15, 2025: 1.30}


def _seasonality(month: int) -> float:
    """Cosine peak at May/June, trough at Nov/Dec. Returns ~0.6 to ~1.4."""
    return 1.0 + 0.4 * math.cos((month - 5.5) * math.pi / 6.0)


def _supplier_weight(supplier: Supplier) -> float:
    """Rough Pareto: a handful of large suppliers carry most volume."""
    name = supplier.name
    if "AG" in name:
        return 4.0
    if "GmbH" in name:
        return 2.0
    return 1.0  # KG, OHG, eG


def _resolve_status(order_date: date, today: date, rng: random.Random) -> PurchaseOrderStatus:
    age_days = (today - order_date).days
    if age_days > 90:
        # Old POs: nearly all closed, a sliver cancelled
        return rng.choices(
            [PurchaseOrderStatus.closed, PurchaseOrderStatus.cancelled],
            weights=[98, 2],
            k=1,
        )[0]
    if age_days > 30:
        return rng.choices(
            [PurchaseOrderStatus.closed, PurchaseOrderStatus.partial, PurchaseOrderStatus.cancelled],
            weights=[70, 25, 5],
            k=1,
        )[0]
    return rng.choices(
        [PurchaseOrderStatus.open, PurchaseOrderStatus.partial, PurchaseOrderStatus.cancelled],
        weights=[55, 40, 5],
        k=1,
    )[0]


def _build_lines(
    materials: list[RawMaterial],
    rng: random.Random,
) -> list[tuple[RawMaterial, Decimal, Decimal, Decimal, Decimal, Decimal]]:
    """Return list of (material, quantity, unit_price, line_net, line_vat, line_gross)."""
    n_lines = rng.choices([1, 2, 3, 4, 5, 6, 7, 8], weights=[5, 18, 25, 22, 14, 9, 5, 2], k=1)[0]
    picked = rng.sample(materials, min(n_lines, len(materials)))
    rows = []
    for m in picked:
        qty = pick_quantity(m, rng)
        price = pick_unit_price(m, rng)
        net = (qty * price).quantize(Decimal("0.01"))
        vat = (net * _VAT_FACTOR).quantize(Decimal("0.01"))
        gross = net + vat
        rows.append((m, qty, price, net, vat, gross))
    return rows


def generate_purchase_orders(
    suppliers: list[Supplier],
    materials: list[RawMaterial],
    year_range: tuple[int, int] = (2023, 2025),
    today: date = date(2026, 1, 15),
    seed: int = 42,
) -> list[PurchaseOrder]:
    rng = random.Random(seed)

    # Pre-build per-supplier material catalogues. Skip suppliers we can't source from.
    eligible: list[tuple[Supplier, list[RawMaterial]]] = []
    for s in suppliers:
        if not s.active:
            continue
        if supplier_spec(s) == "logistics":
            continue
        cat = materials_for_supplier(s, materials)
        if cat:
            eligible.append((s, cat))

    if not eligible:
        return []

    weights = [_supplier_weight(s) for s, _ in eligible]

    orders: list[PurchaseOrder] = []
    po_counter = 0
    start_year, end_year = year_range
    for year in range(start_year, end_year + 1):
        n_year = int(_BASE_POS_PER_YEAR * _YEAR_GROWTH.get(year, 1.0))
        # Distribute by seasonality across months.
        month_weights = [_seasonality(m) for m in range(1, 13)]
        for month in range(1, 13):
            share = month_weights[month - 1] / sum(month_weights)
            n_month = round(n_year * share)
            for _ in range(n_month):
                po_counter += 1
                supplier, supplier_materials = rng.choices(eligible, weights=weights, k=1)[0]
                day = rng.randint(1, 28)
                order_date = date(year, month, day)
                requested = order_date + timedelta(days=rng.randint(7, 35))

                lines_data = _build_lines(supplier_materials, rng)
                if not lines_data:
                    continue
                total_net = sum((row[3] for row in lines_data), Decimal("0"))
                total_vat = sum((row[4] for row in lines_data), Decimal("0"))
                total_gross = sum((row[5] for row in lines_data), Decimal("0"))

                status = _resolve_status(order_date, today, rng)

                po = PurchaseOrder(
                    id=uuid4(),
                    po_number=f"PO-{year}-{po_counter:06d}",
                    supplier_id=supplier.id,
                    order_date=order_date,
                    requested_delivery_date=requested,
                    status=status,
                    total_net_eur=total_net,
                    total_vat_eur=total_vat,
                    total_gross_eur=total_gross,
                    notes=None,
                )
                po.supplier = supplier
                for i, (m, qty, price, net, vat, gross) in enumerate(lines_data, start=1):
                    line = PurchaseOrderLine(
                        id=uuid4(),
                        purchase_order_id=po.id,
                        line_number=i,
                        raw_material_id=m.id,
                        description=m.name,
                        quantity=qty,
                        unit_price_net_eur=price,
                        vat_rate_pct=_DEFAULT_VAT,
                        line_net_eur=net,
                        line_vat_eur=vat,
                        line_gross_eur=gross,
                    )
                    line.raw_material = m
                    po.lines.append(line)
                orders.append(po)

    return orders
