"""Generate purchase orders against the master data.

Multi-year span, seasonal weighting (peak around May/June), YoY growth.
"""

from __future__ import annotations

import math
import random
from datetime import date, timedelta
from decimal import Decimal
from typing import NamedTuple
from uuid import uuid4

from data.erp.generators._market_helpers import (
    materials_for_supplier,
    pick_quantity,
    pick_unit_price,
    supplier_spec,
)
from data.erp.models import (
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


class _PoLineData(NamedTuple):
    material: RawMaterial
    quantity: Decimal
    unit_price: Decimal
    net: Decimal
    vat: Decimal
    gross: Decimal


# PO status distribution by age. Weights are tuned to produce roughly the
# mix a healthy procurement function shows at any given point: most old
# orders are closed, recent ones are still in flight.
_STATUS_WEIGHTS_OLD = {
    PurchaseOrderStatus.closed: 98,
    PurchaseOrderStatus.cancelled: 2,
}
_STATUS_WEIGHTS_MIDDLE = {
    PurchaseOrderStatus.closed: 70,
    PurchaseOrderStatus.partial: 25,
    PurchaseOrderStatus.cancelled: 5,
}
_STATUS_WEIGHTS_RECENT = {
    PurchaseOrderStatus.open: 55,
    PurchaseOrderStatus.partial: 40,
    PurchaseOrderStatus.cancelled: 5,
}

# Line-count distribution: typical PO has 2-4 lines, the long tail thins out.
_LINE_COUNT_WEIGHTS = [5, 18, 25, 22, 14, 9, 5, 2]  # for n_lines = 1..8


def _resolve_status(order_date: date, today: date, rng: random.Random) -> PurchaseOrderStatus:
    age_days = (today - order_date).days
    if age_days > 90:
        weights = _STATUS_WEIGHTS_OLD
    elif age_days > 30:
        weights = _STATUS_WEIGHTS_MIDDLE
    else:
        weights = _STATUS_WEIGHTS_RECENT
    return rng.choices(list(weights.keys()), weights=list(weights.values()), k=1)[0]


def _build_lines(
    materials: list[RawMaterial],
    rng: random.Random,
) -> list[_PoLineData]:
    n_lines = rng.choices(
        list(range(1, len(_LINE_COUNT_WEIGHTS) + 1)),
        weights=_LINE_COUNT_WEIGHTS,
        k=1,
    )[0]
    picked = rng.sample(materials, min(n_lines, len(materials)))
    rows: list[_PoLineData] = []
    for material in picked:
        qty = pick_quantity(material, rng)
        price = pick_unit_price(material, rng)
        net = (qty * price).quantize(Decimal("0.01"))
        vat = (net * _VAT_FACTOR).quantize(Decimal("0.01"))
        rows.append(_PoLineData(
            material=material,
            quantity=qty,
            unit_price=price,
            net=net,
            vat=vat,
            gross=net + vat,
        ))
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

    # Seasonality is the same shape every year; compute once.
    month_weights = [_seasonality(m) for m in range(1, 13)]
    monthly_share = [w / sum(month_weights) for w in month_weights]

    orders: list[PurchaseOrder] = []
    po_counter = 0
    start_year, end_year = year_range
    for year in range(start_year, end_year + 1):
        n_year = int(_BASE_POS_PER_YEAR * _YEAR_GROWTH.get(year, 1.0))
        for month in range(1, 13):
            n_month = round(n_year * monthly_share[month - 1])
            for _ in range(n_month):
                po_counter += 1
                supplier, supplier_materials = rng.choices(eligible, weights=weights, k=1)[0]
                day = rng.randint(1, 28)
                order_date = date(year, month, day)
                requested = order_date + timedelta(days=rng.randint(7, 35))

                lines_data = _build_lines(supplier_materials, rng)
                if not lines_data:
                    po_counter -= 1  # leave the counter dense for the next iteration
                    continue
                total_net = sum((row.net for row in lines_data), Decimal("0"))
                total_vat = sum((row.vat for row in lines_data), Decimal("0"))
                total_gross = sum((row.gross for row in lines_data), Decimal("0"))

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
                for line_number, row in enumerate(lines_data, start=1):
                    line = PurchaseOrderLine(
                        id=uuid4(),
                        purchase_order_id=po.id,
                        line_number=line_number,
                        raw_material_id=row.material.id,
                        description=row.material.name,
                        quantity=row.quantity,
                        unit_price_net_eur=row.unit_price,
                        vat_rate_pct=_DEFAULT_VAT,
                        line_net_eur=row.net,
                        line_vat_eur=row.vat,
                        line_gross_eur=row.gross,
                    )
                    line.raw_material = row.material
                    po.lines.append(line)
                orders.append(po)

    return orders
