"""Word (.docx) → HTML through mammoth → the HTML converter.

Pages break where Word last laid them out (``w:lastRenderedPageBreak``, saved by Word with
the file) and at explicit page breaks; generated files without either are split by length.
mammoth embeds images as ``data:`` URIs, which the HTML converter writes to ``images/``.
Only explicit breaks are understood by mammoth, so the rendered ones are rewritten into
explicit ones in a copy of the file; the stored original is never changed.
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from pathlib import Path

from ...core.errors import InvalidInput
from ...domain.config import DecompositionConfig
from ...domain.enums import DocumentFormat
from .base import ConvertResult, DecompositionError, FormatSpec, select_pages
from .html import MARKER, html_pages

log = logging.getLogger(__name__)

DOCUMENT_XML = "word/document.xml"
# A .docx is a zip: refuse ones that inflate beyond this (zip bombs).
MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
_RENDERED_BREAK = re.compile(rb"<w:lastRenderedPageBreak\s*/>")
_PAGE_BREAK_HR = re.compile(r'<hr class="ce-page-break" ?/?>')
_STYLE_MAP = "br[type='page'] => hr.ce-page-break"


def verify(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            total = sum(i.file_size for i in z.infolist())
    except zipfile.BadZipFile as exc:
        raise InvalidInput("The .docx file is not a valid Word document") from exc
    if DOCUMENT_XML not in names:
        raise InvalidInput("The file is a zip archive but not a Word document")
    if total > MAX_UNCOMPRESSED_BYTES:
        raise InvalidInput("The Word document expands to more than 512 MB")


def _with_explicit_breaks(source: Path) -> io.BytesIO:
    """A copy of the .docx whose rendered page breaks are explicit ``w:br w:type="page"``."""
    out = io.BytesIO()
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename == DOCUMENT_XML:
                data = _RENDERED_BREAK.sub(b'<w:br w:type="page"/>', data)
            dst.writestr(info, data)
    out.seek(0)
    return out


def convert(source: Path, out_dir: Path, cfg: DecompositionConfig) -> ConvertResult:
    import mammoth

    verify(source)  # also when a document stored before this check is decomposed again
    try:
        result = mammoth.convert_to_html(_with_explicit_breaks(source), style_map=_STYLE_MAP)
    except (zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise DecompositionError(f"Cannot read the Word document: {exc}") from exc
    for message in result.messages:
        log.debug("mammoth: %s", message.message)
    pages, paged_by = html_pages(_PAGE_BREAK_HR.sub(MARKER, result.value), out_dir, cfg)
    if not pages:
        raise DecompositionError("The Word document has no text")
    return ConvertResult(pages=select_pages(pages, cfg), converter="docx", paged_by=paged_by)


SPEC = FormatSpec(
    format=DocumentFormat.DOCX,
    mime_types=("application/vnd.openxmlformats-officedocument.wordprocessingml.document",),
    extensions=(".docx",),
    # A zip; verify() checks it holds a Word document (the entry list is at the end of the file).
    sniff=lambda head, ext: head.startswith(b"PK\x03\x04") and ext == ".docx",
    convert=convert,
    verify=verify,
)
