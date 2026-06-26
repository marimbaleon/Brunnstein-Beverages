"""Run the agent over all test_invoices and compare to expected outcomes.

    uv run python -m use_cases.automated_invoice_processing.agent.evaluate

Prints one line per scenario with pass/fail and the diff between predicted
and expected decision + signals.
"""

from __future__ import annotations

import json
from pathlib import Path

from use_cases.automated_invoice_processing.agent.graph import run_on_pdf

_TEST_DIR = Path("use_cases/automated_invoice_processing/test_invoices")


def _load_scenario_meta(scenario_dir: Path) -> dict:
    meta_file = next(scenario_dir.glob("*.json"))
    return json.loads(meta_file.read_text())


def _scenario_pdf(scenario_dir: Path) -> Path:
    return next(scenario_dir.glob("*.pdf"))


def evaluate_all_scenarios() -> list[dict]:
    results: list[dict] = []
    for scenario_dir in sorted(_TEST_DIR.iterdir()):
        if not scenario_dir.is_dir():
            continue
        meta = _load_scenario_meta(scenario_dir)
        pdf_path = _scenario_pdf(scenario_dir)
        verdict = run_on_pdf(str(pdf_path))

        decision_ok = verdict.decision == meta["expected_outcome"]
        expected_signals = set(meta["expected_signals"])
        # Cast to plain strings so the eval output renders as `iban_missing`
        # rather than `<Signal.iban_missing: 'iban_missing'>`.
        actual_signals = {str(s) for s in verdict.signals}
        signals_ok = expected_signals.issubset(actual_signals)

        results.append({
            "scenario": scenario_dir.name,
            "decision_ok": decision_ok,
            "signals_ok": signals_ok,
            "expected_decision": meta["expected_outcome"],
            "actual_decision": str(verdict.decision),
            "expected_signals": sorted(expected_signals),
            "actual_signals": sorted(actual_signals),
            "extra_signals": sorted(actual_signals - expected_signals),
            "missing_signals": sorted(expected_signals - actual_signals),
            "notes": verdict.notes,
        })
    return results


def main() -> None:
    results = evaluate_all_scenarios()
    n_pass = sum(1 for r in results if r["decision_ok"] and r["signals_ok"])
    print(f"{n_pass}/{len(results)} scenarios pass\n")
    for r in results:
        status = "PASS" if r["decision_ok"] and r["signals_ok"] else "FAIL"
        print(f"[{status}] {r['scenario']}")
        if not r["decision_ok"]:
            print(f"    decision: expected {r['expected_decision']!r}, "
                  f"got {r['actual_decision']!r}")
        if r["missing_signals"]:
            print(f"    missing signals: {r['missing_signals']}")
        if r["extra_signals"]:
            print(f"    extra signals:   {r['extra_signals']}")


if __name__ == "__main__":
    main()
