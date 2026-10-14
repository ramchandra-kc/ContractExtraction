"""Repeating header and footer removal.

Pages are processed in batches of ``BATCH_SIZE``. For each page the first and last
``EDGE_RATIO`` of its lines form the header and footer zones. A line is normalised
(Markdown heading markers removed, whitespace collapsed, digits → ``#``, case folded) so
"Page 3 of 10" and "Page 4 of 10" match. A normalised line that appears in the same zone on
at least ``max(2, MIN_SHARE * batch size)`` pages is moved out of the page text into the
page's ``header`` or ``footer``. Lines outside the zones are never touched.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

BATCH_SIZE = 20
EDGE_RATIO = 0.15
MIN_SHARE = 0.3

_HEADING = re.compile(r"^#+\s+")
_SPACE = re.compile(r"\s+")
_DIGITS = re.compile(r"\d+")


def normalize(line: str) -> str:
    line = _SPACE.sub(" ", _HEADING.sub("", line.strip())).strip()
    return _DIGITS.sub("#", line).casefold()


@dataclass
class PageText:
    text: str
    header: str | None = None
    footer: str | None = None


def _zones(lines: list[str]) -> tuple[int, set[str], set[str]]:
    edge = max(1, math.ceil(len(lines) * EDGE_RATIO))
    head = {n for n in map(normalize, lines[:edge]) if n}
    foot = {n for n in map(normalize, lines[-edge:]) if n}
    return edge, head, foot


def _process(batch: list[PageText]) -> None:
    prepared = []
    head_counts: Counter[str] = Counter()
    foot_counts: Counter[str] = Counter()
    for page in batch:
        lines = page.text.splitlines()
        edge, head, foot = _zones(lines)
        prepared.append((page, lines, edge))
        head_counts.update(head)
        foot_counts.update(foot)

    threshold = max(2, math.ceil(len(batch) * MIN_SHARE))
    head_patterns = {k for k, v in head_counts.items() if v >= threshold}
    foot_patterns = {k for k, v in foot_counts.items() if v >= threshold}
    if not head_patterns and not foot_patterns:
        return

    for page, lines, edge in prepared:
        keep, header, footer = [], [], []
        for i, line in enumerate(lines):
            key = normalize(line)
            if i < edge and key in head_patterns:
                header.append(line.strip())
            elif i >= len(lines) - edge and key in foot_patterns:
                footer.append(line.strip())
            else:
                keep.append(line)
        if header or footer:
            page.text = "\n".join(keep).strip()
            page.header = "\n".join(header) or None
            page.footer = "\n".join(footer) or None


def strip_headers_footers(pages: list[PageText]) -> list[PageText]:
    """Mutates and returns ``pages`` (in reading order). Empty pages are skipped."""
    non_empty = [p for p in pages if p.text.strip()]
    for i in range(0, len(non_empty), BATCH_SIZE):
        _process(non_empty[i:i + BATCH_SIZE])
    return pages
