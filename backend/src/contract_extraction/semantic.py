"""Semantic grading of extracted values against labels, for the free-text parts exact and token scores can't judge.

The labels are short paraphrases ("material breach not remedied within 60 days of notice") while extractions often
quote the clause, so ``exact_match``, ``score`` and even ``lenient`` count right answers as wrong. ``semantic`` asks an
LLM whether each part means the same as the label:

* a part is one labelled key of an object label (keys the label leaves empty don't count, as in ``score``), or the
  whole value for any other label
* parts settled without an LLM: an empty answer is wrong; ``lenient`` 1 is right; booleans and numbers are compared
  by ``lenient_leaf``
* the rest is graded correct (1), partial (0.5) or wrong (0) in one call per cell; the cell's score is the mean
  over its parts
* "" labels (not in this contract), errors and exact matches are scored as by ``score``

Grades are cached in a JSON-lines file keyed by the grading model, prompt version, field, label and answer, so
re-scoring (also after ``experiment export`` rewrites the CSVs) and identical answers in other runs and experiments
cost nothing. The grader is a different model family from the one that drafted the labels.
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .evaluation import _empty, lenient_leaf, score
from .extraction.parsing import parse_json_lenient

PROMPT_VERSION = 1
GRADES = {"correct": 1.0, "partial": 0.5, "wrong": 0.0}

SYSTEM = """You grade a contract-extraction system. For each part, compare the EXTRACTED value with the REFERENCE, a \
reviewer's label for the same contract. The reference is often a short paraphrase or summary of the clause; the \
extracted value may quote the contract word for word or word it differently. Grade meaning, not wording.

- correct: the same legal meaning; nothing material in the reference is missing, wrong or contradicted. Extra \
harmless detail is fine.
- partial: some of the reference is captured, e.g. some of its list items, or the right clause with a wrong or \
missing detail such as a period, amount, party or condition.
- wrong: a different meaning or clause, nothing given, or it contradicts the reference.

For lists, judge how well the extracted items cover the reference items; items merged or split differently are fine, \
extra items count against the answer only when they are wrong for this field. Durations are ISO 8601 (P30D = 30 \
days, P1M = one month). null means not given.

Answer with JSON only: {"<part>": {"grade": "correct" | "partial" | "wrong", "reason": "<at most 20 words>"}, ...} \
with one entry per part."""


@dataclass(frozen=True)
class FieldInfo:
    label: str
    description: str | None = None


@dataclass(frozen=True)
class Request:
    """One cell's parts that need the LLM, with the parts already settled."""
    field: str
    expected: Any
    value: Any
    open_parts: tuple[str, ...]

    @property
    def key(self) -> str:
        return cache_key(self.field, self.expected, self.value)


def cache_key(field: str, expected: Any, value: Any) -> str:
    raw = json.dumps([PROMPT_VERSION, field, expected, value], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def parts(value: Any, expected: Any) -> dict[str, tuple[Any, Any]]:
    """part → (answer, label): an object label's non-empty keys, else the whole value as ``"value"``."""
    if isinstance(expected, dict) and any(not _empty(v) for v in expected.values()):
        got = value if isinstance(value, dict) else {}
        return {k: (got.get(k), v) for k, v in expected.items() if not _empty(v)}
    return {"value": (value, expected)}


def settled(value: Any, expected: Any) -> float | None:
    """A part's grade when no LLM is needed, else None."""
    if _empty(value):
        return 0.0
    if score(value, expected, lenient=True) >= 1.0:
        return 1.0
    if isinstance(expected, (bool, int, float)) or isinstance(value, bool):
        return lenient_leaf(value, expected)
    return None


def request(field: str, label: str, status: str, value: Any, expected: Any, exact_match: bool | None) -> Request | None:
    """The LLM work a result row needs, or None when its semantic score follows without one."""
    if label != "value" or status != "extracted" or exact_match:
        return None
    open_parts = tuple(p for p, (v, e) in parts(value, expected).items() if settled(v, e) is None)
    return Request(field, expected, value, open_parts) if open_parts else None


def semantic_score(label: str, status: str, value: Any, expected: Any, exact_match: bool | None,
                   graded: dict[str, float] | None) -> float | None:
    """The cell's semantic score; None when unlabelled or when a part it needs has no grade yet."""
    if exact_match is None or label not in ("value", "absent"):
        return None
    if status == "error":
        return 0.0
    if exact_match:
        return 1.0
    if label == "absent" or status != "extracted":
        return round(score(value, expected), 3)
    total = 0.0
    ps = parts(value, expected)
    for p, (v, e) in ps.items():
        grade = settled(v, e)
        if grade is None:
            if graded is None or p not in graded:
                return None
            grade = graded[p]
        total += grade
    return round(total / len(ps), 3)


def prompt(req: Request, info: FieldInfo | None) -> str:
    head = f"Field: {info.label if info else req.field} ({req.field})"
    if info and info.description:
        head += f"\nWhat it captures: {info.description}"
    ps = parts(req.value, req.expected)
    body = [{"part": p, "reference": ps[p][1], "extracted": ps[p][0]} for p in req.open_parts]
    return f"{head}\n\nParts:\n{json.dumps(body, ensure_ascii=False, indent=1)}"


def parse_grades(text: str, open_parts: Iterable[str]) -> tuple[dict[str, float], dict[str, str]] | None:
    """part → grade and part → reason, or None unless every part got a known grade."""
    data = parse_json_lenient(text)
    if not isinstance(data, dict):
        return None
    grades, reasons = {}, {}
    for p in open_parts:
        entry = data.get(p)
        grade = entry.get("grade") if isinstance(entry, dict) else entry
        if not isinstance(grade, str) or grade.strip().lower() not in GRADES:
            return None
        grades[p] = GRADES[grade.strip().lower()]
        reasons[p] = str(entry.get("reason", "")) if isinstance(entry, dict) else ""
    return grades, reasons


class Cache:
    """Grades by grading model and cell (``cache_key``), in an append-only JSON-lines file."""

    def __init__(self, path: Path, model: str):
        self.path, self.model = path, model
        self.entries: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    e = json.loads(line)
                    if e.get("model") == model:
                        self.entries[e["key"]] = e

    def grades(self, key: str) -> dict[str, float] | None:
        e = self.entries.get(key)
        return e["grades"] if e else None

    def add(self, entry: dict[str, Any]) -> None:
        with self._lock:
            self.entries[entry["key"]] = entry
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


@dataclass
class Usage:
    calls: int = 0
    failed: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0


def grade(requests: list[Request], fields: dict[str, FieldInfo], complete: Callable[[str, str], Any], cache: Cache,
          workers: int = 8, report: Callable[[int, int], None] | None = None) -> Usage:
    """Grade the requests missing from the cache, ``workers`` calls at a time. ``complete(system, user)`` returns a
    ``ChatResult``; an answer without a grade for every part is retried once, then left ungraded."""
    todo = list({r.key: r for r in requests if cache.grades(r.key) is None}.values())
    usage, lock, done = Usage(), threading.Lock(), [0]

    def one(req: Request) -> None:
        user = prompt(req, fields.get(req.field))
        for _ in range(2):
            try:
                result = complete(SYSTEM, user)
            except Exception:  # noqa: BLE001 - a failed call leaves the cell ungraded; the next run retries it
                continue
            with lock:
                usage.calls += 1
                usage.prompt_tokens += result.prompt_tokens or 0
                usage.completion_tokens += result.completion_tokens or 0
            parsed = parse_grades(result.text, req.open_parts)
            if parsed:
                cache.add({"key": req.key, "model": cache.model, "field": req.field, "grades": parsed[0],
                           "reasons": parsed[1]})
                break
        else:
            with lock:
                usage.failed += 1
        with lock:
            done[0] += 1
            if report:
                report(done[0], len(todo))

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        list(pool.map(one, todo))
    return usage


def _load(raw: str) -> Any:
    return json.loads(raw) if raw not in ("", None) else None


def _exact(raw: str) -> bool | None:
    return {"true": True, "false": False}.get(raw)


def requests_for(rows: Iterable[dict[str, str]]) -> list[Request]:
    out = []
    for r in rows:
        req = request(r["field"], r.get("label", ""), r.get("status", ""), _load(r.get("value", "")),
                      _load(r.get("expected", "")), _exact(r.get("exact_match", "")))
        if req:
            out.append(req)
    return out


def add_scores(path: Path, cache: Cache) -> tuple[int, int]:
    """Rewrite an export CSV with a ``semantic`` column; returns (scored, missing a grade) over labelled rows."""
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    scored = missing = 0
    for r in rows:
        value, expected, exact = _load(r.get("value", "")), _load(r.get("expected", "")), _exact(r.get("exact_match", ""))
        s = semantic_score(r.get("label", ""), r.get("status", ""), value, expected, exact,
                           cache.grades(cache_key(r["field"], expected, value)))
        r["semantic"] = "" if s is None else s
        if s is not None:
            scored += 1
        elif exact is not None and r.get("label") in ("value", "absent"):
            missing += 1
    if rows:
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    return scored, missing


def sample(rows: list[dict[str, str]], cache: Cache, n: int, seed: int = 2026) -> list[dict[str, Any]]:
    """``n`` LLM-graded parts drawn at random (one per distinct cell), for a hand check: fill ``human_grade`` with
    correct / partial / wrong and pass the file to ``agreement``."""
    cells: dict[str, tuple[dict[str, str], Request]] = {}
    for r, req in ((r, requests_for([r])) for r in rows):
        if req and cache.grades(req[0].key) is not None:
            cells.setdefault(req[0].key, (r, req[0]))
    picked = random.Random(seed).sample(sorted(cells), min(n, len(cells)))
    out = []
    for key in picked:
        row, req = cells[key]
        e = cache.entries[key]
        part = random.Random(key).choice(req.open_parts)
        v, x = parts(req.value, req.expected)[part]
        out.append({"document": row["document"], "field": req.field, "part": part,
                    "reference": json.dumps(x, ensure_ascii=False), "extracted": json.dumps(v, ensure_ascii=False),
                    "lenient": round(score(v, x, lenient=True), 3),
                    "grade": next(g for g, s in GRADES.items() if s == e["grades"][part]),
                    "reason": e.get("reasons", {}).get(part, ""), "human_grade": ""})
    return out


def agreement(rows: Iterable[dict[str, str]]) -> dict[str, Any]:
    """Grader vs hand grades on a filled-in sample: raw agreement, Cohen's kappa, and agreement on correct vs not."""
    pairs = [(r["grade"].strip().lower(), r["human_grade"].strip().lower()) for r in rows
             if r.get("human_grade", "").strip().lower() in GRADES]
    if not pairs:
        return {"n": 0}
    n = len(pairs)
    observed = sum(a == b for a, b in pairs) / n
    expected = sum((sum(a == g for a, _ in pairs) / n) * (sum(b == g for _, b in pairs) / n) for g in GRADES)
    kappa = (observed - expected) / (1 - expected) if expected < 1 else 1.0
    binary = sum((a == "correct") == (b == "correct") for a, b in pairs) / n
    confusion = {f"{a}->{b}": sum(1 for x in pairs if x == (a, b)) for a in GRADES for b in GRADES}
    return {"n": n, "agreement": round(observed, 3), "kappa": round(kappa, 3), "correct_agreement": round(binary, 3),
            "confusion": {k: v for k, v in confusion.items() if v}}
