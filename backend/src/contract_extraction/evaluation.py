"""Partial-credit comparison of an extracted value with its ground-truth label.

``v_run_evaluation.exact_match`` says whether a best value equals its label. Catalogue fields are mostly
objects and lists, where "all or nothing" hides how close an answer is, so the API adds a score:

* text: 1 when equal after trimming, collapsing spaces and ignoring case, else 0
* numbers and booleans: 1 when equal (1 and 1.0 are equal)
* objects: the mean score over the label's keys that have a value (keys the label leaves null or out do
  not count); an object label with no such keys scores 1 only against an empty answer
* lists: each labelled item is matched with the best still-unused answer item; the sum of those scores
  is divided by the larger of the two lengths, so missing and extra items both cost
* the label "" (not in this contract) scores 1 against a value that was not found, else 0
"""

from __future__ import annotations

from typing import Any


def _norm(value: Any) -> Any:
    if isinstance(value, str):
        return " ".join(value.split()).casefold()
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return float(value)
    return value


def _empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict)):
        return all(_empty(v) for v in (value.values() if isinstance(value, dict) else value))
    return False


def score(value: Any, expected: Any) -> float:
    """How well ``value`` matches ``expected`` (the label), from 0 to 1."""
    if isinstance(expected, str) and not expected.strip():
        return 1.0 if _empty(value) else 0.0
    if isinstance(expected, dict):
        keys = [k for k, v in expected.items() if not _empty(v)]
        if not keys:
            return 1.0 if _empty(value) else 0.0
        if not isinstance(value, dict):
            return 0.0
        return sum(score(value.get(k), expected[k]) for k in keys) / len(keys)
    if isinstance(expected, list):
        items = [e for e in expected if not _empty(e)]
        got = [v for v in value if not _empty(v)] if isinstance(value, list) else ([] if _empty(value) else [value])
        if not items:
            return 1.0 if not got else 0.0
        remaining, total = list(got), 0.0
        for e in items:
            if not remaining:
                break
            best = max(range(len(remaining)), key=lambda i: score(remaining[i], e))
            total += score(remaining.pop(best), e)
        return total / max(len(items), len(got))
    if isinstance(value, (dict, list)):
        return 0.0
    return 1.0 if _norm(value) == _norm(expected) else 0.0


def match_score(status: str, value: Any, expected: Any, exact_match: bool | None) -> float | None:
    """A best value's partial credit against its label, rounded as the API shows it: None when unlabelled, 0 for an
    error outcome (which never counts as correct)."""
    if exact_match is None:
        return None
    if status == "error":
        return 0.0
    return round(score(value, expected), 3)
