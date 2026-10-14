"""Parsing of judge answers into verdicts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from ..domain.enums import JudgeIssue, Verdict
from .parsing import parse_json_lenient


@dataclass(frozen=True)
class JudgeOutcome:
    verdict: Verdict
    issue: JudgeIssue | None
    explanation: str
    # The judge call that produced the verdict (None when no call was made).
    llm_call_id: uuid.UUID | None = None


def parse_verdict(answer: str) -> JudgeOutcome:
    parsed = parse_json_lenient(answer)
    if not isinstance(parsed, dict):
        return JudgeOutcome(Verdict.ERROR, None, f"Judge answer is not JSON: {(answer or '')[:300]}")
    status = str(parsed.get("status") or "").strip().upper()
    if status not in (Verdict.PASS, Verdict.FAIL):
        return JudgeOutcome(Verdict.ERROR, None, f"Judge returned status {status or 'nothing'!r}")
    issue_text = str(parsed.get("issue") or "").strip().upper()
    issue = JudgeIssue(issue_text) if issue_text in JudgeIssue.__members__ else None
    if status == Verdict.PASS:
        issue = JudgeIssue.NONE
    explanation = str(parsed.get("explanation") or "").strip() or "No explanation given."
    return JudgeOutcome(Verdict(status), issue, explanation)
