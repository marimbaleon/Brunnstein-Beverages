"""Signal and decision codes emitted by the agent.

These strings appear in three places that must stay in sync:
1. `validation.py` and `extraction.py` emit them
2. `graph.py` routes on them
3. `test_invoices/<scenario>/*.json` fixtures declare expected values

Using `StrEnum` keeps the source of truth here. A typo at any call site is
caught by the linter / type checker rather than silently never matching.
"""

from enum import StrEnum


class Signal(StrEnum):
    # IBAN checks (extraction + master data comparison)
    iban_missing = "iban_missing"
    iban_mismatch_typo = "iban_mismatch_typo"
    iban_mismatch_full = "iban_mismatch_full"

    # Master data lookups
    supplier_unknown = "supplier_unknown"
    po_not_found = "po_not_found"
    po_supplier_mismatch = "po_supplier_mismatch"

    # Three-way match against goods receipts
    no_matching_goods_receipt = "no_matching_goods_receipt"
    quantity_mismatch_vs_goods_receipt = "quantity_mismatch_vs_goods_receipt"
    unit_price_drift = "unit_price_drift"

    # Pipeline-level
    extraction_failed = "extraction_failed"


class Decision(StrEnum):
    approve = "approve"
    flag_for_review = "flag_for_review"
    flag_for_fraud_review = "flag_for_fraud_review"
    hold_for_goods_receipt = "hold_for_goods_receipt"


# Signals that should be surfaced to the human reviewer as urgent.
FRAUD_SIGNALS: frozenset[Signal] = frozenset({Signal.iban_mismatch_full})

# Signals that warrant attention but aren't fraud-grade.
WARNING_SIGNALS: frozenset[Signal] = frozenset({
    Signal.iban_mismatch_typo,
    Signal.iban_missing,
    Signal.quantity_mismatch_vs_goods_receipt,
    Signal.unit_price_drift,
})
