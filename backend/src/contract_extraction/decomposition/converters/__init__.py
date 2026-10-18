"""Supported source formats: detection at upload and the converter used at decomposition.

``REGISTRY`` is the single list of supported formats. Upload validation, the error message,
``GET /config/formats`` and the frontend's file picker all derive from it, so supporting a new
format means adding one converter module with a ``SPEC`` and listing it here.
"""

from __future__ import annotations

from pathlib import Path

from ...core.errors import InvalidInput
from . import pdf
from .base import ConvertResult, DecompositionError, FormatSpec, RawPage

__all__ = ["REGISTRY", "ConvertResult", "DecompositionError", "FormatSpec", "RawPage", "accepted", "detect", "spec_for"]

# Sniff order: binary signatures first, then text formats.
REGISTRY: tuple[FormatSpec, ...] = (pdf.SPEC,)

_HEAD_BYTES = 8192


def accepted() -> str:
    return ", ".join(ext for spec in REGISTRY for ext in spec.extensions)


def detect(path: Path, filename: str) -> FormatSpec:
    """The format of a stored file, from its content and (for text formats) its extension."""
    with path.open("rb") as fh:
        head = fh.read(_HEAD_BYTES)
    if not head:
        raise InvalidInput("The file is empty")
    ext = Path(filename).suffix.lower()
    for spec in REGISTRY:
        if spec.sniff(head, ext):
            return spec
    raise InvalidInput(f"Unsupported file type; accepted: {accepted()}")


def spec_for(fmt: str) -> FormatSpec:
    for spec in REGISTRY:
        if spec.format == fmt:
            return spec
    raise InvalidInput(f"No converter for format {fmt!r}")
