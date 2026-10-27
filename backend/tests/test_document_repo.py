from __future__ import annotations

import io
import uuid

import pytest

from contract_extraction.core.errors import NotFound
from contract_extraction.persistence.repositories import DocumentRepo


def _register(session, storage, content: bytes, name: str = "contract.pdf"):
    return DocumentRepo(session).register(storage.stage(io.BytesIO(content), name), storage)


def test_register_assigns_code_and_stores_file(session, storage):
    doc, created = _register(session, storage, b"%PDF-1 one")
    assert created
    assert doc.code.startswith("DOC") and len(doc.code) >= 6
    assert doc.storage_path == f"{doc.code}/source/contract.pdf"
    assert storage.resolve(doc.storage_path).read_bytes() == b"%PDF-1 one"
    assert doc.size_bytes == 10


def test_same_content_is_stored_once(session, storage):
    first, _ = _register(session, storage, b"same bytes", "a.pdf")
    second, created = _register(session, storage, b"same bytes", "b.pdf")
    assert not created
    assert second.id == first.id
    assert not list((storage.root / ".staging").iterdir())


def test_codes_increase(session, storage):
    a, _ = _register(session, storage, b"a")
    b, _ = _register(session, storage, b"b")
    assert int(b.code[3:]) == int(a.code[3:]) + 1


def test_lookup_and_paging(session, storage):
    docs = [_register(session, storage, f"doc {i}".encode())[0] for i in range(3)]
    repo = DocumentRepo(session)
    assert repo.get(docs[0].id).code == docs[0].code
    assert repo.get_by_code(docs[1].code).id == docs[1].id
    rows, total = repo.list(limit=2)
    assert total >= 3 and len(rows) == 2
    with pytest.raises(NotFound):
        repo.get(uuid.uuid4())


def test_search(session, storage):
    lease, _ = _register(session, storage, f"lease {uuid.uuid4()}".encode(), "Zqx_Office_Lease.pdf")
    _register(session, storage, f"nda {uuid.uuid4()}".encode(), "zqx-mutual-nda.pdf")
    repo = DocumentRepo(session)
    assert [d.id for d in repo.list(q="zqx_office")[0]] == [lease.id]
    assert [d.id for d in repo.list(q=lease.code.lower())[0]] == [lease.id]
    assert repo.list(q=" ZQX ")[1] == 2
    assert repo.list(q="zqx%lease")[1] == 0 and repo.list(q="zqx_mutual")[1] == 0
    assert repo.list(q="  ")[1] >= 2
