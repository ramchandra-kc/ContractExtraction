"""Test helpers shared by several test modules (pytest puts this folder on sys.path)."""

from __future__ import annotations

import hashlib

BODY = [
    "This Master Services Agreement is made between Acme Pty Ltd (the Customer) and Contoso Limited (the Supplier). "
    "The Supplier will deliver the services described in Schedule 1.",
    "Payment terms: invoices are payable within thirty (30) days of receipt. Late payments attract interest of 2% per month.",
    "Force majeure: neither party is liable for delays caused by events beyond its reasonable control, including floods and strikes.",
]


def make_pdf(path, pages: list[str] = BODY, header: str = "ACME MASTER SERVICES AGREEMENT", with_image: bool = True):
    """A small text PDF: a repeating header, 'Page n of N' footers, body text, and an image on page 2."""
    import pymupdf

    doc = pymupdf.open()
    for i, body in enumerate(pages, start=1):
        page = doc.new_page()
        page.insert_text((72, 60), header, fontsize=11)
        page.insert_textbox(pymupdf.Rect(72, 100, 540, 400), body, fontsize=12)
        if with_image and i == 2:
            pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 120, 80), 0)
            pix.clear_with(180)
            page.insert_image(pymupdf.Rect(72, 420, 312, 580), stream=pix.tobytes("png"))
        page.insert_text((72, 780), f"Page {i} of {len(pages)}", fontsize=10)
    doc.save(path)
    doc.close()
    return path


_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
_DOCX_PARTS = {
    "[Content_Types].xml": (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'),
    "_rels/.rels": (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Target="word/document.xml" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"/></Relationships>'),
}


def docx_paragraph(text: str, style: str | None = None, before: str = "") -> str:
    """One ``w:p``; ``before`` is raw run content placed ahead of the text (e.g. a page break)."""
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{ppr}<w:r>{before}<w:t xml:space=\"preserve\">{text}</w:t></w:r></w:p>"


def make_docx(path, paragraphs: list[str]):
    """A minimal .docx (no styles part, so headings map through their style id) from ``docx_paragraph`` strings."""
    import zipfile

    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {_W}><w:body>'
                + "".join(paragraphs) + "</w:body></w:document>")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, xml in _DOCX_PARTS.items():
            z.writestr(name, xml)
        z.writestr("word/document.xml", document)
    return path


def make_scan(path, lines: list[str], fmt: str = "PNG", frames: int = 1, dpi: int = 150, **save):
    """A scanned-looking image: ``lines`` rendered by pymupdf, saved by Pillow (``frames`` > 1 for a multi-page TIFF)."""
    import io

    import pymupdf
    from PIL import Image

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_textbox(pymupdf.Rect(72, 72, 523, 770), "\n\n".join(lines), fontsize=14)
    img = Image.open(io.BytesIO(page.get_pixmap(dpi=dpi).tobytes("png"))).convert("RGB")
    rest = [img.copy() for _ in range(frames - 1)]
    img.save(path, fmt, dpi=(dpi, dpi), **({"save_all": True, "append_images": rest} if rest else {}), **save)
    return path


class HashEmbedder:
    """Deterministic bag-of-words embedder: texts sharing words get similar vectors."""

    def __init__(self, dimension: int = 768):
        self.dimension = dimension
        self.calls = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        out = []
        for text in texts:
            v = [0.0] * self.dimension
            for word in text.lower().split():
                v[int(hashlib.md5(word.strip(".,:;()?").encode()).hexdigest(), 16) % self.dimension] += 1.0
            out.append(v)
        return out
