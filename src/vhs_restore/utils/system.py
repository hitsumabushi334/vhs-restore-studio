"""Small system queries used by local diagnostics."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def free_disk_space(path: Path) -> int:
    """Return free bytes on the filesystem containing ``path``."""

    return shutil.disk_usage(Path(path)).free


def find_tool(name: str | os.PathLike[str]) -> Path | None:
    """Resolve a locally installed executable, returning ``None`` if absent."""

    if not name:
        return None
    resolved = shutil.which(os.fspath(name))
    return Path(resolved) if resolved is not None else None

