"""Contract type detection: which of the field set's contract types a document is.

The classifier reads the document's first pages (title, parties, recitals usually settle it) and
answers with one or more types, each with a confidence and a short quote. A document can be several
types at once (an MSA with a SOW attached). Proposals reaching the pipeline's minimum confidence are
selected; when none is, the run uses the fallback type.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from ..domain.config import ContractType
from .parsing import parse_json_lenient

# Upper bound on the document text shown to the classifier (about 3k tokens).
MAX_CHARS = 12_000
OTHER = "other"


@dataclass(frozen=True)
class Candidate:
    key: str
    confidence: Decimal
    evidence: str | None


def opening_text(chunks: list[tuple[int, str]], pages: int, max_chars: int = MAX_CHARS) -> str:
    """Text of the chunks starting on the first ``pages`` pages, in document order, cut at ``max_chars``.

    ``chunks`` are (page_start, text) in chunk order.
    """
    text = "\n".join(t for page, t in chunks if page <= pages)
    if not text and chunks:  # e.g. pages are numbered from a large offset: use the start of the document
        text = "\n".join(t for _, t in chunks)
    return text[:max_chars]


def classification_prompt(types: tuple[ContractType, ...], text: str) -> str:
    listed = [f"- {t.key}: {t.label} — {t.description}" for t in types if not t.is_fallback]
    listed.append(f"- {OTHER}: none of the types above")
    return ("Contract types:\n" + "\n".join(listed)
            + "\n\nWhich of these contract types is the document below? List every type that applies "
            "(e.g. a master agreement with a statement of work attached is both), most likely first.\n"
            'Return JSON: {"types": [{"key": "<type key>", "confidence": <0 to 1>, '
            '"evidence": "<short quote from the document>"}]}\n\n'
            f"Document (first pages):\n<<<\n{text}\n>>>")


def _confidence(raw: object) -> Decimal | None:
    if isinstance(raw, bool) or raw is None:
        return None
    text = str(raw).strip()
    percent = text.endswith("%")
    try:
        value = Decimal(re.sub(r"[%\s]", "", text))
    except InvalidOperation:
        return None
    if percent or value > 1:
        value /= 100
    if not value.is_finite():
        return None
    return max(Decimal(0), min(Decimal(1), value)).quantize(Decimal("0.001"))


def parse_classification(answer: str, known: set[str]) -> list[Candidate]:
    """Proposed types from the classifier's answer: known keys (and "other") only, best first, no repeats.

    Accepts ``{"types": [...]}``, a bare list, or a single ``{"key": ...}`` object; a missing confidence
    counts as 0.5, a bare key string as 1.
    """
    parsed = parse_json_lenient(answer)
    if isinstance(parsed, dict):
        items = parsed.get("types", [parsed] if "key" in parsed else [])
    else:
        items = parsed if isinstance(parsed, list) else []
    out: dict[str, Candidate] = {}
    for item in items:
        if isinstance(item, str):
            key, conf, evidence = item, Decimal(1), None
        elif isinstance(item, dict):
            key = str(item.get("key") or item.get("type") or "")
            conf = _confidence(item.get("confidence"))
            conf = Decimal("0.5") if conf is None else conf
            evidence = str(item["evidence"]).strip()[:1000] if item.get("evidence") else None
        else:
            continue
        key = re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")
        if (key in known or key == OTHER) and (key not in out or conf > out[key].confidence):
            out[key] = Candidate(key, conf, evidence)
    return sorted(out.values(), key=lambda c: -c.confidence)


def select(candidates: list[Candidate], min_confidence: Decimal, fallback_key: str | None) -> list[str]:
    """Keys of the proposed types to use: confident enough, and not "other" or the fallback type."""
    return [c.key for c in candidates
            if c.confidence >= min_confidence and c.key not in (OTHER, fallback_key)]
