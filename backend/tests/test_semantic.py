"""Semantic grading (semantic.py): which parts need the LLM, how grades combine, caching, CSV rewrite, agreement."""

from __future__ import annotations

import csv
import json

import pytest

from contract_extraction.providers.base import ChatResult
from contract_extraction.semantic import (Cache, FieldInfo, agreement, grade, parse_grades, parts, prompt, request,
                                          requests_for, add_scores, sample, semantic_score)

LABEL = {"triggers": ["material breach not remedied within 30 days of notice", "insolvency"],
         "cure_period": "P30D", "insolvency_trigger": True, "notice": None}
ANSWER = {"triggers": ["Supplier commits a material breach and fails to remedy it within thirty (30) days after notice",
                       "Supplier becomes insolvent"],
          "cure_period": "P30D", "insolvency_trigger": False}


def test_only_unsettled_parts_go_to_the_llm():
    assert set(parts(ANSWER, LABEL)) == {"triggers", "cure_period", "insolvency_trigger"}  # empty "notice" ignored
    req = request("termination_for_cause", "value", "extracted", ANSWER, LABEL, False)
    assert req.open_parts == ("triggers",)  # cure_period equal, boolean compared exactly
    assert request("x", "value", "extracted", ANSWER, LABEL, True) is None
    assert request("x", "value", "not_found", None, LABEL, False) is None
    assert request("x", "absent", "extracted", "something", "", False) is None
    assert request("title", "value", "extracted", "Acme Pty Ltd.", "ACME PTY LTD", False) is None  # lenient 1


def test_scores_combine_settled_and_graded_parts():
    assert semantic_score("value", "extracted", ANSWER, LABEL, False, None) is None  # grade still missing
    assert semantic_score("value", "extracted", ANSWER, LABEL, False, {"triggers": 1.0}) == pytest.approx(2 / 3, abs=1e-3)
    assert semantic_score("value", "extracted", ANSWER, LABEL, False, {"triggers": 0.5}) == 0.5
    assert semantic_score("value", "not_found", None, LABEL, False, None) == 0.0
    assert semantic_score("value", "error", None, LABEL, False, None) == 0.0
    assert semantic_score("absent", "not_found", None, "", True, None) == 1.0
    assert semantic_score("absent", "extracted", "x", "", False, None) == 0.0
    assert semantic_score("unlabelled", "extracted", "x", None, None, None) is None


def test_prompt_and_answer_parsing():
    req = request("termination_for_cause", "value", "extracted", ANSWER, LABEL, False)
    text = prompt(req, FieldInfo("Termination for cause", "Grounds on which a party may terminate"))
    assert "Termination for cause" in text and "Grounds on which" in text and "thirty (30) days" in text
    assert "cure_period" not in text  # settled parts are not sent
    assert parse_grades('```json\n{"triggers": {"grade": "Correct", "reason": "same"}}\n```', ["triggers"]) == (
        {"triggers": 1.0}, {"triggers": "same"})
    assert parse_grades('{"triggers": "partial"}', ["triggers"]) == ({"triggers": 0.5}, {"triggers": ""})
    assert parse_grades('{"triggers": {"grade": "maybe"}}', ["triggers"]) is None
    assert parse_grades('{"other": {"grade": "wrong"}}', ["triggers"]) is None


def _rows(tmp_path):
    rows = [{"document": f"DOC{i}", "field": "termination_for_cause", "label": "value", "status": "extracted",
             "value": json.dumps(ANSWER), "expected": json.dumps(LABEL), "exact_match": "false", "run_state": "succeeded"}
            for i in range(3)]
    rows.append({"document": "DOC9", "field": "title", "label": "absent", "status": "not_found", "value": "",
                 "expected": '""', "exact_match": "true", "run_state": "succeeded"})
    path = tmp_path / "results.csv"
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return path, rows


def test_grading_is_cached_and_written_to_the_csv(tmp_path):
    path, rows = _rows(tmp_path)
    calls = []

    def complete(system, user):
        calls.append(user)
        return ChatResult('{"triggers": {"grade": "correct", "reason": "same grounds"}}', 5, 100, 20)

    cache = Cache(tmp_path / "cache.jsonl", "grader-model")
    usage = grade(requests_for(rows), {}, complete, cache)
    assert len(calls) == 1 and (usage.calls, usage.prompt_tokens, usage.failed) == (1, 100, 0)  # identical cells once
    assert grade(requests_for(rows), {}, complete, Cache(tmp_path / "cache.jsonl", "grader-model")).calls == 0
    assert Cache(tmp_path / "cache.jsonl", "other-model").entries == {}  # another grader starts afresh

    assert add_scores(path, cache) == (4, 0)
    written = list(csv.DictReader(path.open()))
    assert [r["semantic"] for r in written] == ["0.667"] * 3 + ["1.0"]

    picked = sample(written, cache, 5)
    assert len(picked) == 1 and picked[0]["part"] == "triggers" and picked[0]["grade"] == "correct"


def test_a_bad_answer_is_retried_then_left_ungraded(tmp_path):
    _, rows = _rows(tmp_path)
    answers = iter(["not json", "still not"])
    cache = Cache(tmp_path / "cache.jsonl", "m")
    usage = grade(requests_for(rows), {}, lambda s, u: ChatResult(next(answers), 1), cache)
    assert (usage.calls, usage.failed) == (2, 1) and cache.entries == {}


def test_agreement_with_hand_grades():
    rows = [{"grade": g, "human_grade": h} for g, h in
            [("correct", "correct")] * 6 + [("wrong", "wrong")] * 3 + [("partial", "correct"), ("correct", "")]]
    a = agreement(rows)
    assert a["n"] == 10 and a["agreement"] == 0.9 and a["correct_agreement"] == 0.9
    assert 0.7 < a["kappa"] < 0.9 and a["confusion"]["partial->correct"] == 1
    assert agreement([{"grade": "correct", "human_grade": ""}]) == {"n": 0}
