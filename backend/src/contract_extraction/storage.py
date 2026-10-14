"""Local file storage for documents and their artifacts.

Layout under the storage root (paths stored in the database are relative to it)::

    <code>/source/<file name>
    <code>/decompositions/<decomposition id>/{json,images}/
    <code>/logs/<run id>.log

Each decomposition gets its own folder, so re-processing never changes files that an
earlier row points to.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from .core.errors import InvalidInput, PayloadTooLarge

_UNSAFE = re.compile(r"[^A-Za-z0-9._ -]+")
_CODE = re.compile(r"^DOC\d{3,}$")
_CHUNK = 1024 * 1024


def safe_filename(name: str, default: str = "document.pdf") -> str:
    """Base name only, with unusual characters replaced."""
    base = Path(name.replace("\\", "/")).name.strip()
    base = _UNSAFE.sub("_", base).strip(". ")
    return base or default


@dataclass(frozen=True)
class StagedFile:
    """An upload written to a temporary file, hashed, not yet assigned to a document."""

    path: Path
    sha256: str
    size_bytes: int
    filename: str


class FileStorage:
    def __init__(self, root: Path):
        self.root = root

    def stage(self, stream: BinaryIO, filename: str, max_bytes: int | None = None) -> StagedFile:
        """Copy ``stream`` to a temporary file while hashing it.

        The hash decides whether the document already exists before anything is stored
        under a document code. Raises ``InvalidInput`` when ``max_bytes`` is exceeded.
        """
        tmp_dir = self.root / ".staging"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        digest, size = hashlib.sha256(), 0
        with tempfile.NamedTemporaryFile(dir=tmp_dir, delete=False) as out:
            path = Path(out.name)
            try:
                while chunk := stream.read(_CHUNK):
                    size += len(chunk)
                    if max_bytes is not None and size > max_bytes:
                        raise PayloadTooLarge(f"File exceeds the {max_bytes // _CHUNK} MB upload limit")
                    digest.update(chunk)
                    out.write(chunk)
            except BaseException:
                out.close()
                path.unlink(missing_ok=True)
                raise
        return StagedFile(path, digest.hexdigest(), size, safe_filename(filename))

    def commit_source(self, staged: StagedFile, code: str) -> str:
        """Move a staged file to ``<code>/source/``; returns the path relative to the root."""
        target = self.document_dir(code) / "source" / staged.filename
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(staged.path, target)
        return target.relative_to(self.root).as_posix()

    def discard(self, staged: StagedFile) -> None:
        staged.path.unlink(missing_ok=True)

    def document_dir(self, code: str) -> Path:
        if not _CODE.match(code):
            raise InvalidInput(f"Invalid document code: {code!r}")
        return self.root / code

    def decomposition_dir(self, code: str, decomposition_id: str) -> Path:
        return self.document_dir(code) / "decompositions" / decomposition_id

    def log_path(self, code: str, run_id: str) -> Path:
        return self.document_dir(code) / "logs" / f"{run_id}.log"

    def resolve(self, relative: str) -> Path:
        """Absolute path for a stored relative path, refusing anything outside the root."""
        root = self.root.resolve()
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise InvalidInput("Path escapes the storage root")
        return path

    def remove_document(self, code: str) -> None:
        shutil.rmtree(self.document_dir(code), ignore_errors=True)
