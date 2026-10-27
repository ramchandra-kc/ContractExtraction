"""Paired arm comparison (compare.py): pairing, cluster bootstrap, permutation p-values, McNemar and Holm."""

from __future__ import annotations

import pytest

from contract_extraction.compare import cells, compare, compare_arms, holm, mcnemar


def _rows(arm: str, values: dict[tuple[str, str], list[str]], column: str = "exact_match", **extra) -> list[dict]:
    return [{"retrieval_config": arm, "document": d, "field": f, column: v, "label": "value", "run_state": "succeeded", **extra}
            for (d, f), vs in values.items() for v in vs]


def test_cells_average_repeats_and_keep_only_wanted_rows():
    rows = _rows("A", {("D1", "title"): ["true", "false"], ("D1", "parties"): ["true"]})
    rows += [{**rows[0], "label": "absent", "field": "x"}, {**rows[0], "run_state": "failed", "field": "y"}]
    assert cells(rows, ["retrieval_config"], "exact") == {"A": {("D1", "title"): 0.5, ("D1", "parties"): 1.0}}


def test_mcnemar_and_holm():
    assert mcnemar(0, 0) == 1.0 and mcnemar(5, 5) == 1.0
    assert mcnemar(0, 10) == pytest.approx(2 / 1024)
    assert holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])


def test_a_clear_effect_has_a_ci_above_zero_and_no_effect_one_around_it():
    docs = [f"D{i}" for i in range(20)]
    base = {(d, f): 0.0 for d in docs for f in "abc"}
    better = {k: 1.0 if k[1] != "c" else 0.0 for k in base}
    c = compare(base, better, binary=True, resamples=2000)
    assert (c.cells, c.documents) == (60, 20) and c.diff == pytest.approx(2 / 3)
    assert c.ci_low > 0 and c.p < 0.01 and (c.b, c.c) == (0, 40)

    noise = {k: 1.0 if (int(k[0][1:]) + ord(k[1])) % 2 else 0.0 for k in base}
    same = compare(noise, {k: noise[(k[0], {"a": "b", "b": "a", "c": "c"}[k[1]])] for k in noise}, resamples=2000)
    assert same.ci_low <= 0 <= same.ci_high and same.p > 0.05


def test_one_document_driving_an_effect_is_not_significant():
    """Ten fields better in one contract and nothing elsewhere: cell-level McNemar says significant, the cluster
    statistics (rightly) don't, as the evidence comes from a single document."""
    base = {(f"D{i}", f"f{j}"): 0.0 for i in range(10) for j in range(10)}
    arm = {k: 1.0 if k[0] == "D0" else 0.0 for k in base}
    c = compare(base, arm, binary=True, resamples=4000)
    assert c.mcnemar_p < 0.01
    assert c.ci_low == 0.0 and c.p > 0.05


def test_compare_arms_pairs_shared_cells_against_the_baseline():
    rows = (_rows("RAG02", {("D1", "a"): ["false"], ("D2", "a"): ["false"], ("D2", "b"): ["true"]})
            + _rows("RAG07", {("D1", "a"): ["true"], ("D2", "a"): ["true"], ("D3", "a"): ["true"]}))
    [c] = compare_arms(rows, ["retrieval_config"], "RAG02", "exact", resamples=500)
    assert (c.arm, c.cells, c.documents, c.diff, c.p_holm) == ("RAG07", 2, 2, 1.0, c.p)
    with pytest.raises(KeyError, match="RAG99"):
        compare_arms(rows, ["retrieval_config"], "RAG99", "exact")
