"""Page text → overlapping chunks with exact character offsets.

Each page is chunked on its own, so a chunk always belongs to one page (clean evidence).
The page text is normalised first (HTML tags removed, line endings unified, trailing
spaces trimmed); offsets refer to that normalised text and ``text == normalised[start:end]``.

Text is split into units: paragraphs, and inside prose paragraphs, sentences (Markdown
headings, lists, tables and code blocks stay whole). Consecutive units are packed up to
``chunk_size`` characters; the next chunk starts at the first unit that lies within the
last ``overlap`` characters, so neighbouring chunks share whole units. A unit longer than
``chunk_size`` is cut into windows that overlap by ``overlap`` characters.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

_BLOCK_TAG = re.compile(r"</?(p|div|section|article|header|footer|h[1-6]|li|tr|br|table|ul|ol)\b[^>]*>", re.I)
_CELL_TAG = re.compile(r"</?(td|th)\b[^>]*>", re.I)
_ANY_TAG = re.compile(r"<[^>]+>")
_BLANK_LINES = re.compile(r"\n[ \t]*\n(?:[ \t]*\n)*")
_PARAGRAPH = re.compile(r"(?:[^\n]|\n(?![ \t]*\n))+")
_SENTENCE = re.compile(r"\S.*?(?:[.!?]+(?=\s)|$)", re.S)
_STRUCTURED = re.compile(r"^(#{1,6}\s|\s{0,3}([-*+]|\d+\.)\s|\||```)", re.M)


@dataclass(frozen=True)
class TextChunk:
    page_number: int
    char_start: int
    char_end: int
    text: str


def normalize(text: str, text_format: str) -> str:
    if text_format == "html":
        text = _CELL_TAG.sub(" | ", _BLOCK_TAG.sub("\n", text))
        text = html.unescape(_ANY_TAG.sub("", text))
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def units(text: str, text_format: str) -> list[tuple[int, int]]:
    """Spans of paragraphs, with prose paragraphs split into sentences."""
    spans: list[tuple[int, int]] = []
    for para in _PARAGRAPH.finditer(text):
        start, end = _trim(text, para.start(), para.end())
        if start == end:
            continue
        block = text[start:end]
        if text_format == "md" and _STRUCTURED.search(block):
            spans.append((start, end))
            continue
        for sentence in _SENTENCE.finditer(block):
            s, e = _trim(text, start + sentence.start(), start + sentence.end())
            if s < e:
                spans.append((s, e))
    return spans


def _windows(start: int, end: int, size: int, overlap: int) -> list[tuple[int, int]]:
    step = max(1, size - overlap)
    out, pos = [], start
    while True:
        out.append((pos, min(pos + size, end)))
        if pos + size >= end:
            return out
        pos += step


def pack(spans: list[tuple[int, int]], size: int, overlap: int) -> list[tuple[int, int]]:
    chunks: list[tuple[int, int]] = []
    i = 0
    while i < len(spans):
        start, end = spans[i]
        if end - start > size:
            chunks.extend(_windows(start, end, size, overlap))
            i += 1
            continue
        j = i
        while j + 1 < len(spans) and spans[j + 1][1] - start <= size:
            j += 1
        end = spans[j][1]
        chunks.append((start, end))
        if j + 1 >= len(spans):
            break
        # Next chunk starts at the first unit inside the overlap zone (always moving forward).
        i = next((k for k in range(i + 1, j + 1) if spans[k][0] >= end - overlap), j + 1)
    return chunks


def chunk_page(page_number: int, text: str, text_format: str, size: int, overlap: int) -> list[TextChunk]:
    normalized = normalize(text, text_format)
    return [
        TextChunk(page_number, s, e, normalized[s:e])
        for s, e in pack(units(normalized, text_format), size, overlap)
        if normalized[s:e].strip()
    ]
