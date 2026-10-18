"""PDF → pages through the pdf-converter library (pymupdf, ocr or hybrid, from the config's method).

The library writes ``<out>/json/*.json`` (page objects with ``text``, ``page_boxes``,
``metadata.page_number`` and ``text_format``) and ``<out>/images/``. It prints progress as
JSON lines on stdout and its pymupdf4llm hooks are process wide, so calls are serialised
and stdout is turned into log records.
"""

from __future__ import annotations

import contextlib
import importlib
import io
import json
import logging
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ...core.errors import InvalidInput
from ...domain.config import DecompositionConfig
from ...domain.enums import DecompositionMethod, DocumentFormat
from .base import ConvertResult, DecompositionError, FormatSpec, RawPage

log = logging.getLogger(__name__)
_library_log = logging.getLogger("pdf_converter")
_LOCK = threading.Lock()


class _ProgressToLog(io.TextIOBase):
    """Turns the library's JSON progress lines on stdout into log records."""

    def __init__(self) -> None:
        self._buf = ""

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._emit(line)
        return len(text)

    def flush(self) -> None:
        if self._buf:
            self._emit(self._buf)
            self._buf = ""

    @staticmethod
    def _emit(line: str) -> None:
        line = line.strip()
        if not line:
            return
        try:
            msg = json.loads(line)
        except ValueError:
            _library_log.debug("%s", line)
            return
        if isinstance(msg, dict) and msg.get("type") == "progress":
            level = str(msg.get("level", "INFO")).upper()
            if level != "DATA":  # machine-readable file list, also in the return value
                _library_log.log(getattr(logging, level, logging.INFO), "%s", msg.get("message", ""))
        else:
            _library_log.debug("%s", line)


@contextlib.contextmanager
def _keep_invisible_text(enabled: bool) -> Iterator[None]:
    """Make pymupdf4llm keep invisible text for the duration of one conversion.

    Scans with an OCR text layer render that text invisibly (alpha 0); pymupdf4llm drops it
    by default, which leaves such pages empty.
    """
    patched: list[tuple[Any, Any]] = []
    if enabled:
        for name in ("pymupdf4llm.helpers.document_layout", "pymupdf4llm.helpers.pymupdf_rag"):
            try:
                module = importlib.import_module(name)
            except ImportError:
                continue
            original = getattr(module, "get_raw_lines", None)
            if original is None:
                continue

            def keep(*args: Any, __orig: Any = original, **kwargs: Any) -> Any:
                kwargs["ignore_invisible"] = False
                return __orig(*args, **kwargs)

            module.get_raw_lines = keep
            patched.append((module, original))
    try:
        yield
    finally:
        for module, original in patched:
            module.get_raw_lines = original


def page_count(pdf_path: Path) -> int:
    import pymupdf

    with pymupdf.open(pdf_path) as doc:
        return doc.page_count


def page_indexes(cfg: DecompositionConfig, total: int) -> list[int]:
    """0-based page indexes from the optional 1-based ``start_page`` / ``end_page`` options."""
    start = int(cfg.options.get("start_page") or 1)
    end = int(cfg.options.get("end_page") or total)
    end = min(end, total)
    if total < 1 or not 1 <= start <= end:
        raise InvalidInput(f"Invalid page range {start}-{end} for a {total}-page document")
    return list(range(start - 1, end))


def _extract_function(method: str) -> Any:
    if method == DecompositionMethod.PYMUPDF:
        from pdf_converter.pymupdf import extract_with_pymupdf
        return extract_with_pymupdf
    if method == DecompositionMethod.OCR:
        from pdf_converter.ocr import extract_with_ocr
        return extract_with_ocr
    if method == DecompositionMethod.HYBRID:
        from pdf_converter.hybrid import extract_with_hybrid
        return extract_with_hybrid
    raise InvalidInput(f"Unknown decomposition method: {method!r}")


def page_sizes(pdf_path: Path) -> dict[int, tuple[float, float]]:
    import pymupdf

    with pymupdf.open(pdf_path) as doc:
        return {i + 1: (page.rect.width, page.rect.height) for i, page in enumerate(doc)}


def convert(pdf_path: Path, out_dir: Path, cfg: DecompositionConfig) -> ConvertResult:
    return ConvertResult(pages=extract_pages(pdf_path, out_dir, cfg), converter=f"pdf:{cfg.method}",
                         paged_by="source", page_sizes=page_sizes(pdf_path))


def extract_pages(pdf_path: Path, out_dir: Path, cfg: DecompositionConfig) -> list[RawPage]:
    """Run pdf-converter with ``cfg.method``; images land in ``out_dir/images``. Returns pages in page order."""
    pages = page_indexes(cfg, page_count(pdf_path))
    kwargs: dict[str, Any] = {
        "input_path": str(pdf_path.resolve()),
        "output_path": str(out_dir.resolve()),
        "page_nums": pages,
        "text_format": cfg.text_format.value,
        "page_per_json": False,
        "write_text_file": False,
        "draw_page_boxes_pdf": False,
    }
    if cfg.method in (DecompositionMethod.OCR, DecompositionMethod.HYBRID):
        kwargs.update(lang=cfg.ocr_language, dpi=cfg.dpi)

    extract = _extract_function(cfg.method)
    log.info("Converting %s with %s/%s, pages %d-%d", pdf_path.name, cfg.method, cfg.text_format, pages[0] + 1, pages[-1] + 1)
    sink = _ProgressToLog()
    try:
        with _LOCK, _keep_invisible_text(cfg.keep_invisible_text), contextlib.redirect_stdout(sink):
            result = extract(**kwargs)
    except Exception as exc:  # noqa: BLE001 - the library raises untyped errors
        raise DecompositionError(f"PDF conversion failed ({cfg.method}): {exc}") from exc
    finally:
        sink.flush()

    paths = [Path(p) for p in result.get("json_output_paths") or []] or sorted((out_dir / "json").glob("*.json"))
    raw: list[RawPage] = []
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        for obj in data if isinstance(data, list) else [data]:
            meta = obj.get("metadata") or {}
            number = meta.get("page_number") or (pages[len(raw)] + 1 if len(raw) < len(pages) else len(raw) + 1)
            raw.append(RawPage(page_number=int(number), text=obj.get("text") or "",
                               text_format=obj.get("text_format") or cfg.text_format.value,
                               metadata=meta, page_boxes=obj.get("page_boxes") or []))
    if not raw:
        raise DecompositionError("The converter produced no pages")
    return sorted(raw, key=lambda p: p.page_number)


SPEC = FormatSpec(
    format=DocumentFormat.PDF,
    mime_types=("application/pdf",),
    extensions=(".pdf",),
    sniff=lambda head, ext: head.startswith(b"%PDF-"),
    convert=convert,
)
