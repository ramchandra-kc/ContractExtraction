from __future__ import annotations

import hashlib
import io

import pytest

from contract_extraction.core.errors import InvalidInput
from contract_extraction.storage import safe_filename


def test_stage_hashes_and_commits(storage):
    staged = storage.stage(io.BytesIO(b"hello"), "../../evil name?.pdf")
    assert staged.sha256 == hashlib.sha256(b"hello").hexdigest()
    assert staged.size_bytes == 5
    assert staged.filename == "evil name_.pdf"
    rel = storage.commit_source(staged, "DOC001")
    assert rel == "DOC001/source/evil name_.pdf"
    assert storage.resolve(rel).read_bytes() == b"hello"


def test_size_limit_removes_partial_file(storage):
    with pytest.raises(InvalidInput, match="upload limit"):
        storage.stage(io.BytesIO(b"x" * (2 * 1024 * 1024)), "big.pdf", max_bytes=1024 * 1024)
    assert not list((storage.root / ".staging").iterdir())


def test_paths_stay_inside_root(storage):
    with pytest.raises(InvalidInput):
        storage.resolve("../outside.txt")
    with pytest.raises(InvalidInput):
        storage.document_dir("../DOC001")


@pytest.mark.parametrize("name, expected", [("a/b/c.pdf", "c.pdf"), ("C:\\x\\y.pdf", "y.pdf"), ("...", "document.pdf")])
def test_safe_filename(name, expected):
    assert safe_filename(name) == expected
