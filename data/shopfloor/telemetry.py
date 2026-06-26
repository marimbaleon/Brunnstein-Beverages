"""Bronze: raw line-sensor telemetry as Parquet.

One row per sensor sample (default cadence 60 s) taken while a production run is
filling. Each row carries the line, the run and batch it belongs to, and the
core signals a bottling line exposes: line speed, motor temperature, vibration,
buffer fill level, pressure and ambient temperature.

In the hours before every *corrective* maintenance order, vibration and motor
temperature on that line drift upward toward the failure — the signal the
predictive-maintenance use case has to detect before the line goes down.
Preventive maintenance carries no such drift.

Files land partitioned by line and month::

    data/export/bronze/iot_telemetry/line=<line_code>/<year>-<month>.parquet
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from data.erp.models import MaintenanceOrder, MaintenanceType, ProductionLine, ProductionRun
from data.export import BRONZE_ROOT

_BRONZE_ROOT = BRONZE_ROOT / "iot_telemetry"

_SAMPLE_SECONDS = 60

# Hours before a corrective failure over which the degradation builds.
_DRIFT_WINDOW_H = 60.0
# Peak additive drift at the moment of failure.
_VIBRATION_DRIFT_MM_S = 6.5
_MOTOR_TEMP_DRIFT_C = 22.0

# Per-line healthy baselines.
_BASE_MOTOR_TEMP_C = 52.0
_BASE_VIBRATION_MM_S = 2.0
_BASE_PRESSURE_BAR = 3.0

_MICRO_STOP_PROB = 0.015  # chance a given sample sits in a brief stoppage


def _ambient_c(ts: datetime) -> float:
    """Plant-hall ambient: seasonal swing plus a mild day/night cycle."""
    season = 18.0 + 9.0 * math.cos((ts.month - 7) * math.pi / 6.0) * -1
    daily = 2.5 * math.sin((ts.hour - 9) * math.pi / 12.0)
    return season + daily


def _corrective_by_line(maintenance: list[MaintenanceOrder]) -> dict:
    by_line: dict = defaultdict(list)
    for mo in maintenance:
        if mo.type == MaintenanceType.corrective:
            by_line[mo.production_line_id].append(mo.reported_at)
    for line_id in by_line:
        by_line[line_id].sort()
    return by_line


def _drift_severity(ts: datetime, failures: list[datetime]) -> float:
    """0 when healthy, ramping to ~1 at the next corrective failure within window."""
    best = 0.0
    for reported in failures:
        if reported < ts:
            continue
        hours = (reported - ts).total_seconds() / 3600.0
        if hours > _DRIFT_WINDOW_H:
            continue
        # Quadratic ramp: stays quiet, then climbs steeply near the failure.
        best = max(best, (1.0 - hours / _DRIFT_WINDOW_H) ** 2)
    return best


def _run_samples(
    run: ProductionRun,
    line: ProductionLine,
    failures: list[datetime],
    rng: random.Random,
) -> dict[str, list]:
    duration_s = max((run.ended_at - run.started_at).total_seconds(), _SAMPLE_SECONDS)
    effective_bph = run.produced_qty_units / max(duration_s / 3600.0, 0.5)

    cols: dict[str, list] = {
        "ts": [],
        "line_code": [],
        "run_number": [],
        "batch_number": [],
        "line_speed_bph": [],
        "motor_temp_c": [],
        "vibration_mm_s": [],
        "fill_level_pct": [],
        "pressure_bar": [],
        "ambient_temp_c": [],
    }

    n = int(duration_s // _SAMPLE_SECONDS) + 1
    for i in range(n):
        ts = run.started_at + timedelta(seconds=i * _SAMPLE_SECONDS)
        sev = _drift_severity(ts, failures)
        ambient = _ambient_c(ts)

        if rng.random() < _MICRO_STOP_PROB:
            speed = rng.uniform(0.0, effective_bph * 0.1)
        else:
            speed = effective_bph * rng.uniform(0.95, 1.03)

        load = speed / max(line.nominal_speed_bph, 1)
        motor = (
            _BASE_MOTOR_TEMP_C
            + 14.0 * load
            + 0.35 * (ambient - 18.0)
            + sev * _MOTOR_TEMP_DRIFT_C
            + rng.gauss(0, 0.8)
        )
        vibration = (
            _BASE_VIBRATION_MM_S + 1.2 * load + sev * _VIBRATION_DRIFT_MM_S + rng.gauss(0, 0.15)
        )
        fill = 50.0 + 40.0 * math.sin(i / 6.0) + rng.gauss(0, 4.0)
        pressure = _BASE_PRESSURE_BAR + 0.4 * load + rng.gauss(0, 0.05)

        cols["ts"].append(ts)
        cols["line_code"].append(line.line_code)
        cols["run_number"].append(run.run_number)
        cols["batch_number"].append(run.batch_number)
        cols["line_speed_bph"].append(round(max(speed, 0.0), 1))
        cols["motor_temp_c"].append(round(motor, 2))
        cols["vibration_mm_s"].append(round(max(vibration, 0.0), 3))
        cols["fill_level_pct"].append(round(min(max(fill, 0.0), 100.0), 1))
        cols["pressure_bar"].append(round(max(pressure, 0.0), 3))
        cols["ambient_temp_c"].append(round(ambient, 2))

    return cols


def write_iot_telemetry(
    runs: list[ProductionRun],
    lines: list[ProductionLine],
    maintenance: list[MaintenanceOrder],
    seed: int = 42,
    out_dir: Path = _BRONZE_ROOT,
) -> list[Path]:
    """Write per-line, per-month telemetry Parquet files. Returns the paths."""
    rng = random.Random(seed + 7)
    line_by_id = {ln.id: ln for ln in lines}
    failures_by_line = _corrective_by_line(maintenance)

    # Accumulate samples per (line_code, year-month) before writing.
    buckets: dict[tuple[str, str], dict[str, list]] = {}
    for run in runs:
        line = line_by_id[run.production_line_id]
        failures = failures_by_line.get(line.id, [])
        samples = _run_samples(run, line, failures, rng)
        month_key = f"{run.started_at.year}-{run.started_at.month:02d}"
        bucket = buckets.setdefault((line.line_code, month_key), {k: [] for k in samples})
        for col, values in samples.items():
            bucket[col].extend(values)

    written: list[Path] = []
    for (line_code, month_key), cols in sorted(buckets.items()):
        part_dir = out_dir / f"line={line_code}"
        part_dir.mkdir(parents=True, exist_ok=True)
        path = part_dir / f"{month_key}.parquet"
        table = pa.table(cols)
        pq.write_table(table, path, compression="snappy")
        written.append(path)
    return written
