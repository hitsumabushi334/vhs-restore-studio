"""Interfaces and selection for local video upscaling backends."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Protocol, runtime_checkable

from vhs_restore.utils.paths import safe_output_path


_VIDEO_SUFFIXES = frozenset(
    {
        ".3gp",
        ".avi",
        ".flv",
        ".m2ts",
        ".m4v",
        ".mkv",
        ".mov",
        ".mp4",
        ".mpeg",
        ".mpg",
        ".mts",
        ".mxf",
        ".ts",
        ".vob",
        ".webm",
        ".wmv",
    }
)


@runtime_checkable
class UpscaleBackend(Protocol):
    """Common interface implemented by every local upscaling backend."""

    name: str

    def is_available(self) -> bool:
        """Return whether this backend can be invoked on this machine."""

    def upscale(
        self,
        input: Path,
        output: Path,
        scale: int,
        model: str | None = None,
    ) -> Path:
        """Upscale ``input`` into a safe output path and return that path."""


def prepare_upscale_paths(
    input: str | Path,
    output: str | Path,
) -> tuple[Path, Path]:
    """Normalize media paths and choose a collision-free output path."""

    source = Path(input)
    destination = safe_output_path(Path(output))
    if source.resolve(strict=False) == destination.resolve(strict=False):
        raise ValueError("upscale output must differ from input")
    return source, destination


def validate_scale(scale: int) -> int:
    """Validate the integer scale accepted by local backends."""

    if isinstance(scale, bool) or not isinstance(scale, int) or scale <= 0:
        raise ValueError("scale must be a positive integer")
    return scale


def raise_for_command_failure(result: object, backend_name: str) -> None:
    """Raise a useful error when a backend process exits unsuccessfully."""

    returncode = getattr(result, "returncode", 0)
    if returncode == 0:
        return

    details: list[str] = []
    for attribute in ("stdout", "stderr"):
        value = getattr(result, attribute, None)
        if value:
            details.append(str(value).strip())
    detail = " ".join(part for part in details if part)
    suffix = f": {detail}" if detail else ""
    raise RuntimeError(
        f"{backend_name} upscale failed with exit code {returncode}{suffix}"
    )


def _is_video_input(input: str | Path) -> bool:
    return Path(input).suffix.casefold() in _VIDEO_SUFFIXES


def _backend_supports_input(
    backend: UpscaleBackend,
    input: str | Path | None,
) -> bool:
    if input is None:
        return True

    supports_input = getattr(backend, "supports_input", None)
    if callable(supports_input):
        try:
            return bool(supports_input(input))
        except Exception:
            return False

    backend_name = str(getattr(backend, "name", "")).casefold()
    return not (_is_video_input(input) and "realesrgan" in backend_name)


def select_upscale_backend(
    backends: Iterable[UpscaleBackend] | None = None,
    *,
    input: str | Path | None = None,
    video2x: UpscaleBackend | None = None,
    realesrgan: UpscaleBackend | None = None,
    classical: UpscaleBackend | None = None,
) -> UpscaleBackend:
    """Select Video2X, then Real-ESRGAN, then classical scaling.

    The final candidate is always returned as the safe fallback.  Availability
    probes are best-effort so a broken optional executable cannot prevent the
    app from selecting a classical path.
    """

    if backends is not None:
        candidates = tuple(backends)
        if not candidates:
            raise ValueError("backends must contain at least one backend")
        fallback = candidates[-1]
        preferred = candidates[:-1]
    else:
        if video2x is None:
            from .video2x import Video2XBackend

            video2x = Video2XBackend()
        if realesrgan is None:
            from .realesrgan import RealESRGANBackend

            realesrgan = RealESRGANBackend()
        if classical is None:
            from .classical import ClassicalBackend

            classical = ClassicalBackend()
        preferred = (video2x, realesrgan)
        fallback = classical

    for backend in preferred:
        if not _backend_supports_input(backend, input):
            continue
        try:
            if backend.is_available():
                return backend
        except Exception:
            continue
    return fallback


select_backend = select_upscale_backend
get_upscale_backend = select_upscale_backend


__all__ = [
    "UpscaleBackend",
    "get_upscale_backend",
    "prepare_upscale_paths",
    "raise_for_command_failure",
    "select_backend",
    "select_upscale_backend",
    "validate_scale",
]
