"""Generate the inventory movement ledger and the current stock snapshot.

Movements are posted from the events that already exist, closing the material
loop the rest of the simulation implies:

* goods receipts add raw material,
* production runs consume raw material (per the product BOM) and yield finished
  goods,
* deliveries issue finished goods,
* customer returns add finished goods back.

Because procurement and production volumes are simulated independently, a raw
running balance can dip below zero. To keep on-hand realistic, an opening-stock
adjustment is posted at the start of the window for each item/plant so the
minimum running balance never falls under a safety level. ``StockLevel`` is the
net position as of ``today``.
"""

from __future__ import annotations

import random
from collections import defaultdict
from datetime import date
from decimal import Decimal
from uuid import uuid4

from data.erp.models import (
    CustomerReturn,
    Delivery,
    GoodsReceipt,
    Plant,
    Product,
    ProductComponent,
    ProductionRun,
    RawMaterial,
    StockItemType,
    StockLevel,
    StockMovement,
    StockMovementType,
)

_RM_LOCATION = "RM01"
_FG_LOCATION = "FG01"
_CENT_QTY = Decimal("0.001")


def _key(item_type: StockItemType, item_id, plant_id) -> tuple:
    return (item_type, item_id, plant_id)


def generate_inventory(
    goods_receipts: list[GoodsReceipt],
    production_runs: list[ProductionRun],
    deliveries: list[Delivery],
    products: list[Product],
    raw_materials: list[RawMaterial],
    components: list[ProductComponent],
    plants: list[Plant],
    customer_returns: list[CustomerReturn] | None = None,
    today: date = date(2026, 1, 15),
    seed: int = 42,
) -> tuple[list[StockMovement], list[StockLevel]]:
    """Build stock movements and the resulting per-item/plant stock levels."""
    rng = random.Random(seed + 33)
    product_by_id = {p.id: p for p in products}
    rm_uom = {m.id: m.unit_of_measure for m in raw_materials}
    bom: dict = defaultdict(list)
    for comp in components:
        bom[comp.product_id].append(comp)

    # Each movement is collected as a tuple, numbered after sorting by date.
    raw_moves: list[dict] = []

    def add(item_type, item_id, plant_id, location, mtype, qty, uom, day, ref):
        raw_moves.append({
            "item_type": item_type,
            "item_id": item_id,
            "plant_id": plant_id,
            "location": location,
            "mtype": mtype,
            "qty": Decimal(qty).quantize(_CENT_QTY),
            "uom": uom,
            "day": day,
            "ref": ref,
        })

    # Goods receipts: raw material in. Assign each GR to a plant (random, seeded).
    for gr in goods_receipts:
        plant = rng.choice(plants)
        for line in gr.lines:
            rm_id = line.purchase_order_line.raw_material_id
            add(StockItemType.raw_material, rm_id, plant.id, _RM_LOCATION,
                StockMovementType.goods_receipt, line.quantity_received,
                rm_uom.get(rm_id, "EA"), gr.received_date, gr.gr_number)

    # Production: consume raw per BOM, yield finished goods.
    for run in production_runs:
        product = product_by_id[run.product_id]
        plant_id = run.production_line.plant_id
        produced = run.produced_qty_units
        litres = Decimal(produced) * product.volume_l
        for comp in bom.get(run.product_id, []):
            consumed = (comp.quantity_per_1000l * litres / Decimal(1000))
            if consumed <= 0:
                continue
            add(StockItemType.raw_material, comp.raw_material_id, plant_id, _RM_LOCATION,
                StockMovementType.production_issue, -consumed, comp.unit_of_measure,
                run.started_at.date(), run.run_number)
        add(StockItemType.product, run.product_id, plant_id, _FG_LOCATION,
            StockMovementType.production_receipt, produced, "EA",
            run.started_at.date(), run.run_number)

    # Deliveries: finished goods out.
    for delivery in deliveries:
        for line in delivery.lines:
            add(StockItemType.product, line.product_id, delivery.plant_id, _FG_LOCATION,
                StockMovementType.delivery_issue, -line.quantity_units, "EA",
                delivery.delivery_date, delivery.delivery_number)

    # Returns: finished goods back in (shipped from the customer's serving plant).
    default_plant = plants[0].id
    for ret in customer_returns or []:
        for line in ret.lines:
            add(StockItemType.product, line.product_id, default_plant, _FG_LOCATION,
                StockMovementType.return_receipt, line.quantity_units, "EA",
                ret.return_date, ret.return_number)

    # Opening balances: lift each item/plant so the minimum running balance stays
    # above a safety level. Posted at the window start as an adjustment.
    by_item: dict = defaultdict(list)
    for mv in raw_moves:
        by_item[_key(mv["item_type"], mv["item_id"], mv["plant_id"])].append(mv)

    start_day = min((mv["day"] for mv in raw_moves), default=today)
    openings: list[dict] = []
    for key, moves in by_item.items():
        moves.sort(key=lambda m: m["day"])
        running = Decimal(0)
        lowest = Decimal(0)
        for mv in moves:
            running += mv["qty"]
            lowest = min(lowest, running)
        safety = (abs(lowest) * Decimal("0.05")).quantize(_CENT_QTY)
        opening = (-lowest + safety).quantize(_CENT_QTY)
        if opening > 0:
            item_type, item_id, plant_id = key
            openings.append({
                "item_type": item_type,
                "item_id": item_id,
                "plant_id": plant_id,
                "location": _RM_LOCATION if item_type == StockItemType.raw_material
                else _FG_LOCATION,
                "mtype": StockMovementType.adjustment,
                "qty": opening,
                "uom": moves[0]["uom"],
                "day": start_day,
                "ref": "opening-balance",
            })

    all_moves = openings + raw_moves
    all_moves.sort(key=lambda m: (m["day"], str(m["ref"]), str(m["item_id"])))

    # Materialise movement ORM rows with sequential document numbers.
    movements: list[StockMovement] = []
    counter: dict[int, int] = defaultdict(int)
    for mv in all_moves:
        year = mv["day"].year
        counter[year] += 1
        movements.append(StockMovement(
            id=uuid4(),
            movement_number=f"MV-{year}-{counter[year]:06d}",
            item_type=mv["item_type"],
            raw_material_id=mv["item_id"] if mv["item_type"] == StockItemType.raw_material
            else None,
            product_id=mv["item_id"] if mv["item_type"] == StockItemType.product else None,
            plant_id=mv["plant_id"],
            storage_location=mv["location"],
            movement_type=mv["mtype"],
            posting_date=mv["day"],
            quantity=mv["qty"],
            unit_of_measure=mv["uom"],
            reference=mv["ref"],
        ))

    # Snapshot: net on-hand per item/plant.
    totals: dict = defaultdict(lambda: Decimal(0))
    meta: dict = {}
    for mv in all_moves:
        k = _key(mv["item_type"], mv["item_id"], mv["plant_id"])
        totals[k] += mv["qty"]
        meta[k] = (mv["location"], mv["uom"])

    levels: list[StockLevel] = []
    for key, qty in totals.items():
        item_type, item_id, plant_id = key
        location, uom = meta[key]
        levels.append(StockLevel(
            id=uuid4(),
            item_type=item_type,
            raw_material_id=item_id if item_type == StockItemType.raw_material else None,
            product_id=item_id if item_type == StockItemType.product else None,
            plant_id=plant_id,
            storage_location=location,
            quantity_on_hand=qty.quantize(_CENT_QTY),
            unit_of_measure=uom,
            as_of_date=today,
        ))

    return movements, levels
