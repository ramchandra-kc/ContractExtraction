"""Documents: upload, list, detail, original file, pages, images, and queueing runs."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select

from ...core.errors import NotFound
from ...core.settings import Settings
from ...domain.enums import DocumentFormat
from ...ingestion import register_detected
from ...persistence import models as m
from ...persistence.repositories import ConfigRepo, DocumentRepo, RunRepo
from ...persistence.repositories.artifacts import DecompositionRepo
from ...pipeline.options import narrow
from ...storage import FileStorage
from ..deps import SessionDep, get_settings, get_storage
from ..schemas import (
    DecompositionOut,
    DocumentDetail,
    DocumentOut,
    ImageOut,
    Page,
    PageOut,
    PagesOut,
    RunCreate,
    RunOut,
    RunSummary,
)
from .runs import run_out

router = APIRouter(prefix="/documents", tags=["documents"])

# Originals that a browser would run as a page are only ever downloaded, never shown inline.
_DOWNLOAD_ONLY = {DocumentFormat.HTML, DocumentFormat.EML}


def document_out(doc: m.Document, latest: m.Run | None) -> DocumentOut:
    out = DocumentOut.model_validate(doc)
    out.latest_run = RunSummary.model_validate(latest) if latest else None
    return out


@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED,
             responses={200: {"model": DocumentOut, "description": "The same file was uploaded before"}})
def upload_document(
    file: Annotated[UploadFile, File(description="A contract file in one of the formats from GET /config/formats")],
    response: Response,
    session: SessionDep,
    storage: FileStorage = Depends(get_storage),
    settings: Settings = Depends(get_settings),
):
    """Store a contract file. The same content is stored once: uploading it again returns the existing document (200)."""
    staged = storage.stage(file.file, file.filename or "document", settings.storage.max_upload_mb * 1024 * 1024)
    doc, created = register_detected(DocumentRepo(session), storage, staged)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    response.headers["Location"] = f"/api/v1/documents/{doc.id}"
    return document_out(doc, RunRepo(session).latest_for_documents([doc.id]).get(doc.id))


@router.get("", response_model=Page[DocumentOut])
def list_documents(session: SessionDep,
                   limit: int = Query(25, ge=1, le=200), offset: int = Query(0, ge=0)):
    """Newest first, each with its latest run."""
    rows, total = DocumentRepo(session).list(limit, offset)
    latest = RunRepo(session).latest_for_documents([d.id for d in rows])
    return Page[DocumentOut](items=[document_out(d, latest.get(d.id)) for d in rows], total=total, limit=limit, offset=offset)


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(document_id: uuid.UUID, session: SessionDep):
    doc = DocumentRepo(session).get(document_id)
    runs = RunRepo(session).list_for_document(doc.id)
    decompositions = session.scalars(select(m.Decomposition).where(m.Decomposition.document_id == doc.id)
                                     .order_by(m.Decomposition.created_at.desc())).all()
    base = document_out(doc, runs[0] if runs else None)
    return DocumentDetail(
        **base.model_dump(),
        decompositions=[DecompositionOut(id=d.id, config=d.config_snapshot.get("name"), method=d.converter,
                                         text_format=d.config_snapshot.get("text_format"), page_count=d.page_count,
                                         duration_ms=d.duration_ms, created_at=d.created_at) for d in decompositions],
        runs=[RunSummary.model_validate(r) for r in runs],
    )


@router.get("/{document_id}/file", response_class=FileResponse,
            responses={200: {"content": {"application/octet-stream": {}},
                             "description": "The original file, with the document's mime type"}})
def get_document_file(document_id: uuid.UUID, session: SessionDep,
                      storage: FileStorage = Depends(get_storage)):
    doc = DocumentRepo(session).get(document_id)
    path = storage.resolve(doc.storage_path)
    if not path.is_file():
        raise NotFound(f"The stored file of {doc.code} is missing")
    if doc.format in _DOWNLOAD_ONLY:
        return FileResponse(path, media_type=doc.mime_type, filename=doc.original_filename,
                            content_disposition_type="attachment", headers={"Content-Security-Policy": "sandbox"})
    return FileResponse(path, media_type=doc.mime_type, filename=doc.original_filename, content_disposition_type="inline")


@router.get("/{document_id}/pages", response_model=PagesOut)
def get_pages(document_id: uuid.UUID, session: SessionDep, decomposition_id: uuid.UUID | None = None):
    """Pages of a decomposition (the latest one by default) with their images."""
    doc = DocumentRepo(session).get(document_id)
    repo = DecompositionRepo(session)
    dec = repo.get(decomposition_id) if decomposition_id else repo.latest_for_document(doc.id)
    if dec is None or dec.document_id != doc.id:
        raise NotFound(f"No decomposition for {doc.code}" if decomposition_id is None else "Decomposition not found")
    images: dict[uuid.UUID, list[ImageOut]] = {}
    for img in repo.images(dec.id):
        images.setdefault(img.page_id, []).append(ImageOut(
            id=img.id, file_name=img.file_name, width=img.width, height=img.height,
            url=f"/api/v1/documents/{doc.id}/images/{img.id}"))
    return PagesOut(decomposition_id=dec.id, pages=[
        PageOut(page_number=p.page_number, text=p.text, text_format=p.text_format, header=p.header, footer=p.footer,
                width=p.width, height=p.height, source_part=(p.metadata_ or {}).get("source_part"),
                images=images.get(p.id, []))
        for p in repo.pages(dec.id)
    ])


@router.get("/{document_id}/images/{image_id}", response_class=FileResponse,
            responses={200: {"content": {"image/*": {}}, "description": "Image file"}})
def get_image(document_id: uuid.UUID, image_id: uuid.UUID, session: SessionDep,
              storage: FileStorage = Depends(get_storage)):
    img = session.scalars(
        select(m.PageImage).join(m.Page).join(m.Decomposition)
        .where(m.PageImage.id == image_id, m.Decomposition.document_id == document_id)
    ).one_or_none()
    if img is None:
        raise NotFound("Image not found")
    path = storage.resolve(img.storage_path)
    if not path.is_file():
        raise NotFound("The image file is missing")
    return FileResponse(path)


@router.post("/{document_id}/runs", response_model=RunOut, status_code=status.HTTP_202_ACCEPTED)
def create_run(document_id: uuid.UUID, body: RunCreate, response: Response, session: SessionDep):
    """Queue a run; a worker executes it. 409 when the document already has a queued or running run."""
    doc = DocumentRepo(session).get(document_id)
    options = body.options()
    pipeline = narrow(ConfigRepo(session).resolve_pipeline(body.pipeline), options)
    run = RunRepo(session).enqueue(doc.id, pipeline, body.kind, options.model_dump(exclude_defaults=True))
    response.headers["Location"] = f"/api/v1/runs/{run.id}"
    return run_out(run)
