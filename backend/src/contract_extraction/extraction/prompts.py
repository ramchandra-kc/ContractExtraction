"""User prompts for the extraction LLM and the judge. System prompts come from the run's config snapshot."""

from __future__ import annotations

from ..domain.config import Field
from .retrieval import Hit

# Hits with less text than this add nothing and are left out of the context.
MIN_CONTEXT_CHARS = 7


def build_context(hits: list[Hit]) -> str:
    return "".join(f"{h.text}\n" for h in hits if len(h.text) >= MIN_CONTEXT_CHARS)


def extraction_prompt(field: Field, context: str) -> str:
    return f"{field.user_prompt}<<<\n{context}\n>>>"


def judge_prompt(field: Field, context: str, answer: str) -> str:
    return f"Question: Extract {field.label}\nContext: {context}\nAnswer: {answer}"
