from __future__ import annotations

import pytest

from contract_extraction.core.errors import InvalidInput
from contract_extraction.decomposition.converters import REGISTRY, accepted, detect, spec_for
from contract_extraction.domain.enums import DocumentFormat


def _file(tmp_path, name: str, content: bytes):
    path = tmp_path / "staged"
    path.write_bytes(content)
    return path, name


def test_registry_formats_are_unique_and_known():
    formats = [s.format for s in REGISTRY]
    assert len(formats) == len(set(formats)) and all(isinstance(f, DocumentFormat) for f in formats)
    assert all(ext.startswith(".") and ext == ext.lower() for s in REGISTRY for ext in s.extensions)
    assert ".pdf" in accepted()


@pytest.mark.parametrize("name", ["contract.pdf", "contract.PDF", "contract.bin", "contract"])
def test_pdf_is_detected_by_content(tmp_path, name):
    spec = detect(*_file(tmp_path, name, b"%PDF-1.7\n..."))
    assert spec.format == DocumentFormat.PDF and spec.mime_type == "application/pdf"


def test_empty_file(tmp_path):
    with pytest.raises(InvalidInput, match="empty"):
        detect(*_file(tmp_path, "a.pdf", b""))


def test_unsupported_content(tmp_path):
    with pytest.raises(InvalidInput, match="Unsupported file type; accepted: .pdf"):
        detect(*_file(tmp_path, "a.pdf", b"\x00\x01\x02 not a document"))


def test_spec_for():
    assert spec_for("pdf").format == DocumentFormat.PDF
    with pytest.raises(InvalidInput):
        spec_for("nope")
