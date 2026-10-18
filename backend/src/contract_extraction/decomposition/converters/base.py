"""What every converter returns, and how a format is declared.

A converter turns one stored source file into pages. Image files it extracts go to
``<out_dir>/images/`` and are referenced from the page text by file name; the
decomposition service records them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ...core.errors import InvalidInput
from ...domain.config import DecompositionConfig
from ...domain.enums import DocumentFormat

# source: the file has real pages (PDF, image). marker: text split at page-break markers.
# size: no markers, split by length; such pages have no repeating headers or footers.
PagedBy = Literal["source", "marker", "size"]


class DecompositionError(Exception):
    """The converter failed on this file."""


@dataclass
class RawPage:
    page_number: int
    text: str
    text_format: str
    metadata: dict[str, Any] = field(default_factory=dict)
    page_boxes: list[Any] = field(default_factory=list)


@dataclass(frozen=True)
class ConvertResult:
    pages: list[RawPage]
    converter: str
    paged_by: PagedBy
    # Page number → (width, height) for every page of the source; empty for text formats.
    page_sizes: dict[int, tuple[float, float]] = field(default_factory=dict)


@dataclass(frozen=True)
class FormatSpec:
    format: DocumentFormat
    # The first mime type is the one stored for the document.
    mime_types: tuple[str, ...]
    extensions: tuple[str, ...]
    # (first bytes of the file, lower-case extension with the dot) → is it this format?
    sniff: Callable[[bytes, str], bool]
    convert: Callable[[Path, Path, DecompositionConfig], ConvertResult]

    @property
    def mime_type(self) -> str:
        return self.mime_types[0]


def page_indexes(cfg: DecompositionConfig, total: int) -> list[int]:
    """0-based page indexes from the optional 1-based ``start_page`` / ``end_page`` options."""
    start = int(cfg.options.get("start_page") or 1)
    end = int(cfg.options.get("end_page") or total)
    end = min(end, total)
    if total < 1 or not 1 <= start <= end:
        raise InvalidInput(f"Invalid page range {start}-{end} for a {total}-page document")
    return list(range(start - 1, end))


def select_pages(pages: list[RawPage], cfg: DecompositionConfig) -> list[RawPage]:
    """The ``start_page`` / ``end_page`` range of pages a converter made itself (PDFs pass the range to pdf-converter)."""
    return [pages[i] for i in page_indexes(cfg, len(pages))]
