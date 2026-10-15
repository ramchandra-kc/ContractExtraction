"""Page text → overlapping chunks with exact character offsets.

Each page is chunked on its own, so a chunk always belongs to one page (clean evidence).
The page text is normalised first (HTML tags removed, line endings unified, trailing
spaces trimmed); offsets refer to that normalised text and ``text == normalised[start:end]``.

Text is split into units: paragraphs, and inside prose paragraphs, sentences (Markdown
headings, lists, tables and code blocks stay whole). Consecutive units are packed up to
``chunk_size`` characters; the next chunk starts at the first unit that lies within the
last ``overlap`` characters, so neighbouring chunks share whole units. A unit longer than
``chunk_size`` is cut into windows that overlap by ``overlap`` characters. A chunk never ends
on a heading: the heading starts the next chunk instead.

Besides its text (what the extraction model reads), each chunk has a **search text** that is
embedded and keyword-indexed: Markdown removed, table rows as ``Header: value`` lines, and the
section it sits in (the last heading before it, possibly on an earlier page) in front.
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
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.M)
_EMPHASIS = re.compile(r"\*\*|__|`")
_BREAK = re.compile(r"<br\s*/?>", re.I)
_BULLET = re.compile(r"^\s*[-*+]\s+")
_SEPARATOR_CELL = re.compile(r"^:?-+:?$")
_SPACES = re.compile(r"[ \t]+")


@dataclass(frozen=True)
class TextChunk:
    page_number: int
    char_start: int
    char_end: int
    text: str
    # Embedded and keyword-indexed instead of ``text``: see the module docstring.
    search_text: str = ""
    # The chunk's section and the headings inside it, one per line (weighted up in keyword search).
    headings: str = ""


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


def pack(spans: list[tuple[int, int]], size: int, overlap: int,
         headings: frozenset[int] = frozenset()) -> list[tuple[int, int]]:
    """Spans packed into chunks; ``headings`` are the indexes of heading spans, which never end a chunk."""
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
        while i < j < len(spans) - 1 and j in headings:
            j -= 1  # leave the heading to the chunk it introduces
        end = spans[j][1]
        chunks.append((start, end))
        if j + 1 >= len(spans):
            break
        # Next chunk starts at the first unit inside the overlap zone (always moving forward).
        i = next((k for k in range(i + 1, j + 1) if spans[k][0] >= end - overlap), j + 1)
    return chunks


def _inline(text: str) -> str:
    return _SPACES.sub(" ", _EMPHASIS.sub("", _BREAK.sub(" ", text))).strip()


def heading_text(line: str) -> str | None:
    """The text of a Markdown heading line, without markers and emphasis; None for other lines."""
    m = _HEADING.fullmatch(line.strip())
    return (_inline(m.group(1)).rstrip(":").strip() or None) if m else None


def _cells(line: str) -> list[str]:
    inner = line.strip()
    inner = inner[1:] if inner.startswith("|") else inner
    inner = inner[:-1] if inner.endswith("|") else inner
    return [_inline(c) for c in inner.split("|")]


def table_rows(lines: list[str]) -> list[str]:
    """A Markdown table as one line per row.

    Columns empty in every row are dropped. Then:

    * two columns: a key/value list (``Name: Downer``); a row with an empty key continues the row above
    * a header naming every column distinctly: each value with its header (``Rate: 5%; Cap: 10%``)
    * otherwise (form-like layouts): each row's cells joined by ``; ``
    """
    rows = [_cells(line) for line in lines]
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    header: list[str] | None = None
    if len(rows) > 1 and all(_SEPARATOR_CELL.match(c) or not c for c in rows[1]):
        header, rows = rows[0], rows[2:]
    rows = [r for r in rows if not all(_SEPARATOR_CELL.match(c) or not c for c in r)]
    keep = [k for k in range(width) if any(r[k] for r in rows + ([header] if header else []))]
    rows, header = [[r[k] for k in keep] for r in rows], [header[k] for k in keep] if header else None
    out: list[str] = []
    if len(keep) == 2:
        for key, value in ([header] if header else []) + rows:  # a two-column "header" is the first pair
            if key and value:
                out.append(f"{key}: {value}")
            elif out and value:
                out[-1] = f"{out[-1]} {value}"
            elif key or value:
                out.append(key or value)
        return out
    labelled = header is not None and all(header) and len(set(header)) == len(header)
    if header and not labelled and any(header):
        rows = [header] + rows
    for r in rows:
        cells = [f"{h}: {v}" for h, v in zip(header, r, strict=True) if v] if labelled and header else [c for c in r if c]
        if cells:
            out.append("; ".join(cells))
    return out


def search_text(text: str, section: str | None = None) -> str:
    """Text for embedding and keyword search: Markdown removed, tables as rows, ``section`` in front."""
    out: list[str] = [section] if section else []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith("|"):
            j = i
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                j += 1
            out += table_rows(lines[i:j])
            i = j
            continue
        heading = heading_text(line)
        cleaned = heading if heading is not None else _inline(_BULLET.sub("", line))
        if cleaned:
            out.append(cleaned)
        i += 1
    return "\n".join(out)


def _sections(text: str) -> list[tuple[int, str]]:
    """(offset, heading) of every Markdown heading, in order."""
    return [(m.start(), h) for m in _HEADING.finditer(text) if (h := heading_text(m.group(0)))]


def page_section(text: str, text_format: str, section: str | None) -> str | None:
    """The section in force at the end of a page that starts in ``section``."""
    found = _sections(normalize(text, text_format)) if text_format == "md" else []
    return found[-1][1] if found else section


def chunk_page(page_number: int, text: str, text_format: str, size: int, overlap: int,
               section: str | None = None) -> list[TextChunk]:
    """Chunks of one page; ``section`` is the heading in force where the page starts (from earlier pages)."""
    normalized = normalize(text, text_format)
    spans = units(normalized, text_format)
    found = _sections(normalized) if text_format == "md" else []
    heads = frozenset(k for k, (s, e) in enumerate(spans)
                      if text_format == "md" and "\n" not in normalized[s:e] and heading_text(normalized[s:e]))
    out: list[TextChunk] = []
    for s, e in pack(spans, size, overlap, heads):
        text = normalized[s:e]
        if not text.strip():
            continue
        before = [h for pos, h in found if pos < s]
        # A chunk that opens with a heading is its own section; others carry the one they continue.
        context = None if heading_text(text.split("\n")[0]) else (before[-1] if before else section)
        inside = [h for pos, h in found if s <= pos < e]
        out.append(TextChunk(page_number, s, e, text, search_text(text, context),
                             "\n".join(([context] if context else []) + inside)))
    return out
