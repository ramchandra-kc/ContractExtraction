from __future__ import annotations

import io
import shutil

import pytest

from contract_extraction.decomposition.service import decompose, relink_images
from contract_extraction.persistence.repositories import ConfigRepo, DocumentRepo
from contract_extraction.persistence.repositories.artifacts import DecompositionRepo
from contract_extraction.persistence import models as m
from sqlalchemy import select


def _document(session, storage, pdf):
    doc, _ = DocumentRepo(session).register(storage.stage(io.BytesIO(pdf.read_bytes()), pdf.name), storage)
    return doc


def _config(session, name: str):
    from contract_extraction.persistence.repositories.config import _decomposition

    return _decomposition(session.scalars(select(m.DecompositionConfig).where(m.DecompositionConfig.name == name)).one())


def test_relink_images():
    md, names = relink_images("see ![](/tmp/out/images/msa.pdf-1-0.png) and ![x](a/b.jpg)", "md")
    assert md == "see ![](images/msa.pdf-1-0.png) and ![x](images/b.jpg)"
    assert names == ["msa.pdf-1-0.png", "b.jpg"]
    html, names = relink_images('<img src="/x/y/z.png" alt="">', "html")
    assert html == '<img src="images/z.png" alt="">' and names == ["z.png"]


def test_pymupdf_decomposition(session, storage, sample_pdf):
    doc = _document(session, storage, sample_pdf)
    cfg = ConfigRepo(session).resolve_pipeline().decomposition
    dec = decompose(session, doc, cfg, storage)

    repo = DecompositionRepo(session)
    pages = repo.pages(dec.id)
    assert [p.page_number for p in pages] == [1, 2, 3]
    assert doc.page_count == 3 and dec.page_count == 3
    assert dec.config_snapshot["method"] == "pymupdf" and dec.converter == "pdf:pymupdf"
    # pymupdf4llm's layout analysis already drops running headers/footers for text PDFs;
    # our repeated-line pass (unit-tested separately) catches what remains, e.g. in OCR output.
    for i, p in enumerate(pages, start=1):
        assert "ACME MASTER SERVICES AGREEMENT" not in p.text
        assert f"Page {i} of 3" not in p.text
        assert p.width and p.height
    assert "Acme Pty Ltd" in pages[0].text
    assert "thirty (30) days" in pages[1].text

    images = repo.images(dec.id)
    assert len(images) == 1
    assert storage.resolve(images[0].storage_path).is_file()
    assert f"images/{images[0].file_name}" in pages[1].text
    assert storage.resolve(dec.storage_dir).joinpath("pages.json").is_file()


def test_each_decomposition_has_its_own_folder(session, storage, sample_pdf):
    doc = _document(session, storage, sample_pdf)
    cfg = ConfigRepo(session).resolve_pipeline().decomposition
    first = decompose(session, doc, cfg, storage)
    second = decompose(session, doc, cfg, storage)
    assert first.storage_dir != second.storage_dir
    assert DecompositionRepo(session).latest_for_document(doc.id).id == second.id


def _text_document(session, storage, name: str, content: str):
    from contract_extraction.ingestion import register_detected

    return register_detected(DocumentRepo(session), storage, storage.stage(io.BytesIO(content.encode()), name))[0]


def test_html_decomposition_removes_running_footers(session, storage):
    # Clause texts differ in words, not only digits: digits are wildcards when looking for repeated lines.
    clauses = ["Definitions apply.", "Fees are monthly.", "Either party may terminate.", "Notices are written."]
    pages = [f"<p>{c}</p><p>Acme Rail confidential</p><p>Page {i}</p>" for i, c in enumerate(clauses, start=1)]
    doc = _text_document(session, storage, "msa.htm",
                         "<html><body>" + '<div style="page-break-before:always"></div>'.join(pages) + "</body></html>")
    assert (doc.format, doc.mime_type) == ("html", "text/html")
    dec = decompose(session, doc, ConfigRepo(session).resolve_pipeline().decomposition, storage)

    rows = DecompositionRepo(session).pages(dec.id)
    assert dec.converter == "html" and dec.page_count == doc.page_count == 4
    assert [p.page_number for p in rows] == [1, 2, 3, 4]
    for clause, p in zip(clauses, rows, strict=True):
        assert p.text.startswith(clause) and "Page" not in p.text
        assert "Page" in p.footer and p.width is None and p.metadata_["paged_by"] == "marker"


def test_pages_by_length_keep_repeated_lines(session, storage):
    block = "Acme Rail confidential\n\n" + "The supplier delivers on time. " * 40
    doc = _text_document(session, storage, "notes.txt", "\n\n".join([block] * 6))
    cfg = ConfigRepo(session).resolve_pipeline().decomposition.model_copy(update={"options": {"page_chars": 1500}})
    dec = decompose(session, doc, cfg, storage)
    rows = DecompositionRepo(session).pages(dec.id)
    assert dec.converter == "txt" and len(rows) > 2
    assert all(p.header is None and p.footer is None for p in rows)


def test_docx_decomposition(session, storage, tmp_path):
    from contract_extraction.ingestion import register_detected
    from helpers import docx_paragraph, make_docx

    path = make_docx(tmp_path / "msa.docx", [docx_paragraph("Services Agreement", style="Heading1"),
                                             docx_paragraph("The fee is $5,000.", before='<w:br w:type="page"/>')])
    doc = register_detected(DocumentRepo(session), storage, storage.stage(io.BytesIO(path.read_bytes()), "msa.docx"))[0]
    dec = decompose(session, doc, ConfigRepo(session).resolve_pipeline().decomposition, storage)
    rows = DecompositionRepo(session).pages(dec.id)
    assert doc.format == "docx" and dec.converter == "docx"
    assert [p.text for p in rows] == ["# Services Agreement", "The fee is $5,000."]


@pytest.mark.ocr
def test_image_decomposition(session, storage, tmp_path):
    if not shutil.which("tesseract"):
        pytest.skip("Tesseract is not installed")
    from contract_extraction.ingestion import register_detected
    from helpers import make_scan

    scan = make_scan(tmp_path / "scan.jpg", ["Acme Rail Pty Ltd supplies sleepers."], fmt="JPEG")
    doc = register_detected(DocumentRepo(session), storage, storage.stage(io.BytesIO(scan.read_bytes()), "scan.jpg"))[0]
    dec = decompose(session, doc, ConfigRepo(session).resolve_pipeline().decomposition, storage)
    rows = DecompositionRepo(session).pages(dec.id)
    assert (doc.format, doc.mime_type, dec.converter) == ("image", "image/jpeg", "image:ocr")
    assert doc.page_count == 1 and "Acme Rail" in rows[0].text and rows[0].width and rows[0].height


@pytest.mark.ocr
@pytest.mark.parametrize("config", ["ocr", "hybrid"])
def test_ocr_methods(session, storage, sample_pdf, config):
    if not shutil.which("tesseract"):
        pytest.skip("Tesseract is not installed")
    doc = _document(session, storage, sample_pdf)
    dec = decompose(session, doc, _config(session, config), storage)
    text = " ".join(p.text for p in DecompositionRepo(session).pages(dec.id))
    assert dec.page_count == 3
    assert "Acme" in text and "Contoso" in text
