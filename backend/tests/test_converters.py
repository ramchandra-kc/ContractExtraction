"""Converters for non-PDF formats, on small synthetic files (no database)."""

from __future__ import annotations

import base64
import uuid

import pytest

from contract_extraction.core.errors import InvalidInput
from contract_extraction.decomposition.converters import html, text
from contract_extraction.decomposition.converters.base import RawPage, select_pages
from contract_extraction.domain.config import DecompositionConfig
from contract_extraction.domain.enums import DecompositionMethod, TextFormat

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


def test_select_pages():
    pages = [RawPage(page_number=i, text=str(i), text_format="md") for i in range(1, 6)]
    assert [p.page_number for p in select_pages(pages, _cfg(start_page=2, end_page=3))] == [2, 3]
    assert [p.page_number for p in select_pages(pages, _cfg(end_page=99))] == [1, 2, 3, 4, 5]
    with pytest.raises(InvalidInput):
        select_pages(pages, _cfg(start_page=9))
