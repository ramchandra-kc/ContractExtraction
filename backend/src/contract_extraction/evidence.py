"""Evidence recall: did the chunks a field was given contain the label's evidence quote?

Draft labels carry a verbatim quote (``labels.notes_for`` stores it in ``ground_truth.notes`` as ``“…”``). A quote
can join several passages with "…"; each passage is a *fragment*. Decomposition reshapes text (Markdown, whitespace,
quote characters, OCR noise), so text is normalised to word tokens and a fragment counts as found in a chunk when at
least ``MIN_COVERAGE`` of its tokens appear there in order (``difflib`` matching blocks).

For one outcome:

* ``evidence_any``: some fragment is in a retrieved chunk (the model saw at least part of the evidence)
* ``evidence_all``: every fragment is (each in some retrieved chunk)
* ``evidence_rank``: rank of the first retrieved chunk holding a fragment (None: not retrieved)
* ``evidence_indexed``: every fragment is in some chunk of the document's index; when not, the evidence was lost
  before retrieval (decomposition or chunking), so retrieval can't be blamed
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache

MIN_COVERAGE = 0.8
# Fragments shorter than this many tokens are too unspecific to locate ("30 days").
MIN_TOKENS = 3

_SPLIT = re.compile(r"\s*(?:…|\.\.\.)\s*")
_WORD = re.compile(r"\w+")


def quote_from_notes(notes: str | None) -> str | None:
    """The evidence quote in label notes written by ``labels.notes_for`` (parts joined by " · "), or None."""
    if not notes:
        return None
    parts = notes.split(" · ")
    for i, part in enumerate(parts):
        if part.startswith("“"):
            for j in range(i, len(parts)):  # the quote itself may contain " · "
                if parts[j].endswith("”"):
                    return " · ".join(parts[i:j + 1])[1:-1].strip() or None
            return None
    return None


def tokens(text: str) -> tuple[str, ...]:
    text = unicodedata.normalize("NFKC", text).casefold()
    return tuple(_WORD.findall(text))


def fragments(quote: str) -> list[tuple[str, ...]]:
    """The quote's passages as token tuples; too-short passages are dropped (unless that leaves none)."""
    parts = [tokens(p) for p in _SPLIT.split(quote) if p.strip()]
    parts = [p for p in parts if p]
    long = [p for p in parts if len(p) >= MIN_TOKENS]
    return long or parts


def covered(fragment: tuple[str, ...], chunk: tuple[str, ...]) -> bool:
    """At least ``MIN_COVERAGE`` of the fragment's tokens appear in the chunk, in order."""
    if not fragment or len(chunk) < len(fragment) * MIN_COVERAGE:
        return False
    if len(fragment) <= len(chunk) and _contains(fragment, chunk):
        return True
    matched = sum(b.size for b in SequenceMatcher(None, fragment, chunk, autojunk=False).get_matching_blocks())
    return matched >= len(fragment) * MIN_COVERAGE


def _contains(fragment: tuple[str, ...], chunk: tuple[str, ...]) -> bool:
    return f" {' '.join(fragment)} " in f" {' '.join(chunk)} "


@dataclass(frozen=True)
class EvidenceMatch:
    fragments: int
    any: bool
    all: bool
    rank: int | None
    indexed: bool | None  # None when the document's chunks are unknown


class Matcher:
    """Matches quotes against chunks, caching tokens and verdicts per (fragment, chunk) for a whole export."""

    def __init__(self) -> None:
        self._covered = lru_cache(maxsize=200_000)(self._covered_uncached)
        self._tokens: dict[object, tuple[str, ...]] = {}
        self._sets: dict[object, frozenset[str]] = {}

    def add_chunks(self, chunks: dict[object, str]) -> None:
        for chunk_id, text in chunks.items():
            if chunk_id not in self._tokens:
                self._tokens[chunk_id] = tokens(text)
                self._sets[chunk_id] = frozenset(self._tokens[chunk_id])

    def _covered_uncached(self, fragment: tuple[str, ...], chunk_id: object) -> bool:
        words = self._sets.get(chunk_id, frozenset())
        if sum(t in words for t in fragment) < len(fragment) * MIN_COVERAGE:  # cheap rejection before difflib
            return False
        return covered(fragment, self._tokens[chunk_id])

    def match(self, quote: str, retrieved: Iterable[tuple[int, object]],
              document_chunks: Iterable[object] | None = None) -> EvidenceMatch | None:
        """``retrieved``: (rank, chunk id) of the outcome's evidence; ``document_chunks``: every chunk id of its index.
        None when the quote has no usable fragment."""
        frags = fragments(quote)
        if not frags:
            return None
        retrieved = sorted(retrieved)
        found = [any(self._covered(f, c) for _, c in retrieved) for f in frags]
        rank = next((r for r, c in retrieved if any(self._covered(f, c) for f in frags)), None)
        indexed = None
        if document_chunks is not None:
            ids = list(document_chunks)
            indexed = all(any(self._covered(f, c) for c in ids) for f in frags)
        return EvidenceMatch(len(frags), any(found), all(found), rank, indexed)
