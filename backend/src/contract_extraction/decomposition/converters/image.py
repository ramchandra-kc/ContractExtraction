"""Images (scans, photos) → a PDF with one page per frame → OCR through the PDF converter.

The PDF is written to the decomposition folder as ``source.pdf``. Frames are turned upright
from their EXIF orientation, and pages are sized for the config's OCR DPI, so OCR sees each
image at its own pixel size. Image documents always use OCR, whatever the config's PDF method.
"""

from __future__ import annotations

from pathlib import Path

from ...domain.config import DecompositionConfig
from ...domain.enums import DecompositionMethod, DocumentFormat
from . import pdf
from .base import ConvertResult, DecompositionError, FormatSpec

_SIGNATURES = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"II*\x00": "image/tiff",
    b"MM\x00*": "image/tiff",
    b"GIF87a": "image/gif",
    b"GIF89a": "image/gif",
}
_BMP_HEADER_SIZES = {12, 40, 52, 56, 108, 124}


def _is_bmp(head: bytes) -> bool:
    # "BM" alone would match text such as "BMW Supply Agreement": also require zero reserved bytes and a known header size.
    return (len(head) >= 18 and head[:2] == b"BM" and head[6:10] == b"\x00\x00\x00\x00"
            and int.from_bytes(head[14:18], "little") in _BMP_HEADER_SIZES)


def mime_of(head: bytes) -> str | None:
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if _is_bmp(head):
        return "image/bmp"
    return next((mime for sig, mime in _SIGNATURES.items() if head.startswith(sig)), None)


def to_pdf(source: Path, target: Path, dpi: int) -> None:
    """One PDF page per frame, sized so that rendering at ``dpi`` (as OCR does) gives the image's own pixels."""
    from PIL import Image, ImageOps, ImageSequence

    try:
        with Image.open(source) as img:
            frames = [ImageOps.exif_transpose(f).convert("RGB") for f in ImageSequence.Iterator(img)]
    except (OSError, Image.DecompressionBombError) as exc:
        raise DecompositionError(f"Cannot read the image: {exc}") from exc
    # The file's own DPI is ignored: it is often a placeholder (72, 96, even 1).
    frames[0].save(target, "PDF", save_all=True, append_images=frames[1:], resolution=float(dpi))


def convert(source: Path, out_dir: Path, cfg: DecompositionConfig) -> ConvertResult:
    pdf_path = out_dir / "source.pdf"
    to_pdf(source, pdf_path, cfg.dpi)
    ocr = cfg.model_copy(update={"method": DecompositionMethod.OCR})
    return ConvertResult(pages=pdf.extract_pages(pdf_path, out_dir, ocr), converter="image:ocr", paged_by="source",
                         page_sizes=pdf.page_sizes(pdf_path))


SPEC = FormatSpec(
    format=DocumentFormat.IMAGE,
    mime_types=("image/png", "image/jpeg", "image/tiff", "image/gif", "image/bmp", "image/webp"),
    extensions=(".png", ".jpg", ".jpeg", ".tif", ".tiff", ".gif", ".bmp", ".webp"),
    sniff=lambda head, ext: mime_of(head) is not None,
    convert=convert,
    mime_of=lambda head: mime_of(head) or "application/octet-stream",
)
