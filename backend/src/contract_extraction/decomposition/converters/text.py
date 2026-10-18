"""Plain text → pages, plus the text helpers the other text formats share.

Pages come from page-break markers (EDGAR ``<PAGE>`` lines, form feeds); without markers
the text is split at paragraph boundaries near ``options.page_chars`` characters. EDGAR
filings are unwrapped first: only the body inside ``<TEXT>…</TEXT>`` is kept and the
SGML table tags are dropped. Text is stored as Markdown, so lines that Markdown would read
as headings, quotes or code are neutralised.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from ...domain.config import DecompositionConfig
from ...domain.enums import DocumentFormat, TextFormat
from .base import ConvertResult, DecompositionError, FormatSpec, PagedBy, RawPage, select_pages

DEFAULT_PAGE_CHARS = 3000

_EDGAR_TEXT = re.compile(r"<TEXT>(.*?)(?:</TEXT>|\Z)", re.I | re.S)
_EDGAR_TAG = re.compile(r"</?(?:TABLE|CAPTION|S|C|FN|F\d+)>", re.I)
_PAGE_MARKER = re.compile(r"^[ \t]*<PAGE>[ \t]*(?:\r?\n|$)|\f", re.I | re.M)
_BLANK_LINES = re.compile(r"\n[ \t]*\n(?:[ \t]*\n)*")
_MD_LINE_START = re.compile(r"^([#>])", re.M)


def decode(data: bytes) -> str:
    """UTF-8 (with or without BOM), else Windows-1252, else Latin-1 (which never fails)."""
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def is_text(head: bytes) -> bool:
    return b"\x00" not in head


def unwrap_edgar(text: str) -> str:
    """The bodies of an EDGAR ``<DOCUMENT>`` (``<TEXT>`` sections); other text is returned unchanged."""
    if not text.lstrip().upper().startswith("<DOCUMENT>"):
        return text
    bodies = _EDGAR_TEXT.findall(text)
    return "\n".join(bodies) if bodies else text


def split_markers(text: str) -> list[str]:
    return _PAGE_MARKER.split(text)


def paginate(text: str, page_chars: int) -> list[str]:
    """Split at blank lines into pages of about ``page_chars``; a longer paragraph becomes a page of its own."""
    pages: list[str] = []
    current = ""
    for block in _BLANK_LINES.split(text):
        if not block.strip():
            continue
        if current and len(current) + len(block) + 2 > page_chars:
            pages.append(current)
            current = ""
        current = f"{current}\n\n{block}" if current else block
    if current:
        pages.append(current)
    return pages


def page_chars(cfg: DecompositionConfig) -> int:
    return max(500, int(cfg.options.get("page_chars") or DEFAULT_PAGE_CHARS))


def to_pages(parts: list[str], text_format: str, paged_by: PagedBy, metadata: dict | None = None) -> list[RawPage]:
    """Numbered pages from text parts, skipping empty ones."""
    texts = [p.strip() for p in parts if p.strip()]
    return [RawPage(page_number=i, text=t, text_format=text_format, metadata={"paged_by": paged_by, **(metadata or {})})
            for i, t in enumerate(texts, start=1)]


def paged(text: str, cfg: DecompositionConfig, text_format: str,
          prepare: Callable[[str], str] = lambda s: s) -> tuple[list[RawPage], PagedBy]:
    """Pages from markers when there are any, otherwise by length; ``prepare`` turns raw text into page text."""
    parts = [p for p in split_markers(text) if p.strip()]
    if len(parts) > 1:
        return to_pages([prepare(p) for p in parts], text_format, "marker"), "marker"
    return to_pages(paginate(prepare(text), page_chars(cfg)), text_format, "size"), "size"


def plain_to_markdown(text: str) -> str:
    """Plain text that renders and chunks as itself: indentation removed (it would be a code block) and
    line-start ``#`` / ``>`` escaped (they would be headings and quotes)."""
    lines = [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return _MD_LINE_START.sub(r"\\\1", "\n".join(lines))


def convert(source: Path, out_dir: Path, cfg: DecompositionConfig) -> ConvertResult:
    text = _EDGAR_TAG.sub("", unwrap_edgar(decode(source.read_bytes())))
    pages, paged_by = paged(text, cfg, TextFormat.MD.value, plain_to_markdown)
    if not pages:
        raise DecompositionError("The text file has no text")
    return ConvertResult(pages=select_pages(pages, cfg), converter="txt", paged_by=paged_by)


SPEC = FormatSpec(
    format=DocumentFormat.TXT,
    mime_types=("text/plain",),
    extensions=(".txt",),
    # The fallback text format: .txt, or any other text without a known extension.
    sniff=lambda head, ext: is_text(head) and ext in (".txt", ""),
    convert=convert,
)
