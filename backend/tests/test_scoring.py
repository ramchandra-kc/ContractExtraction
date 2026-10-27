"""Partial-credit scoring of values against ground truth (evaluation.py)."""

from __future__ import annotations

import pytest

from contract_extraction.evaluation import lenient_score, score


@pytest.mark.parametrize("value, expected, result", [
    ("  Acme   PTY ltd ", "Acme Pty Ltd", 1.0),
    ("Contoso", "Acme Pty Ltd", 0.0),
    (30, 30.0, 1.0),
    (True, True, 1.0),
    (None, "", 1.0),
    ({"rate": None}, "", 1.0),
    ("30 days", "", 0.0),
    ({"due_period": "P30D", "currency": "AUD", "extra": 1}, {"due_period": "P30D", "currency": "aud", "trigger": None}, 1.0),
    ({"due_period": "P30D", "currency": "USD"}, {"due_period": "P30D", "currency": "AUD"}, 0.5),
    ("P30D", {"due_period": "P30D"}, 0.0),
    (["b", "a"], ["a", "b"], 1.0),
    (["a"], ["a", "b"], 0.5),
    (["a", "b", "c", "d"], ["a", "b"], 0.5),
    ([{"name": "Acme", "role": "customer"}, {"name": "Contoso", "role": "supplier"}],
     [{"name": "Contoso", "role": "supplier"}, {"name": "acme", "role": "Customer"}], 1.0),
    ([{"name": "Acme", "role": "supplier"}], [{"name": "Acme", "role": "customer"}], 0.5),
    ({"a": {"b": 1, "c": 2}}, {"a": {"b": 1, "c": 3}}, 0.5),
    ([], [], 1.0),
])
def test_score(value, expected, result):
    assert score(value, expected) == pytest.approx(result)


@pytest.mark.parametrize("value, expected, result", [
    ("Acme Pty Ltd.", "ACME", 1.0),                        # legal form and punctuation ignored
    ("Contoso Limited", "Contoso Ltd", 1.0),
    ("“Effective Date”", "Effective Date", 1.0),
    ("$1,000", 1000, 1.0),
    ("1,000.50", "1000.5", 1.0),
    ("30", 31, 0.0),
    (True, "true", 0.0),                                  # booleans stay exact
    ("thirty days after receipt of invoice", "thirty days after invoice", 0.8),  # F1: precision 4/6, recall 1
    ("Contoso", "Acme Pty Ltd", 0.0),
    ({"name": "Acme Inc.", "role": "customer"}, {"name": "ACME", "role": "Customer"}, 1.0),
    ([{"name": "Acme Inc"}], [{"name": "Acme"}, {"name": "Contoso"}], 0.5),
    (None, "", 1.0),
    ("Acme", "", 0.0),
])
def test_lenient_score(value, expected, result):
    assert round(score(value, expected, lenient=True), 4) == result


def test_lenient_score_is_never_below_the_exact_one():
    cases = [("Acme Pty Ltd", "Acme Pty Ltd"), (["a"], ["a", "b"]), ({"x": 1, "y": "B"}, {"x": 1, "y": "b"}), (30, 30.0)]
    assert all(score(v, e, lenient=True) >= score(v, e) for v, e in cases)
    assert lenient_score("error", "Acme", "Acme", False) == 0.0 and lenient_score("extracted", "x", None, None) is None
