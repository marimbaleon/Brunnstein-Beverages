"""Policy parameters and the signal -> decision routing table.

These are the levers a business owner would tune. They're collected here so
the decision logic stays declarative and reviewers can find every threshold
in one place. In a real deployment these would live in master data
(per-supplier overrides) rather than as module constants.
"""

from __future__ import annotations

from decimal import Decimal

from use_cases.automated_invoice_processing.agent.signals import (
    Decision,
    Signal,
)

# Three-way match tolerances. Anything below these is treated as a match.
QUANTITY_TOLERANCE = Decimal("0.05")   # 5% delta against goods receipt
UNIT_PRICE_TOLERANCE = Decimal("0.02")  # 2% drift against PO


def decide_from_signals(signals: frozenset[Signal]) -> Decision:
    """Route an invoice to a decision based on its accumulated signals.

    Rules are listed highest-priority-first so the policy is readable as a
    table. If you add a rule, add it where its priority belongs, not at
    the bottom.
    """
    if Signal.iban_mismatch_full in signals:
        return Decision.flag_for_fraud_review

    if signals == {Signal.no_matching_goods_receipt}:
        return Decision.hold_for_goods_receipt

    if signals:
        return Decision.flag_for_review

    return Decision.approve
