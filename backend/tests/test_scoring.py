"""Partial-credit scoring of values against ground truth (evaluation.py)."""

from __future__ import annotations

import pytest

from contract_extraction.evaluation import score


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
