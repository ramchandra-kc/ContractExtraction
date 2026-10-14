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
    assert dec.config_snapshot["method"] == "pymupdf"
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
