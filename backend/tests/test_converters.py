"""Converters for non-PDF formats, on small synthetic files (no database; OCR tests need Tesseract)."""

from __future__ import annotations

import base64
import shutil
import uuid
import zipfile

import pytest

from contract_extraction.core.errors import InvalidInput
from contract_extraction.decomposition.converters import docx, html, image, text
from contract_extraction.decomposition.converters.base import RawPage, select_pages
from contract_extraction.domain.config import DecompositionConfig
from contract_extraction.domain.enums import DecompositionMethod, TextFormat
from helpers import docx_paragraph, make_docx, make_scan

# A 1×1 transparent PNG.
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def _cfg(text_format: str = "md", **options) -> DecompositionConfig:
    return DecompositionConfig(id=uuid.uuid4(), name="t", method=DecompositionMethod.PYMUPDF,
                               text_format=TextFormat(text_format), keep_invisible_text=True,
                               remove_headers_footers=True, ocr_language="eng", dpi=200, options=options)


def _convert(module, tmp_path, content: str | bytes, name: str, cfg: DecompositionConfig | None = None):
    source = tmp_path / name
    source.write_bytes(content.encode() if isinstance(content, str) else content)
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    return module.convert(source, out, cfg or _cfg()), out


EDGAR_TXT = """<DOCUMENT>
<TYPE>EX-10.1
<SEQUENCE>2
<FILENAME>ex10-1.txt
<DESCRIPTION>SUPPLY AGREEMENT
<TEXT>
                              SUPPLY AGREEMENT

      This Supply Agreement is made between Acme Rail Pty Ltd and Jane Sample.
# 1 is not a heading here
> nor a quote

                                      1
<PAGE>
<TABLE>
<CAPTION>
<S>                 <C>
Price               $100
</TABLE>
                                      2
<PAGE>
      2.  Term. The term is two (2) years.
</TEXT>
</DOCUMENT>
"""


def test_txt_edgar_wrapper_markers_and_markdown(tmp_path):
    result, _ = _convert(text, tmp_path, EDGAR_TXT, "ex.txt")
    assert (result.converter, result.paged_by) == ("txt", "marker")
    assert [p.page_number for p in result.pages] == [1, 2, 3]
    first, second, third = (p.text for p in result.pages)
    assert first.startswith("SUPPLY AGREEMENT") and "<TYPE>" not in first and "ex10-1.txt" not in first
    assert "\n\\# 1 is not a heading here\n\\> nor a quote" in first
    assert "Price               $100" in second and "<S>" not in second and "<TABLE>" not in second
    assert third == "2.  Term. The term is two (2) years."
    assert all(p.text_format == "md" and p.metadata["paged_by"] == "marker" for p in result.pages)


def test_txt_form_feeds_are_page_breaks(tmp_path):
    result, _ = _convert(text, tmp_path, "one\fTwo\f\fthree", "a.txt")
    assert [p.text for p in result.pages] == ["one", "Two", "three"]


def test_txt_without_markers_is_split_by_length(tmp_path):
    paragraphs = [f"Clause {i}. " + "The supplier shall deliver the goods. " * 20 + "End." for i in range(12)]
    result, _ = _convert(text, tmp_path, "\n\n".join(paragraphs), "a.txt", _cfg(page_chars=2000))
    assert result.paged_by == "size" and len(result.pages) > 3
    assert all(len(p.text) <= 2000 + len(paragraphs[0]) for p in result.pages)
    assert "\n\n".join(p.text for p in result.pages) == "\n\n".join(paragraphs)  # nothing lost or split mid-paragraph


def test_decode_falls_back_to_cp1252():
    assert text.decode("Caf\xe9 “quoted”".encode("cp1252")) == "Café “quoted”"
    assert text.decode("BOM".encode("utf-8-sig")) == "BOM"
    assert text.decode(b"\x81\x8d") == "\x81\x8d"  # undefined in cp1252 → Latin-1


def test_empty_text_file_fails(tmp_path):
    with pytest.raises(text.DecompositionError):
        _convert(text, tmp_path, " \n\n ", "a.txt")


HTML = f"""<html><head><title>x</title><style>p {{color: red}}</style><script>alert(1)</script></head>
<body>
<nav><a href="/">Home</a></nav>
<h1>Services Agreement</h1>
<p>Between <a href="https://example.com">Acme Rail Pty Ltd</a> and Jane Sample.</p>
<img src="https://example.com/logo.png" alt="Acme logo">
<div style="page-break-before: always"><h2>1. Fees</h2><p>The fee is $5,000.</p>
<img src="data:image/png;base64,{base64.b64encode(PNG).decode()}" alt="signature"></div>
<table><tr><td></td></tr><tr><td>Clause text in a layout table.</td></tr><tr><td></td><td></td></tr></table>
<table><tr><th>Item</th><th>Rate</th></tr><tr><td></td><td></td></tr><tr><td>Hourly</td><td>$200</td></tr></table>
<p style="page-break-after:always">End of schedule.</p>
<p>Signed by the parties.</p>
<!-- a comment -->
</body></html>"""


def test_html_to_markdown_pages(tmp_path):
    result, out = _convert(html, tmp_path, HTML, "a.htm")
    assert (result.converter, result.paged_by) == ("html", "marker")
    first, second, third = (p.text for p in result.pages)
    assert first.startswith("# Services Agreement")
    assert "Between Acme Rail Pty Ltd and Jane Sample." in first and "example.com" not in first
    assert "Acme logo" in first and "Home" not in first and "alert" not in first and "color" not in first
    assert second.startswith("## 1. Fees")
    assert "Clause text in a layout table." in second and "| Clause" not in second  # flattened
    assert "| Item | Rate |" in second and "| Hourly | $200 |" in second and "|  |  |" not in second
    assert second.rstrip().endswith("End of schedule.")
    assert third == "Signed by the parties."
    images = list((out / "images").iterdir())
    assert len(images) == 1 and images[0].read_bytes() == PNG
    assert f"![signature]({images[0].name})" in second


@pytest.mark.parametrize("number", ["1.", "(e)", "2.1", "iv)", "(iii)", "12.3.4", "a."])
def test_html_numbered_clause_tables_become_paragraphs(tmp_path, number):
    doc = (f"<table><tr><td></td><td>{number}</td><td>Construction. The parties drafted this jointly.</td></tr>"
           "<tr><td></td><td></td><td>Continued text of the clause.</td></tr></table>")
    result, _ = _convert(html, tmp_path, doc, "a.htm")
    assert result.pages[0].text == f"{number} Construction. The parties drafted this jointly.\n\nContinued text of the clause."


@pytest.mark.parametrize("first", ["Hourly", "Item", "2026", "$5"])
def test_html_two_column_data_tables_stay_tables(tmp_path, first):
    doc = f"<table><tr><td>{first}</td><td>$200</td></tr><tr><td>Daily</td><td>$1,500</td></tr></table>"
    result, _ = _convert(html, tmp_path, doc, "a.htm")
    assert f"| {first} | $200 |" in result.pages[0].text


def test_html_text_format_keeps_clean_html(tmp_path):
    result, _ = _convert(html, tmp_path, HTML, "a.htm", _cfg("html"))
    first = result.pages[0].text
    assert result.pages[0].text_format == "html" and len(result.pages) == 3
    assert "<h1>Services Agreement</h1>" in first and "style=" not in first and "<script" not in first
    assert "CEPAGEBREAK" not in " ".join(p.text for p in result.pages)


def test_html_edgar_page_tags_and_unclosed_paragraphs(tmp_path):
    # EDGAR HTML often never closes <P>; a naive parser nests them until recursion fails.
    body = "".join(f"<P>Paragraph {i}." for i in range(1500))
    doc = f"<DOCUMENT>\n<TYPE>EX-10\n<TEXT>\n<HTML><BODY>{body}<PAGE><P>After the break.</BODY></HTML>\n</TEXT>\n</DOCUMENT>"
    result, _ = _convert(html, tmp_path, doc, "a.htm")
    assert [p.text.splitlines()[0] for p in result.pages] == ["Paragraph 0.", "After the break."]
    assert "<TYPE>" not in result.pages[0].text and "Paragraph 1499." in result.pages[0].text


def test_html_without_breaks_is_split_by_length(tmp_path):
    doc = "<html><body>" + "".join(f"<p>Clause {i}. {'Text. ' * 100}</p>" for i in range(10)) + "</body></html>"
    result, _ = _convert(html, tmp_path, doc, "a.html", _cfg(page_chars=1500))
    assert result.paged_by == "size" and len(result.pages) >= 5


# ---- images -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("fmt, mime", [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("TIFF", "image/tiff"),
                                       ("GIF", "image/gif"), ("BMP", "image/bmp"), ("WEBP", "image/webp")])
def test_image_mime_from_signature(tmp_path, fmt, mime):
    path = make_scan(tmp_path / "scan", ["Acme Rail"], fmt=fmt, dpi=30)
    assert image.mime_of(path.read_bytes()[:64]) == mime


@pytest.mark.parametrize("head", [b"BMW Supply Agreement between Acme Rail", b"BM", b"GIF8", b"RIFF1234WAVE"])
def test_text_is_not_an_image(head):
    assert image.mime_of(head) is None


def test_image_to_pdf_pages_upright_and_sized(tmp_path):
    import pymupdf
    from PIL import Image

    tiff = make_scan(tmp_path / "scan.tiff", ["Acme Rail"], fmt="TIFF", frames=3, dpi=100)
    pixels = Image.open(tiff).width
    image.to_pdf(tiff, tmp_path / "a.pdf", dpi=200)
    with pymupdf.open(tmp_path / "a.pdf") as doc:
        assert doc.page_count == 3
        # Rendering at the OCR DPI gives the image's own pixels, whatever DPI the file claims (here 100).
        assert doc[0].get_pixmap(dpi=200).width == pixels

    # A phone photo stored sideways with EXIF orientation 6 (rotate 90° clockwise to view).
    photo = Image.new("RGB", (400, 300), "white")
    exif = photo.getexif()
    exif[0x0112] = 6
    photo.save(tmp_path / "photo.jpg", "JPEG", exif=exif)
    image.to_pdf(tmp_path / "photo.jpg", tmp_path / "b.pdf", dpi=200)
    with pymupdf.open(tmp_path / "b.pdf") as doc:
        assert doc[0].rect.width < doc[0].rect.height  # upright: portrait


def test_unreadable_image(tmp_path):
    (tmp_path / "bad.png").write_bytes(b"\x89PNG\r\n\x1a\n not really")
    with pytest.raises(image.DecompositionError, match="Cannot read the image"):
        image.to_pdf(tmp_path / "bad.png", tmp_path / "x.pdf", 200)


@pytest.mark.ocr
def test_image_ocr(tmp_path):
    if not shutil.which("tesseract"):
        pytest.skip("Tesseract is not installed")
    scan = make_scan(tmp_path / "scan.tiff", ["SUPPLY AGREEMENT", "Acme Rail Pty Ltd supplies sleepers to Jane Sample."],
                     fmt="TIFF", frames=2)
    result, out = _convert(image, tmp_path, scan.read_bytes(), "scan.tiff", _cfg())  # the config's method is pymupdf
    assert (result.converter, result.paged_by) == ("image:ocr", "source")
    assert [p.page_number for p in result.pages] == [1, 2] and sorted(result.page_sizes) == [1, 2]
    assert "Acme Rail" in result.pages[0].text and "Jane Sample" in result.pages[1].text
    assert (out / "source.pdf").is_file()


# ---- docx ------------------------------------------------------------------------------------------


def test_docx_pages_at_rendered_and_explicit_breaks(tmp_path):
    path = make_docx(tmp_path / "msa.docx", [
        docx_paragraph("Services Agreement", style="Heading1"),
        docx_paragraph("Between Acme Rail Pty Ltd and Jane Sample."),
        docx_paragraph("The fee is $5,000.", before="<w:lastRenderedPageBreak/>"),
        docx_paragraph("Signed by the parties.", before='<w:br w:type="page"/>'),
    ])
    result, _ = _convert(docx, tmp_path, path.read_bytes(), "msa.docx")
    assert (result.converter, result.paged_by) == ("docx", "marker")
    assert [p.text for p in result.pages] == ["# Services Agreement\n\nBetween Acme Rail Pty Ltd and Jane Sample.",
                                              "The fee is $5,000.", "Signed by the parties."]
    with zipfile.ZipFile(path) as z:  # the stored original is not changed
        assert b"lastRenderedPageBreak" in z.read("word/document.xml")


def test_docx_without_breaks_is_split_by_length(tmp_path):
    path = make_docx(tmp_path / "a.docx", [docx_paragraph(f"Clause {i}. " + "Text. " * 80) for i in range(10)])
    result, _ = _convert(docx, tmp_path, path.read_bytes(), "a.docx", _cfg(page_chars=1200))
    assert result.paged_by == "size" and len(result.pages) >= 4


def test_docx_verify(tmp_path, monkeypatch):
    good = make_docx(tmp_path / "a.docx", [docx_paragraph("Text")])
    docx.verify(good)
    with zipfile.ZipFile(tmp_path / "other.docx", "w") as z:
        z.writestr("readme.txt", "not Word")
    with pytest.raises(InvalidInput, match="not a Word document"):
        docx.verify(tmp_path / "other.docx")
    (tmp_path / "broken.docx").write_bytes(b"PK\x03\x04 truncated")
    with pytest.raises(InvalidInput, match="not a valid Word document"):
        docx.verify(tmp_path / "broken.docx")
    monkeypatch.setattr(docx, "MAX_UNCOMPRESSED_BYTES", 100)
    with pytest.raises(InvalidInput, match="expands"):
        docx.verify(good)


def test_select_pages():
    pages = [RawPage(page_number=i, text=str(i), text_format="md") for i in range(1, 6)]
    assert [p.page_number for p in select_pages(pages, _cfg(start_page=2, end_page=3))] == [2, 3]
    assert [p.page_number for p in select_pages(pages, _cfg(end_page=99))] == [1, 2, 3, 4, 5]
    with pytest.raises(InvalidInput):
        select_pages(pages, _cfg(start_page=9))
