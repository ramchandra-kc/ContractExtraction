"""Paired comparison of experiment arms from an export (results.csv or outcomes.csv), with uncertainty.

Arms are the values of a column (``pipeline``, ``retrieval_config``, or both joined by " / "). Every arm extracted
the same document × field cells, so arms are compared cell by cell: a cell's value is the metric averaged over its
repeats, and only cells present in both arms count.

Fields of one contract are correlated (same document, same decomposition), so cells are not independent samples.
Both statistics therefore resample whole documents:

* ``ci_low`` / ``ci_high``: 95% cluster bootstrap interval of the mean difference (documents drawn with replacement)
* ``p``: two-sided cluster sign-flip permutation test (each document's differences flipped together)
* ``p_holm``: Holm-corrected over the arms compared to the baseline in one call

For a 0/1 metric, McNemar's exact test over cells (``mcnemar_p``, from the discordant pairs ``b`` and ``c``) is
reported too; it treats cells as independent, so prefer ``p`` when they disagree.
"""

from __future__ import annotations

import csv
import math
import random
import statistics
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

METRICS = {
    "exact": "exact_match",
    "score": "score",
    "lenient": "lenient",
    "semantic": "semantic",  # after `experiment semantic`
    "evidence": "evidence_any",
    "invented": "status",  # on "" labels: a value where there is none
}
BINARY = {"exact", "evidence", "invented"}


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _value(row: dict[str, str], metric: str) -> float | None:
    raw = row.get(METRICS[metric], "")
    if metric == "invented":
        return 1.0 if raw == "extracted" else 0.0
    if raw in ("true", "false"):
        return 1.0 if raw == "true" else 0.0
    return float(raw) if raw not in ("", None) else None


def cells(rows: Iterable[dict[str, str]], by: list[str], metric: str, labels: str = "value",
          where: dict[str, str] | None = None) -> dict[str, dict[tuple[str, str], float]]:
    """arm → (document, field) → the metric's mean over the cell's repeats, from succeeded runs."""
    acc: dict[str, dict[tuple[str, str], list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r.get("run_state", "succeeded") != "succeeded":
            continue
        if labels != "all" and r.get("label", "value") != labels:  # retrieval_hits.csv: value labels only
            continue
        if where and any(r.get(k) != v for k, v in where.items()):
            continue
        v = _value(r, metric)
        if v is not None:
            acc[" / ".join(r[c] for c in by)][(r["document"], r["field"])].append(v)
    return {arm: {k: statistics.fmean(v) for k, v in cs.items()} for arm, cs in acc.items()}


@dataclass
class Comparison:
    arm: str
    baseline: str
    cells: int
    documents: int
    baseline_mean: float
    arm_mean: float
    diff: float
    ci_low: float
    ci_high: float
    p: float
    p_holm: float | None = None
    b: int | None = None  # McNemar: baseline right, arm wrong
    c: int | None = None  # McNemar: baseline wrong, arm right
    mcnemar_p: float | None = None


def compare(base: dict[tuple[str, str], float], arm: dict[tuple[str, str], float], *, baseline: str = "",
            name: str = "", binary: bool = False, resamples: int = 10_000, seed: int = 0) -> Comparison | None:
    shared = sorted(base.keys() & arm.keys())
    if not shared:
        return None
    per_doc: dict[str, list[float]] = defaultdict(list)
    for k in shared:
        per_doc[k[0]].append(arm[k] - base[k])
    docs = sorted(per_doc)
    sums, counts = [sum(per_doc[d]) for d in docs], [len(per_doc[d]) for d in docs]
    observed = sum(sums) / sum(counts)
    rng = random.Random(seed)
    boot = []
    for _ in range(resamples):
        idx = [rng.randrange(len(docs)) for _ in docs]
        boot.append(sum(sums[i] for i in idx) / sum(counts[i] for i in idx))
    boot.sort()
    extreme = 0
    total = sum(counts)
    for _ in range(resamples):
        flipped = sum(s if rng.random() < 0.5 else -s for s in sums) / total
        extreme += abs(flipped) >= abs(observed) - 1e-12
    out = Comparison(name, baseline, len(shared), len(docs), statistics.fmean(base[k] for k in shared),
                     statistics.fmean(arm[k] for k in shared), observed,
                     boot[int(0.025 * resamples)], boot[min(resamples - 1, int(0.975 * resamples))],
                     (extreme + 1) / (resamples + 1))
    if binary:
        out.b = sum(base[k] >= 0.5 > arm[k] for k in shared)
        out.c = sum(arm[k] >= 0.5 > base[k] for k in shared)
        out.mcnemar_p = mcnemar(out.b, out.c)
    return out


def mcnemar(b: int, c: int) -> float:
    """Exact two-sided McNemar p-value: a binomial test of b against b + c at 0.5."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def holm(ps: list[float]) -> list[float]:
    """Holm–Bonferroni adjusted p-values, in the input order."""
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    adjusted, running = [0.0] * len(ps), 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (len(ps) - rank) * ps[i]))
        adjusted[i] = running
    return adjusted


def compare_arms(rows: list[dict[str, str]], by: list[str], baseline: str, metric: str = "score",
                 labels: str = "value", where: dict[str, str] | None = None,
                 resamples: int = 10_000, seed: int = 0) -> list[Comparison]:
    """Every arm against ``baseline``, Holm-corrected together."""
    arms = cells(rows, by, metric, labels, where)
    if baseline not in arms:
        raise KeyError(f"baseline {baseline!r} not among the arms: {', '.join(sorted(arms)) or 'none'}")
    out = [c for name in arms if name != baseline
           if (c := compare(arms[baseline], arms[name], baseline=baseline, name=name, binary=metric in BINARY,
                            resamples=resamples, seed=seed))]
    for c, p in zip(out, holm([c.p for c in out]), strict=True):
        c.p_holm = p
    return out
