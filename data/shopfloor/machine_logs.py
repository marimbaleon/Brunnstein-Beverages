"""Bronze: raw machine logs as plain-text ``.log`` files.

One file per line per production day. The lines mix several formats on purpose
(ISO timestamps, syslog-style headers, bracketed German timestamps, free text
and ``key=value`` pairs) so that turning them into a clean event stream is a
real Bronze -> Silver parsing job. Content is coherent with the rest of the
data: run start/stop events quote the run and batch numbers, CIP cleaning sits
between runs, and the WARN/ALARM density climbs in the run-up to a corrective
maintenance order on that line.

Files land under::

    data/export/bronze/machine_logs/<line_code>/<YYYY-MM-DD>.log
"""

from __future__ import annotations

import random
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from data.erp.models import MaintenanceOrder, MaintenanceType, ProductionLine, ProductionRun
from data.export import BRONZE_ROOT

_BRONZE_ROOT = BRONZE_ROOT / "machine_logs"

# How long before a corrective failure the chatter starts ramping up.
_PRE_FAILURE_WINDOW_H = 60.0

_COMPONENTS = ["filler", "capper", "labeller", "inspector", "conveyor", "plc"]

_WARN_MESSAGES = [
    "torque deviation on capper head",
    "label sensor missed trigger",
    "minor reject at inspector",
    "buffer level low",
    "fill valve slow to close",
]
_ALARM_MESSAGES = [
    "vibration above threshold",
    "motor temperature high",
    "pneumatic pressure drop",
    "emergency stop triggered",
    "drive fault, line halted",
]


def _fmt_iso(ts: datetime, level: str, comp: str, msg: str) -> str:
    return f"{ts.isoformat(timespec='seconds')} {level:<5} {comp} {msg}"


def _fmt_syslog(ts: datetime, level: str, comp: str, msg: str, line_code: str) -> str:
    host = "line" + line_code.replace("-", "")
    return f"{ts:%b %d %H:%M:%S} {host} {comp}[1]: {level.lower()}: {msg}"


def _fmt_bracket(ts: datetime, level: str, comp: str, msg: str) -> str:
    return f"[{ts:%d.%m.%Y %H:%M:%S}] {level} {comp}={msg}"


# Each line gets a primary format; a minority of rows use an alternate one.
_FORMATS = (_fmt_iso, _fmt_syslog, _fmt_bracket)


def _emit(
    ts: datetime,
    level: str,
    comp: str,
    msg: str,
    line_code: str,
    primary,
    rng: random.Random,
) -> str:
    fmt = primary if rng.random() < 0.85 else rng.choice(_FORMATS)
    if fmt is _fmt_syslog:
        return _fmt_syslog(ts, level, comp, msg, line_code)
    return fmt(ts, level, comp, msg)


def _corrective_by_line(maintenance: list[MaintenanceOrder]) -> dict:
    by_line: dict = defaultdict(list)
    for mo in maintenance:
        by_line[mo.production_line_id].append(mo)
    return by_line


def _near_failure(ts: datetime, corrective: list[MaintenanceOrder]) -> float:
    best = 0.0
    for mo in corrective:
        if mo.type != MaintenanceType.corrective or mo.reported_at < ts:
            continue
        hours = (mo.reported_at - ts).total_seconds() / 3600.0
        if 0 <= hours <= _PRE_FAILURE_WINDOW_H:
            best = max(best, 1.0 - hours / _PRE_FAILURE_WINDOW_H)
    return best


def _day_lines(
    day: date,
    line: ProductionLine,
    runs: list[ProductionRun],
    maintenance: list[MaintenanceOrder],
    primary,
    rng: random.Random,
) -> list[str]:
    events: list[tuple[datetime, str]] = []
    lc = line.line_code

    for run in runs:
        sev = _near_failure(run.started_at, maintenance)
        duration_h = max((run.ended_at - run.started_at).total_seconds() / 3600.0, 0.5)
        eff_bph = int(run.produced_qty_units / duration_h)
        events.append(
            (
                run.started_at,
                _emit(
                    run.started_at,
                    "INFO",
                    "filler",
                    f"run start id={run.run_number} batch={run.batch_number} "
                    f"target={run.planned_qty_units}",
                    lc,
                    primary,
                    rng,
                ),
            )
        )

        # Periodic heartbeats and the occasional warning across the run.
        cursor = run.started_at + timedelta(minutes=rng.randint(10, 30))
        while cursor < run.ended_at:
            roll = rng.random()
            if roll < 0.12 + 0.5 * sev:
                comp = rng.choice(_COMPONENTS)
                if rng.random() < 0.25 + 0.5 * sev:
                    events.append(
                        (
                            cursor,
                            _emit(
                                cursor, "ALARM", comp, rng.choice(_ALARM_MESSAGES), lc, primary, rng
                            ),
                        )
                    )
                else:
                    events.append(
                        (
                            cursor,
                            _emit(
                                cursor, "WARN", comp, rng.choice(_WARN_MESSAGES), lc, primary, rng
                            ),
                        )
                    )
            else:
                jitter = rng.uniform(0.92, 1.04)
                events.append(
                    (
                        cursor,
                        _emit(
                            cursor,
                            "INFO",
                            "plc",
                            f"heartbeat speed_bph={int(eff_bph * jitter)} ok",
                            lc,
                            primary,
                            rng,
                        ),
                    )
                )
            cursor += timedelta(minutes=rng.randint(15, 40))

        events.append(
            (
                run.ended_at,
                _emit(
                    run.ended_at,
                    "INFO",
                    "filler",
                    f"run end id={run.run_number} produced={run.produced_qty_units} "
                    f"scrap={run.scrap_qty_units}",
                    lc,
                    primary,
                    rng,
                ),
            )
        )
        # CIP cleaning after the run.
        cip = run.ended_at + timedelta(minutes=rng.randint(5, 20))
        events.append(
            (cip, _emit(cip, "INFO", "plc", "CIP cleaning cycle started", lc, primary, rng))
        )

    for mo in maintenance:
        if mo.reported_at.date() != day:
            continue
        kind = "preventive" if mo.type == MaintenanceType.preventive else "CORRECTIVE"
        events.append(
            (
                mo.reported_at,
                _emit(
                    mo.reported_at,
                    "ALARM" if kind == "CORRECTIVE" else "INFO",
                    "maintenance",
                    f"{kind} order={mo.order_number} down_min={mo.downtime_minutes} "
                    f'"{mo.description}"',
                    lc,
                    primary,
                    rng,
                ),
            )
        )

    events.sort(key=lambda e: e[0])
    return [text for _, text in events]


def write_machine_logs(
    runs: list[ProductionRun],
    lines: list[ProductionLine],
    maintenance: list[MaintenanceOrder],
    seed: int = 42,
    out_dir: Path = _BRONZE_ROOT,
) -> list[Path]:
    """Write one ``.log`` per line and production day. Returns the paths."""
    rng = random.Random(seed + 9)
    line_by_id = {ln.id: ln for ln in lines}
    corrective_by_line = _corrective_by_line(maintenance)

    # Group runs by (line, calendar day).
    by_line_day: dict[tuple, list[ProductionRun]] = defaultdict(list)
    for run in runs:
        by_line_day[(run.production_line_id, run.started_at.date())].append(run)

    # A stable primary format per line.
    primary_by_line = {ln.id: _FORMATS[i % len(_FORMATS)] for i, ln in enumerate(lines)}

    written: list[Path] = []
    for (line_id, day), day_runs in sorted(
        by_line_day.items(), key=lambda kv: (line_by_id[kv[0][0]].line_code, kv[0][1])
    ):
        line = line_by_id[line_id]
        day_runs.sort(key=lambda r: r.started_at)
        text_lines = _day_lines(
            day,
            line,
            day_runs,
            corrective_by_line.get(line_id, []),
            primary_by_line[line_id],
            rng,
        )
        part_dir = out_dir / line.line_code
        part_dir.mkdir(parents=True, exist_ok=True)
        path = part_dir / f"{day:%Y-%m-%d}.log"
        path.write_text("\n".join(text_lines) + "\n", encoding="utf-8")
        written.append(path)
    return written
