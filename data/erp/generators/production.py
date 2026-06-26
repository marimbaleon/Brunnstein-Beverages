"""Generate production runs, quality checks and maintenance orders (PP/QM/PM).

Production is build-to-stock: each month a product is filled in roughly the
quantity the sales and webshop side actually consumed that month, on a line
whose type matches the product's container (glass / PET / can). A run is one
batch and carries the lot code printed on the bottle, so a defective batch can
later be traced from a customer complaint back to the line and shift that made
it.

Quality checks sample each run against fill-volume, carbonation, sugar and pH
tolerances. Most pass; a small share of runs are deliberately off-spec and
produce a failing check — those batches are the ground truth the complaint and
returns use cases hang off.

Maintenance orders capture line downtime. Preventive orders recur on a fixed
interval; corrective orders mark unplanned failures. The IoT telemetry written
to the bronze layer drifts in the hours before each corrective order, so the
predictive-maintenance use case has a signal to find.

The chain is truncated at ``today`` (consistent with the sales generator): no
run starts in the future.
"""

from __future__ import annotations

import random
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from uuid import uuid4

from data.erp.models import (
    MaintenanceOrder,
    MaintenanceType,
    OnlineOrder,
    Product,
    ProductCategory,
    ProductionLine,
    ProductionLineType,
    ProductionRun,
    ProductionRunStatus,
    QualityCheck,
    QualityResult,
    SalesOrder,
)

# Which line type fills which container.
_CONTAINER_LINE_TYPE = {
    "glass_returnable": ProductionLineType.glass,
    "glass_oneway": ProductionLineType.glass,
    "pet": ProductionLineType.pet,
    "can": ProductionLineType.can,
}

# Build a little ahead of pure demand: safety stock plus expected fill losses.
_DEMAND_BUFFER = 1.08

# Effective output is well below the rated speed (changeovers, CIP, micro-stops).
_OEE_RANGE = (0.58, 0.82)

# Three-shift model; a run is anchored to a shift start.
_SHIFT_STARTS = (time(6, 0), time(14, 0), time(22, 0))

# Share of runs that are off-spec (a failing quality check) and aborted early.
_DEFECT_RATE = 0.03
_ABORT_RATE = 0.012

# Maintenance cadence and downtime envelopes (minutes).
_PREVENTIVE_INTERVAL_DAYS = (42, 56)
_PREVENTIVE_DOWNTIME = (60, 180)
_CORRECTIVE_PER_LINE_PER_YEAR = (2, 5)
_CORRECTIVE_DOWNTIME = (120, 600)

_CORRECTIVE_FAULTS = [
    "Füllerventil undicht, Dichtung getauscht",
    "Verschließer-Drehmoment außerhalb Toleranz, Nachjustage",
    "Etikettieraggregat Stau, Spendekopf gereinigt",
    "Antriebsmotor Transportband Lagerschaden, Motor getauscht",
    "Inspektor Falschausschleusung, Sensor neu kalibriert",
    "Pneumatik Druckabfall, Leitung erneuert",
    "Förderband Kettenriss, Kette ersetzt",
]
_PREVENTIVE_TASKS = [
    "Planwartung: Schmierung, Sichtprüfung, Verschleißteile",
    "Vorbeugende Instandhaltung Füller und Verschließer",
    "Quartalswartung Etikettierer und Inspektor",
]


def _is_carbonated(product: Product) -> bool:
    name = product.name.lower()
    if "still" in name or "eistee" in name:
        return False
    if product.category == ProductCategory.mineral_water:
        return "medium" in name or "classic" in name
    return True


def _has_sugar(product: Product) -> bool:
    return product.category in (
        ProductCategory.soft_drink,
        ProductCategory.spritzer,
        ProductCategory.specialty,
    )


def _monthly_demand(
    sales_orders: list[SalesOrder],
    online_orders: list[OnlineOrder],
    products: list[Product],
) -> dict[tuple, int]:
    """Units consumed per (product_id, year, month) across B2B and webshop sales."""
    units_per_case = {p.id: p.units_per_case for p in products}
    demand: dict[tuple, int] = defaultdict(int)

    for so in sales_orders:
        key_ym = (so.order_date.year, so.order_date.month)
        for line in so.lines:
            demand[(line.product_id, *key_ym)] += int(line.quantity_units)

    for oo in online_orders:
        ordered = oo.ordered_at
        key_ym = (ordered.year, ordered.month)
        for line in oo.lines:
            demand[(line.product_id, *key_ym)] += (
                line.quantity_cases * units_per_case[line.product_id]
            )

    return demand


def _lines_for(product: Product, lines: list[ProductionLine]) -> list[ProductionLine]:
    target = _CONTAINER_LINE_TYPE.get(product.container_type.value)
    # active defaults to True at the DB level; unsaved instances leave it None.
    return [ln for ln in lines if ln.active is not False and ln.line_type == target]


def _measure(
    rng: random.Random,
    target: float,
    tol_pct: float,
    *,
    defective: bool,
) -> tuple[Decimal, Decimal, Decimal, Decimal, QualityResult]:
    """One measurement around a target, with tolerance band and pass/fail verdict."""
    lower = target * (1 - tol_pct)
    upper = target * (1 + tol_pct)
    if defective:
        # Push clearly outside the band, on a random side.
        value = (
            upper * rng.uniform(1.01, 1.06)
            if rng.random() < 0.5
            else lower * rng.uniform(0.94, 0.99)
        )
    else:
        # Normal process spread, occasionally grazing the edge (warning).
        spread = tol_pct * (0.9 if rng.random() < 0.08 else 0.45)
        value = target * (1 + rng.uniform(-spread, spread))

    if value < lower or value > upper:
        result = QualityResult.fail
    elif value < target * (1 - tol_pct * 0.8) or value > target * (1 + tol_pct * 0.8):
        result = QualityResult.warning
    else:
        result = QualityResult.pass_

    q = Decimal("0.001")
    return (
        Decimal(str(value)).quantize(q),
        Decimal(str(target)).quantize(q),
        Decimal(str(lower)).quantize(q),
        Decimal(str(upper)).quantize(q),
        result,
    )


def _quality_checks(
    run: ProductionRun,
    product: Product,
    rng: random.Random,
    *,
    defective: bool,
) -> list[QualityCheck]:
    """Sample the run against the parameters relevant to this product."""
    duration = run.ended_at - run.started_at
    params: list[tuple[str, float, float]] = [
        ("fill_volume_ml", float(product.volume_l) * 1000, 0.015),
        ("ph", 3.4 if _has_sugar(product) else 6.8, 0.05),
    ]
    if _is_carbonated(product):
        params.append(("co2_g_per_l", 7.5, 0.06))
    if _has_sugar(product):
        params.append(("brix", 10.5, 0.04))

    # One parameter carries the defect; the rest measure clean.
    bad_param = rng.choice([p[0] for p in params]) if defective else None

    checks: list[QualityCheck] = []
    for parameter, target, tol in params:
        n_samples = rng.randint(1, 3)
        for _ in range(n_samples):
            offset = timedelta(seconds=rng.randint(0, max(int(duration.total_seconds()), 1)))
            value, tgt, lo, hi, result = _measure(
                rng, target, tol, defective=defective and parameter == bad_param
            )
            checks.append(
                QualityCheck(
                    id=uuid4(),
                    production_run_id=run.id,
                    checked_at=run.started_at + offset,
                    parameter=parameter,
                    measured_value=value,
                    target_value=tgt,
                    lower_tol=lo,
                    upper_tol=hi,
                    result=result,
                )
            )
    return checks


def _maintenance_orders(
    lines: list[ProductionLine],
    year_range: tuple[int, int],
    today: date,
    rng: random.Random,
) -> list[MaintenanceOrder]:
    start = date(year_range[0], 1, 1)
    end = min(date(year_range[1], 12, 31), today)
    orders: list[MaintenanceOrder] = []
    counter = 0

    for line in lines:
        if line.active is False:
            continue

        # Preventive: recurring from the start of the window.
        cursor = max(start, line.commissioned_date)
        while cursor <= end:
            step = rng.randint(*_PREVENTIVE_INTERVAL_DAYS)
            cursor += timedelta(days=step)
            if cursor > end:
                break
            counter += 1
            reported = datetime.combine(cursor, time(rng.randint(7, 16), rng.randint(0, 59)))
            downtime = rng.randint(*_PREVENTIVE_DOWNTIME)
            orders.append(
                MaintenanceOrder(
                    id=uuid4(),
                    order_number=f"MN-{cursor.year}-{counter:06d}",
                    production_line_id=line.id,
                    type=MaintenanceType.preventive,
                    reported_at=reported,
                    completed_at=reported + timedelta(minutes=downtime),
                    downtime_minutes=downtime,
                    description=rng.choice(_PREVENTIVE_TASKS),
                )
            )

        # Corrective: unplanned failures scattered across each year.
        for year in range(year_range[0], year_range[1] + 1):
            y_start = max(date(year, 1, 1), line.commissioned_date)
            y_end = min(date(year, 12, 31), end)
            if y_start >= y_end:
                continue
            span = (y_end - y_start).days
            for _ in range(rng.randint(*_CORRECTIVE_PER_LINE_PER_YEAR)):
                day = y_start + timedelta(days=rng.randint(0, span))
                counter += 1
                reported = datetime.combine(day, time(rng.randint(0, 23), rng.randint(0, 59)))
                downtime = rng.randint(*_CORRECTIVE_DOWNTIME)
                orders.append(
                    MaintenanceOrder(
                        id=uuid4(),
                        order_number=f"MN-{year}-{counter:06d}",
                        production_line_id=line.id,
                        type=MaintenanceType.corrective,
                        reported_at=reported,
                        completed_at=reported + timedelta(minutes=downtime),
                        downtime_minutes=downtime,
                        description=rng.choice(_CORRECTIVE_FAULTS),
                    )
                )

    orders.sort(key=lambda o: o.reported_at)
    return orders


def generate_production(
    products: list[Product],
    lines: list[ProductionLine],
    sales_orders: list[SalesOrder],
    online_orders: list[OnlineOrder],
    year_range: tuple[int, int] = (2023, 2025),
    today: date = date(2026, 1, 15),
    seed: int = 42,
) -> tuple[list[ProductionRun], list[MaintenanceOrder]]:
    """Build production runs (with quality checks) and maintenance orders.

    Run quantities track realised demand per product and month; line choice
    follows the product's container type. Quality checks and the defective-batch
    flag are attached to each run via the ``quality_checks`` relationship.
    """
    rng = random.Random(seed + 5)
    product_by_id = {p.id: p for p in products}
    demand = _monthly_demand(sales_orders, online_orders, products)

    runs: list[ProductionRun] = []
    run_counter: dict[int, int] = defaultdict(int)
    daily_batch_seq: dict[tuple, int] = defaultdict(int)

    # Deterministic order: by product material number (stable across runs, unlike
    # the random UUID), then chronological month.
    for (product_id, year, month), units in sorted(
        demand.items(),
        key=lambda kv: (product_by_id[kv[0][0]].material_number, kv[0][1], kv[0][2]),
    ):
        if units <= 0:
            continue
        product = product_by_id[product_id]
        candidates = _lines_for(product, lines)
        if not candidates:
            continue

        target_units = int(units * _DEMAND_BUFFER)
        weights = [ln.nominal_speed_bph for ln in candidates]

        # Size runs at roughly one shift of effective output on the chosen line.
        produced_so_far = 0
        while produced_so_far < target_units:
            line = rng.choices(candidates, weights=weights, k=1)[0]
            oee = rng.uniform(*_OEE_RANGE)
            shift_qty = int(line.nominal_speed_bph * 8 * oee)
            remaining = target_units - produced_so_far
            planned = min(shift_qty, remaining)
            if planned < shift_qty * 0.25 and produced_so_far > 0:
                planned = remaining  # fold a small tail into this run
            produced_so_far += planned

            day = date(year, month, rng.randint(1, 28))
            shift_start = rng.choice(_SHIFT_STARTS)
            started_at = datetime.combine(day, shift_start) + timedelta(minutes=rng.randint(0, 45))
            if started_at.date() > today:
                continue

            effective_bph = line.nominal_speed_bph * oee
            duration_h = max(planned / effective_bph, 0.5)
            ended_at = started_at + timedelta(hours=duration_h)

            aborted = rng.random() < _ABORT_RATE
            defective = (not aborted) and rng.random() < _DEFECT_RATE
            scrap = int(planned * rng.uniform(0.005, 0.05))
            if aborted:
                scrap = int(planned * rng.uniform(0.3, 0.6))
            produced = planned - scrap

            run_counter[year] += 1
            suffix = line.line_code.split("-")[-1]
            daily_batch_seq[(day, line.line_code)] += 1
            batch = f"L{day:%y%m%d}{suffix}{daily_batch_seq[(day, line.line_code)]:02d}"

            run = ProductionRun(
                id=uuid4(),
                run_number=f"PR-{year}-{run_counter[year]:06d}",
                product_id=product.id,
                production_line_id=line.id,
                batch_number=batch,
                started_at=started_at,
                ended_at=ended_at,
                planned_qty_units=planned,
                produced_qty_units=produced,
                scrap_qty_units=scrap,
                status=(ProductionRunStatus.aborted if aborted else ProductionRunStatus.completed),
            )
            run.product = product
            run.production_line = line
            for check in _quality_checks(run, product, rng, defective=defective):
                run.quality_checks.append(check)
            runs.append(run)

    runs.sort(key=lambda r: r.started_at)
    maintenance = _maintenance_orders(lines, year_range, today, rng)
    return runs, maintenance
