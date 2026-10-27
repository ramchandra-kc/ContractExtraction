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

``lenient_score`` scores the same structure with ``lenient_leaf`` at the leaves (numbers by value, text by token F1
ignoring legal forms and punctuation), so formatting differences don't count as errors.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
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


def score(value: Any, expected: Any, lenient: bool = False) -> float:
    """How well ``value`` matches ``expected`` (the label), from 0 to 1. ``lenient`` compares leaves with
    ``lenient_leaf`` instead of exactly (objects and lists are scored the same way)."""
    if isinstance(expected, str) and not expected.strip():
        return 1.0 if _empty(value) else 0.0
    if isinstance(expected, dict):
        keys = [k for k, v in expected.items() if not _empty(v)]
        if not keys:
            return 1.0 if _empty(value) else 0.0
        if not isinstance(value, dict):
            return 0.0
        return sum(score(value.get(k), expected[k], lenient) for k in keys) / len(keys)
    if isinstance(expected, list):
        items = [e for e in expected if not _empty(e)]
        got = [v for v in value if not _empty(v)] if isinstance(value, list) else ([] if _empty(value) else [value])
        if not items:
            return 1.0 if not got else 0.0
        remaining, total = list(got), 0.0
        for e in items:
            if not remaining:
                break
            best = max(range(len(remaining)), key=lambda i: score(remaining[i], e, lenient))
            total += score(remaining.pop(best), e, lenient)
        return total / max(len(items), len(got))
    if isinstance(value, (dict, list)):
        return 0.0
    if lenient:
        return lenient_leaf(value, expected)
    return 1.0 if _norm(value) == _norm(expected) else 0.0


# Words that differ between correct spellings of the same party or term: legal forms and articles.
_FILLER = frozenset("the a an pty ltd limited inc incorporated llc lp llp plc corp corporation co company gmbh ag sa "
                    "bv nv srl spa".split())
_TOKEN = re.compile(r"[^\W_]+")
_NUMBER = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")


def _tokens(value: str) -> list[str]:
    words = _TOKEN.findall(unicodedata.normalize("NFKC", value).casefold())
    kept = [w for w in words if w not in _FILLER]
    return kept or words


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace("$", "").replace("€", "").replace("£", "").strip()
        if _NUMBER.fullmatch(text):
            return float(text.replace(",", ""))
    return None


def lenient_leaf(value: Any, expected: Any) -> float:
    """A leaf compared the way a reader would: numbers (also written as "1,000" or "$1,000") by value, booleans
    exactly, text by token F1 after case, punctuation, legal forms and articles are ignored ("Acme Pty Ltd." =
    "ACME"). Partial wording gets partial credit."""
    if isinstance(expected, bool) or isinstance(value, bool):
        return 1.0 if value is expected else 0.0
    a, b = _number(value), _number(expected)
    if a is not None and b is not None:
        return 1.0 if abs(a - b) <= 1e-9 * max(1.0, abs(b)) else 0.0
    if _empty(value) or _empty(expected):
        return 1.0 if _empty(value) and _empty(expected) else 0.0
    got, want = Counter(_tokens(str(value))), Counter(_tokens(str(expected)))
    common = sum((got & want).values())
    if not common:
        return 0.0
    precision, recall = common / sum(got.values()), common / sum(want.values())
    return 2 * precision * recall / (precision + recall)


def lenient_score(status: str, value: Any, expected: Any, exact_match: bool | None) -> float | None:
    """Like ``match_score`` with ``lenient_leaf`` comparisons: a reader's judgement of closeness, reported next to
    the exact and partial scores (never instead of them)."""
    if exact_match is None:
        return None
    if status == "error":
        return 0.0
    return round(score(value, expected, lenient=True), 3)


def match_score(status: str, value: Any, expected: Any, exact_match: bool | None) -> float | None:
    """A best value's partial credit against its label, rounded as the API shows it: None when unlabelled, 0 for an
    error outcome (which never counts as correct)."""
    if exact_match is None:
        return None
    if status == "error":
        return 0.0
    return round(score(value, expected), 3)
