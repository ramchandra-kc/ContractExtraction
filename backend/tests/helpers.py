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
