"""Importing draft ground truth from label files. These tests commit (files are registered through their own
sessions); the test database is recreated for every test session, and each test uses its own contract."""

from __future__ import annotations

import json

from contract_extraction.core.settings import load_settings
from contract_extraction.labels import import_file, label_files, notes_for
from contract_extraction.persistence.repositories import DocumentRepo
from contract_extraction.persistence.repositories.ground_truth import GroundTruthRepo

from helpers import BODY, make_pdf

FIELDS = {
    "title": {"value": "Master Services Agreement", "evidence": "MASTER SERVICES AGREEMENT", "location": "Cover",
              "confidence": "high", "note": ""},
    "effective_date": {"value": {"date": "2024-03-01", "relative_to": None, "offset": None},
                       "evidence": "effective as of March 1, 2024", "location": "Preamble", "confidence": "medium",
                       "note": "Undated signatures"},
    "document_status": {"value": "Executed", "evidence": "", "location": "", "confidence": "high", "note": ""},
    "governing_law": {"value": "", "evidence": "", "location": "", "confidence": "high", "note": "Silent"},
}


def _setup(tmp_path, name: str, fields: dict | None = None, **extra):
    """A contract under tmp_path/test_data and its label file under tmp_path/labels."""
    (tmp_path / "test_data" / "msa").mkdir(parents=True, exist_ok=True)
    pdf = make_pdf(tmp_path / "test_data" / "msa" / f"{name}.pdf", pages=[f"{b} Labels test {name}." for b in BODY])
    label = tmp_path / "labels" / "msa" / f"{name}.pdf.json"
    label.parent.mkdir(parents=True, exist_ok=True)
    label.write_text(json.dumps({"file": f"test_data/msa/{name}.pdf", "contract_types": ["msa"],
                                 "labelled_by": "claude-cowork", "fields": fields or FIELDS, **extra}))
    return pdf, label


def _labels(db, code: str) -> dict:
    with db.session() as s:
        repo = GroundTruthRepo(s)
        doc = DocumentRepo(s).get_by_code(code)
        fs = repo.field_set()
        labels = {f.key: (gt.expected_value, gt.created_by, gt.notes) for f, gt in repo.labels(doc.id, fs) if gt}
        return {"labels": labels, "types": [t.key for t in repo.contract_types(doc.id, fs)], "tags": doc.tags}


def test_import_registers_and_labels(db, storage, tmp_path):
    _, label = _setup(tmp_path, "one")
    r = import_file(db, storage, load_settings("test"), label, tmp_path, tags=["p1-drafts"])

    assert r.error is None and r.registered and r.imported == 4 and r.rejected == []
    got = _labels(db, r.code)
    assert got["types"] == ["msa"] and got["tags"] == ["p1-drafts"]
    value, created_by, notes = got["labels"]["effective_date"]
    assert value["date"] == "2024-03-01" and created_by == "claude-cowork"
    assert notes == "claude-cowork draft · medium · Preamble · “effective as of March 1, 2024” · Undated signatures"
    assert got["labels"]["document_status"][0] == "executed"  # enum normalised as in the UI
    assert got["labels"]["governing_law"][0] == ""


def test_bad_values_are_rejected_and_the_rest_imported(db, storage, tmp_path):
    fields = {**FIELDS, "effective_date": {"value": 42}, "title": {"value": None}, "made_up_field": {"value": "x"}}
    _, label = _setup(tmp_path, "two", fields, contract_types=["msa", "nonsense"])
    r = import_file(db, storage, load_settings("test"), label, tmp_path)

    assert r.imported == 2
    assert {k for k, _ in r.rejected} == {"effective_date", "title", "made_up_field", "contract_types"}
    got = _labels(db, r.code)
    assert set(got["labels"]) == {"document_status", "governing_law"} and got["types"] == []


def test_reimport_keeps_hand_edits_unless_overwrite(db, storage, tmp_path):
    _, label = _setup(tmp_path, "three")
    settings = load_settings("test")
    code = import_file(db, storage, settings, label, tmp_path).code
    with db.session() as s:  # edited in the UI: created_by None
        repo = GroundTruthRepo(s)
        doc = DocumentRepo(s).get_by_code(code)
        title = next(f for f in repo.field_set().fields if f.key == "title")
        repo.set(doc.id, title.id, "Services Agreement", "fixed by hand")
        repo.set_contract_types(doc.id, repo.field_set(), ["msa", "sow"])

    again = import_file(db, storage, settings, label, tmp_path)
    assert not again.registered and again.kept == 1 and again.imported == 3 and again.contract_types == ["msa", "sow"]
    assert _labels(db, code)["labels"]["title"][:2] == ("Services Agreement", None)

    forced = import_file(db, storage, settings, label, tmp_path, overwrite=True)
    assert forced.kept == 0 and forced.imported == 4
    got = _labels(db, code)
    assert got["labels"]["title"][:2] == ("Master Services Agreement", "claude-cowork") and got["types"] == ["msa"]


def test_dry_run_changes_nothing(db, storage, tmp_path):
    pdf, label = _setup(tmp_path, "four", {**FIELDS, "effective_date": {"value": 42}})
    r = import_file(db, storage, load_settings("test"), label, tmp_path, dry_run=True)

    assert r.error is None and r.registered and r.code is None
    assert r.imported == 3 and [k for k, _ in r.rejected] == ["effective_date"]
    with db.session() as s:
        import hashlib
        assert DocumentRepo(s).get_by_sha256(hashlib.sha256(pdf.read_bytes()).hexdigest()) is None


def test_file_level_errors(db, storage, tmp_path):
    _, label = _setup(tmp_path, "five")
    data = json.loads(label.read_text())
    label.write_text(json.dumps({**data, "file": "test_data/msa/missing.pdf"}))
    assert "contract not found" in import_file(db, storage, load_settings("test"), label, tmp_path).error

    broken = tmp_path / "labels" / "broken.json"
    broken.write_text("{not json")
    assert import_file(db, storage, load_settings("test"), broken, tmp_path).error


def test_label_files_skip_other_json(tmp_path):
    _, label = _setup(tmp_path, "six")
    (tmp_path / "labels" / "selection.json").write_text(json.dumps({"msa": ["test_data/msa/six.pdf"]}))
    assert label_files(tmp_path / "labels") == [label]


def test_notes_leave_out_empty_parts():
    assert notes_for({"value": "", "confidence": "high", "note": "Silent"}, "cowork") == "cowork draft · high · Silent"
