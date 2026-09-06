"""Small system queries used by local diagnostics."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

_KNOWN_VENDOR_DIRS = ("video2x", "realesrgan-ncnn-vulkan", "vapoursynth")


def project_root() -> Path:
    """Return the repository root (parent of ``src``)."""

    return Path(__file__).resolve().parents[3]


def vendor_root() -> Path:
    """Return the optional-backend vendor directory."""

    override = os.environ.get("VHS_RESTORE_VENDOR")
    if override:
        return Path(override)
    return project_root() / "vendor"


def free_disk_space(path: Path) -> int:
    """Return free bytes on the filesystem containing ``path``."""

    return shutil.disk_usage(Path(path)).free


def _is_under_root(candidate: Path, root: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _safe_iterdir(directory: Path) -> list[Path]:
    try:
        return list(directory.iterdir())
    except OSError:
        return []


def _find_named_executable(directory: Path, stem: str) -> Path | None:
    for filename in (f"{stem}.exe", stem):
        candidate = directory / filename
        if candidate.is_file():
            return candidate
    return None


def _find_in_known_vendor_dirs(vendor: Path, stem: str) -> Path | None:
    for subdir_name in _KNOWN_VENDOR_DIRS:
        subdir = vendor / subdir_name
        if not subdir.is_dir():
            continue

        found = _find_named_executable(subdir, stem)
        if found is not None and _is_under_root(found, vendor):
            return found

        for child in _safe_iterdir(subdir):
            if not child.is_dir():
                continue
            found = _find_named_executable(child, stem)
            if found is not None and _is_under_root(found, vendor):
                return found
    return None


def _rglob_vendor_executable(vendor: Path, stem: str) -> Path | None:
    if not vendor.is_dir():
        return None

    for pattern in (f"**/{stem}.exe", f"**/{stem}"):
        try:
            matches = vendor.glob(pattern)
        except OSError:
            continue
        for candidate in matches:
            if not candidate.is_file():
                continue
            if _is_under_root(candidate, vendor):
                return candidate
    return None


def find_tool(name: str | os.PathLike[str]) -> Path | None:
    """Resolve a locally installed executable, returning ``None`` if absent."""

    if not name:
        return None

    explicit = Path(name)
    if explicit.is_file():
        return explicit

    stem = Path(os.fspath(name)).stem
    vendor = vendor_root()

    for finder in (_find_in_known_vendor_dirs, _rglob_vendor_executable):
        found = finder(vendor, stem)
        if found is not None:
            return found

    scripts_dir = Path(sys.executable).resolve().parent
    found = _find_named_executable(scripts_dir, stem)
    if found is not None:
        return found

    resolved = shutil.which(os.fspath(name))
    return Path(resolved) if resolved is not None else None
