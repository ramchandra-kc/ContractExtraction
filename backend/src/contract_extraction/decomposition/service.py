"""Decomposition stage: stored PDF → converter → header/footer removal → pages and images in the database.

Files are written to ``<code>/decompositions/<decomposition id>/`` (converter JSON in
``json/``, images in ``images/``, final pages in ``pages.json``); every decomposition has its
own folder, so earlier rows stay valid.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import time
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from ..domain.config import DecompositionConfig
from ..domain.enums import TextFormat
from ..persistence import models as m
from ..persistence.repositories.artifacts import DecompositionRepo, NewImage, NewPage
from ..storage import FileStorage
from .converter import convert
from .headers_footers import PageText, strip_headers_footers

log = logging.getLogger(__name__)

_MD_IMAGE = re.compile(r"(!\[[^\]]*\]\()([^)\s]+)(\))")
_HTML_IMAGE = re.compile(r"""(<img\b[^>]*?\bsrc=["'])([^"']+)(["'])""", re.I)


def relink_images(text: str, text_format: str) -> tuple[str, list[str]]:
    """Point image references at ``images/<file>`` (relative to the decomposition folder).

    Returns the rewritten text and the referenced file names.
    """
    names: list[str] = []
    pattern = _MD_IMAGE if text_format == TextFormat.MD else _HTML_IMAGE

    def repl(match: re.Match[str]) -> str:
        name = Path(match.group(2)).name
        names.append(name)
        return f"{match.group(1)}images/{name}{match.group(3)}"

    return pattern.sub(repl, text), names


def _page_sizes(pdf_path: Path) -> dict[int, tuple[float, float]]:
    import pymupdf

    with pymupdf.open(pdf_path) as doc:
        return {i + 1: (page.rect.width, page.rect.height) for i, page in enumerate(doc)}


def _image_size(path: Path) -> tuple[int | None, int | None]:
    import pymupdf

    try:
        pix = pymupdf.Pixmap(str(path))
        return pix.width, pix.height
    except Exception:  # noqa: BLE001 - size is informational only
        return None, None


def decompose(session: Session, document: m.Document, cfg: DecompositionConfig, storage: FileStorage) -> m.Decomposition:
    decomposition_id = uuid.uuid4()
    out_dir = storage.decomposition_dir(document.code, str(decomposition_id))
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = storage.resolve(document.storage_path)
    started = time.perf_counter()

    try:
        raw = convert(pdf_path, out_dir, cfg)
        referenced: dict[int, list[str]] = {}
        texts: list[PageText] = []
        for page in raw:
            text, names = relink_images(page.text, page.text_format)
            referenced[page.page_number] = names
            texts.append(PageText(text=text))
        if cfg.remove_headers_footers:
            strip_headers_footers(texts)

        sizes = _page_sizes(pdf_path)
        pages = [
            NewPage(page_number=p.page_number, text=t.text, text_format=p.text_format, header=t.header, footer=t.footer,
                    width=sizes.get(p.page_number, (None, None))[0], height=sizes.get(p.page_number, (None, None))[1],
                    metadata={k: v for k, v in p.metadata.items() if k != "page_number"})
            for p, t in zip(raw, texts, strict=True)
        ]
        # Only images referenced from a page's text are recorded; the converter's file names
        # do not reliably encode the page.
        images_dir = out_dir / "images"
        images = [
            NewImage(page_number=page, file_name=name, storage_path=(images_dir / name).relative_to(storage.root).as_posix(),
                     width=w, height=h)
            for page, names in referenced.items()
            for name in dict.fromkeys(names)
            if (images_dir / name).is_file()
            for w, h in [_image_size(images_dir / name)]
        ]
        (out_dir / "pages.json").write_text(
            json.dumps([p.__dict__ for p in pages], ensure_ascii=False, indent=2), encoding="utf-8")
    except BaseException:
        shutil.rmtree(out_dir, ignore_errors=True)
        raise

    duration_ms = int((time.perf_counter() - started) * 1000)
    dec = DecompositionRepo(session).create(
        decomposition_id=decomposition_id, document_id=document.id, config_id=cfg.id,
        config_snapshot=cfg.model_dump(mode="json"), storage_dir=out_dir.relative_to(storage.root).as_posix(),
        duration_ms=duration_ms, pages=pages, images=images,
    )
    document.page_count = len(sizes)
    log.info("Decomposed %s: %d pages, %d images in %d ms", document.code, len(pages), len(images), duration_ms)
    return dec
