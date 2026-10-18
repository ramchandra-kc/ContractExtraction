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


@pytest.mark.parametrize("name, content, expected", [
    ("offer.htm", b"<p>Offer</p>", DocumentFormat.HTML),
    ("offer.HTML", b"plain words, but the extension says HTML", DocumentFormat.HTML),
    ("offer", b"<!DOCTYPE html><html><body>Offer</body></html>", DocumentFormat.HTML),
    # EDGAR text filings start like SGML; the extension keeps them plain text.
    ("ex10.txt", b"<DOCUMENT>\n<TYPE>EX-10\n<TEXT>\n<html> mentioned in text\n</TEXT>", DocumentFormat.TXT),
    ("notes", b"Just some contract text.", DocumentFormat.TXT),
    # Binary signatures win over the extension.
    ("scan.txt", b"%PDF-1.4 ...", DocumentFormat.PDF),
])
def test_text_formats(tmp_path, name, content, expected):
    spec = detect(*_file(tmp_path, name, content))
    assert spec.format == expected
    assert spec.mime_type == {"html": "text/html", "txt": "text/plain", "pdf": "application/pdf"}[expected]


@pytest.mark.parametrize("name", ["a.txt", "a.htm", "a"])
def test_binary_is_not_text(tmp_path, name):
    with pytest.raises(InvalidInput, match="Unsupported"):
        detect(*_file(tmp_path, name, b"PK\x03\x04\x00\x00 binary"))


def test_empty_file(tmp_path):
    with pytest.raises(InvalidInput, match="empty"):
        detect(*_file(tmp_path, "a.pdf", b""))


def test_unsupported_content(tmp_path):
    with pytest.raises(InvalidInput, match=r"Unsupported file type; accepted: \.pdf, \.htm, \.html, \.txt"):
        detect(*_file(tmp_path, "a.pdf", b"\x00\x01\x02 not a document"))
    with pytest.raises(InvalidInput, match="Unsupported"):  # text with an unknown extension
        detect(*_file(tmp_path, "a.csv", b"name,value"))


def test_spec_for():
    assert spec_for("pdf").format == DocumentFormat.PDF
    with pytest.raises(InvalidInput):
        spec_for("nope")
