"""Path helpers for safe media output handling."""

from __future__ import annotations

import os
from pathlib import Path


def safe_output_path(desired: Path) -> Path:
    """Return ``desired`` or a collision-free sibling path.

    Existing files, directories, and symlinks are treated as occupied.  The
    original filename, including non-ASCII characters and spaces, is kept
    intact; a numeric suffix is inserted immediately before the extension.
    """

    desired = Path(desired)
    if not os.path.lexists(desired):
        return desired

    suffix = "".join(desired.suffixes)
    stem = desired.name[:-len(suffix)] if suffix else desired.name

    index = 1
    while True:
        candidate = desired.with_name(f"{stem} ({index}){suffix}")
        if not os.path.lexists(candidate):
            return candidate
        index += 1

