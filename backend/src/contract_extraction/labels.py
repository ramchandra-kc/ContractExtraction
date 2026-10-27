"""Import draft ground truth from label files: one JSON per contract, e.g. drafted by Claude Cowork with
docs/labelling/cowork-labelling-prompt.md.

    {"file": "test_data/msa/x.htm", "contract_types": ["msa"], "labelled_by": "claude-cowork",
     "fields": {"<field key>": {"value": ..., "evidence": "...", "location": "...", "confidence": "high", "note": ""}}}

``file`` is relative to the repository root. Each file is registered like an upload (not decomposed), its
contract types are set, and every value goes through the same validation as a label set in the UI. A value
that does not fit its field is reported and the rest of the file is still imported.

Imported labels are drafts: ``created_by`` is the file's ``labelled_by``. A label edited by hand (its
``created_by`` is something else) and contract types already labelled are kept unless ``overwrite``.
Evidence, location, confidence and note go into the label's notes, for review in the UI.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .core.errors import AppError, InvalidInput
from .core.settings import Settings
from .ingestion import register_file
from .persistence.db import Database
from .persistence.repositories import DocumentRepo
from .persistence.repositories.ground_truth import GroundTruthRepo
from .storage import FileStorage

DEFAULT_SOURCE = "import"


@dataclass
class FileReport:
    label_file: Path
    code: str | None = None
    registered: bool = False
    contract_types: list[str] = field(default_factory=list)
    imported: int = 0
    kept: int = 0
    rejected: list[tuple[str, str]] = field(default_factory=list)
    error: str | None = None


def label_files(directory: Path) -> list[Path]:
    """The label files under ``directory``: JSON objects with ``file`` and ``fields`` (others are ignored)."""
    out = []
    for path in sorted(directory.rglob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            out.append(path)  # reported as unreadable by import_file
            continue
        if isinstance(data, dict) and "fields" in data:
            out.append(path)
    return out


def notes_for(entry: dict[str, Any], source: str) -> str:
    """``claude-cowork draft · medium · § 6.1 · "quote" · note``, leaving out empty parts."""
    evidence = (entry.get("evidence") or "").strip()
    parts = [f"{source} draft", entry.get("confidence"), entry.get("location"),
             f"“{evidence}”" if evidence else None, entry.get("note")]
    return " · ".join(str(p).strip() for p in parts if p and str(p).strip())


def import_file(db: Database, storage: FileStorage, settings: Settings, label_file: Path, root: Path, *,
                overwrite: bool = False, dry_run: bool = False, tags: list[str] | None = None) -> FileReport:
    report = FileReport(label_file)
    try:
        data = json.loads(label_file.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("file"), str) or not isinstance(data.get("fields"), dict):
            raise InvalidInput('expected an object with "file" (a path) and "fields" (an object)')
        source_path = root / data["file"]
        if not source_path.is_file():
            raise InvalidInput(f"contract not found: {source_path}")
        source = str(data.get("labelled_by") or DEFAULT_SOURCE)

        if dry_run:
            with db.session() as s:
                doc = DocumentRepo(s).get_by_sha256(hashlib.sha256(source_path.read_bytes()).hexdigest())
                _apply(s, report, doc.id if doc else None, data, source, overwrite, write=False)
                report.code = doc.code if doc else None
                report.registered = doc is None
            return report

        document_id, report.code, report.registered = register_file(db, storage, settings, source_path)
        with db.session() as s:
            _apply(s, report, document_id, data, source, overwrite, write=True)
            if tags:
                DocumentRepo(s).add_tags(document_id, tags)
    except (OSError, ValueError, AppError) as exc:
        report.error = str(exc)
    return report


def _apply(s, report: FileReport, document_id, data: dict, source: str, overwrite: bool, write: bool) -> None:
    repo = GroundTruthRepo(s)
    fs = repo.field_set()
    fields = {f.key: f for f in fs.fields}
    existing = {f.key: gt for f, gt in repo.labels(document_id, fs) if gt is not None} if document_id else {}

    types = data.get("contract_types") or []
    labelled_types = [t.key for t in repo.contract_types(document_id, fs)] if document_id else []
    if types and (overwrite or not labelled_types):
        known = {t.key for t in fs.contract_types}
        unknown = [t for t in types if t not in known]
        if unknown:
            report.rejected.append(("contract_types", f"unknown contract type(s) {unknown}"))
        else:
            if write:
                repo.set_contract_types(document_id, fs, types)
            report.contract_types = types
    else:
        report.contract_types = labelled_types

    for key, entry in data["fields"].items():
        f = fields.get(key)
        if f is None:
            report.rejected.append((key, "not a field of the catalogue"))
            continue
        entry = entry if isinstance(entry, dict) else {"value": entry}
        current = existing.get(key)
        if current is not None and current.created_by != source and not overwrite:
            report.kept += 1
            continue
        try:
            if write:
                with s.begin_nested():
                    repo.set(document_id, f.id, entry.get("value"), notes_for(entry, source), created_by=source)
            else:
                repo.conform(f, entry.get("value"))
        except InvalidInput as exc:
            report.rejected.append((key, str(exc)))
            continue
        report.imported += 1
