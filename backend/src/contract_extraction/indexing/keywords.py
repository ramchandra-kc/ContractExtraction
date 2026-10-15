"""BM25 keyword vectors: chunk search text → sparse vector, query → sparse vector.

Words are lower-cased, stop words dropped and the rest stemmed (Snowball English), so "Parties"
matches "party". Each term maps to a stable id (CRC32), so documents and queries agree without a
vocabulary. A chunk's vector holds BM25's term-frequency part; the store multiplies in the
inverse document frequency at query time (Qdrant ``modifier: idf``; ``MemoryStore`` does the same),
so terms rare in the document count most. Heading terms count ``HEADING_BOOST`` times, so a chunk
titled "Parties" outranks one that merely mentions parties.
"""

from __future__ import annotations

import re
import zlib
from collections import Counter

import snowballstemmer

from ..providers.base import SparseVector

K1 = 1.2
B = 0.75
HEADING_BOOST = 3

_WORD = re.compile(r"[a-z0-9]+")
_STEMMER = snowballstemmer.stemmer("english")
_STOP = frozenset("""
a about above after again against all am an and any are as at be because been before being below between both
but by can did do does doing down during each few for from further had has have having he her here hers herself
him himself his how i if in into is it its itself just me more most my myself no nor not now of off on once only
or other our ours ourselves out over own same she should so some such than that the their theirs them themselves
then there these they this those through to too under until up very was we were what when where which while who
whom why will with would you your yours yourself yourselves
""".split())


def terms(text: str) -> list[str]:
    """Stemmed words of ``text``, stop words removed, in order (repeats kept)."""
    words = [w for w in _WORD.findall(text.lower()) if w not in _STOP]
    return _STEMMER.stemWords(words) if words else []


def term_id(term: str) -> int:
    return zlib.crc32(term.encode("utf-8"))


def _counts(search_text: str, headings: str) -> Counter[str]:
    counts = Counter(terms(search_text))
    for t in terms(headings):
        counts[t] += HEADING_BOOST - 1  # heading lines are also part of the search text
    return counts


def length(search_text: str, headings: str = "") -> int:
    """Document length for BM25 (boosted heading terms included)."""
    return sum(_counts(search_text, headings).values())


def doc_vector(search_text: str, headings: str, avgdl: float) -> SparseVector:
    """BM25 term-frequency weights of a chunk; ``avgdl`` is the mean ``length`` over the document's chunks."""
    counts = _counts(search_text, headings)
    norm = K1 * (1 - B + B * sum(counts.values()) / avgdl) if avgdl > 0 else K1
    weights: dict[int, float] = {}
    for t, f in counts.items():
        tid = term_id(t)
        weights[tid] = weights.get(tid, 0.0) + f * (K1 + 1) / (f + norm)
    return SparseVector(list(weights), list(weights.values()))


def query_vector(query: str) -> SparseVector:
    ids = list(dict.fromkeys(term_id(t) for t in terms(query)))
    return SparseVector(ids, [1.0] * len(ids))
