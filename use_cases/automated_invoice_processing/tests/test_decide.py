"""Tests for the decision routing.

The decision policy is a pure function of the signal set, so we test it
directly without spinning up the LangGraph state machine.
"""

from use_cases.automated_invoice_processing.agent.policy import decide_from_signals
from use_cases.automated_invoice_processing.agent.signals import Decision, Signal


def test_clean_match_approves():
    assert decide_from_signals(frozenset()) == Decision.approve


def test_full_iban_mismatch_routes_to_fraud():
    signals = frozenset({Signal.iban_mismatch_full, Signal.unit_price_drift})
    assert decide_from_signals(signals) == Decision.flag_for_fraud_review


def test_no_goods_receipt_alone_holds():
    signals = frozenset({Signal.no_matching_goods_receipt})
    assert decide_from_signals(signals) == Decision.hold_for_goods_receipt


def test_no_goods_receipt_plus_other_signals_flags_for_review():
    signals = frozenset({Signal.no_matching_goods_receipt, Signal.po_not_found})
    assert decide_from_signals(signals) == Decision.flag_for_review


def test_extraction_failure_routes_to_review():
    signals = frozenset({Signal.extraction_failed})
    assert decide_from_signals(signals) == Decision.flag_for_review
