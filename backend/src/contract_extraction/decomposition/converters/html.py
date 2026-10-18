"""HTML → pages: sanitised, split at page breaks, converted to Markdown (or kept as HTML).

EDGAR filings are unwrapped first (see ``text.unwrap_edgar``). Scripts, styles, frames, form
controls and web-page navigation are removed, links keep only their text, and layout tables
(one filled cell per row) become paragraphs. Pages break at CSS ``page-break-before`` /
``page-break-after: always``, ``break-before`` / ``break-after: page`` and EDGAR ``<PAGE>``
elements; without any, the text is split by length. Only images embedded as ``data:`` URIs
are kept (written to ``images/``); remote or relative images are never fetched and are
replaced by their alt text.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from pathlib import Path

from ...domain.config import DecompositionConfig
from ...domain.enums import DocumentFormat, TextFormat
from .base import ConvertResult, DecompositionError, FormatSpec, select_pages
from .text import decode, is_text, paged, unwrap_edgar

_DROP = ("script", "style", "noscript", "iframe", "frame", "frameset", "object", "embed", "input",
         "button", "select", "textarea", "svg", "canvas", "template", "head", "meta", "link", "base")
# Kept for their content: ASP.NET pages wrap the whole page in a form.
_UNWRAP = ("a", "form", "font", "span")
_BREAK_BEFORE = re.compile(r"(?:page-)?break-before\s*:\s*(?:always|page)", re.I)
_BREAK_AFTER = re.compile(r"(?:page-)?break-after\s*:\s*(?:always|page)", re.I)
_KEEP_ATTRS = {"src", "alt", "colspan", "rowspan"}
# Plain letters, so neither Markdown nor HTML output escapes it; unlikely to occur in a contract.
MARKER = " CEPAGEBREAK7F3A "
_MARKER_SPLIT = re.compile(r"\s*CEPAGEBREAK7F3A\s*")
_DATA_URI = re.compile(r"^data:image/(png|jpe?g|gif|webp|bmp);base64,(.+)$", re.I | re.S)
_HTML_START = re.compile(rb"<!doctype\s+html|<html[\s>]", re.I)
_BLANK_LINES = re.compile(r"\n[ \t]*\n(?:[ \t]*\n)+")
_TRAILING_SPACE = re.compile(r"[ \t]+\n")


def _save_image(src: str, images_dir: Path) -> str | None:
    """Write a ``data:`` image to ``images_dir``; returns its file name (named by content hash)."""
    match = _DATA_URI.match(src.strip())
    if not match:
        return None
    try:
        data = base64.b64decode(match.group(2), validate=False)
    except (binascii.Error, ValueError):
        return None
    ext = match.group(1).lower().replace("jpeg", "jpg")
    name = f"img-{hashlib.sha256(data).hexdigest()[:16]}.{ext}"
    images_dir.mkdir(parents=True, exist_ok=True)
    (images_dir / name).write_bytes(data)
    return name


def _cells(row) -> list:
    return row.find_all(["td", "th"], recursive=False)


def _flatten_layout_tables(soup) -> None:
    """Tables used for layout (at most one non-empty cell per row) become paragraphs; empty rows are dropped.

    Innermost tables first, so a layout table nested in a real table is flattened inside its cell.
    """
    for table in reversed(soup.find_all("table")):
        rows = [r for r in table.find_all("tr") if r.find_parent("table") is table]
        filled = [[c for c in _cells(r) if c.get_text(strip=True) or c.find("img")] for r in rows]
        if all(len(cells) <= 1 for cells in filled):
            paragraphs = []
            for cells in filled:
                for cell in cells:
                    p = soup.new_tag("p")
                    p.extend(list(cell.contents))
                    paragraphs.append(p)
            table.replace_with(*paragraphs) if paragraphs else table.decompose()
            continue
        for row, cells in zip(rows, filled, strict=True):
            if not cells:
                row.decompose()


def sanitise(html: str, images_dir: Path):  # -> bs4.BeautifulSoup
    """Parse and clean ``html``; page breaks become ``MARKER`` text nodes."""
    from bs4 import BeautifulSoup, Comment

    # lxml closes <p> like browsers do; html.parser nests unclosed paragraphs (EDGAR has hundreds) until recursion fails.
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(_DROP):
        tag.decompose()
    # Web pages: site navigation and page header/footer (an article's own header stays).
    for tag in soup.find_all(["nav", "aside"]) + soup.find_all(attrs={"role": "navigation"}):
        tag.decompose()
    for tag in soup.find_all(["header", "footer"]):
        if not tag.find_parent(["article", "main"]):
            tag.decompose()
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()
    for img in soup.find_all("img"):
        name = _save_image(str(img.get("src") or ""), images_dir)
        if name is None:
            alt = str(img.get("alt") or "").strip()
            img.replace_with(alt)
        else:
            img.attrs = {"src": name, "alt": str(img.get("alt") or "")}
    for page in soup.find_all("page"):  # EDGAR <PAGE> inside HTML
        page.insert_before(MARKER)
        page.unwrap()
    for tag in soup.find_all(style=True):
        style = str(tag.get("style"))
        if _BREAK_BEFORE.search(style):
            tag.insert_before(MARKER)
        if _BREAK_AFTER.search(style):
            tag.insert_after(MARKER)
    for tag in soup.find_all(_UNWRAP):
        tag.unwrap()
    _flatten_layout_tables(soup)
    for tag in soup.find_all(True):  # the rest is presentation; dropping it keeps HTML output small
        tag.attrs = {k: v for k, v in tag.attrs.items() if k in _KEEP_ATTRS}
    return soup


def to_markdown(soup) -> str:
    from markdownify import MarkdownConverter

    md = MarkdownConverter(heading_style="ATX", bullets="-", escape_misc=False).convert_soup(soup)
    md = md.replace("\xa0", " ")
    return _BLANK_LINES.sub("\n\n", _TRAILING_SPACE.sub("\n", md)).strip()


def body_html(soup) -> str:
    body = soup.body or soup
    return body.decode_contents().replace("\xa0", " ").strip()


def html_pages(html: str, out_dir: Path, cfg: DecompositionConfig):
    """Pages of an HTML string (also used for email bodies and DOCX output)."""
    soup = sanitise(unwrap_edgar(html), out_dir / "images")
    md = cfg.text_format == TextFormat.MD
    text = to_markdown(soup) if md else body_html(soup)
    # Markers split pages; text.paged also falls back to pages by length.
    return paged(_MARKER_SPLIT.sub("\f", text), cfg, TextFormat.MD.value if md else TextFormat.HTML.value)


def convert(source: Path, out_dir: Path, cfg: DecompositionConfig) -> ConvertResult:
    pages, paged_by = html_pages(decode(source.read_bytes()), out_dir, cfg)
    if not pages:
        raise DecompositionError("The HTML file has no text")
    return ConvertResult(pages=select_pages(pages, cfg), converter="html", paged_by=paged_by)


def _sniff(head: bytes, ext: str) -> bool:
    if not is_text(head):
        return False
    return ext in (".htm", ".html") or (ext == "" and bool(_HTML_START.search(head)))


SPEC = FormatSpec(
    format=DocumentFormat.HTML,
    mime_types=("text/html",),
    extensions=(".htm", ".html"),
    sniff=_sniff,
    convert=convert,
)
