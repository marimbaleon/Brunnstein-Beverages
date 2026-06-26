"""Tests for validation helpers that don't need a database."""

from use_cases.automated_invoice_processing.agent.signals import Signal
from use_cases.automated_invoice_processing.agent.validation import (
    _compare_iban_against_master,
)


def test_iban_match_emits_no_signals():
    iban = "DE89370400440532013000"
    assert _compare_iban_against_master(iban, iban) == []


def test_iban_full_mismatch():
    master = "DE89370400440532013000"
    pdf = "DE12121212121212121212"
    assert _compare_iban_against_master(pdf, master) == [Signal.iban_mismatch_full]


def test_iban_typo_last_two_swapped():
    master = "DE89370400440532013067"
    pdf = "DE89370400440532013076"  # 67 -> 76
    assert _compare_iban_against_master(pdf, master) == [Signal.iban_mismatch_typo]


def test_iban_missing():
    master = "DE89370400440532013000"
    assert _compare_iban_against_master(None, master) == [Signal.iban_missing]
    assert _compare_iban_against_master("", master) == [Signal.iban_missing]
