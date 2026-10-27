"""The code a process runs, recorded with every run so experiment results can be tied to a commit."""

from __future__ import annotations

import functools
import subprocess
from pathlib import Path

from .. import __version__


@functools.cache
def code_version() -> str:
    """``git describe --always --dirty`` of the checkout (e.g. ``565c89c1d2e3-dirty`` with uncommitted changes);
    the package version outside a git checkout. Read once per process: a worker keeps the code it started with."""
    try:
        out = subprocess.run(["git", "describe", "--always", "--dirty", "--abbrev=12"], cwd=Path(__file__).parent,
                             capture_output=True, text=True, timeout=5, check=True)
    except (OSError, subprocess.SubprocessError):
        return __version__
    return out.stdout.strip() or __version__
