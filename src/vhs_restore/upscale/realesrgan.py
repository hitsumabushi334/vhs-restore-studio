"""Real-ESRGAN ncnn Vulkan backend wrapper."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from vhs_restore.utils.process import run_command
from vhs_restore.utils.system import find_tool

from .base import (
    prepare_upscale_paths,
    raise_for_command_failure,
    validate_scale,
)


_IMAGE_SUFFIXES = frozenset(
    {".avif", ".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
)


@dataclass(frozen=True, slots=True)
class RealESRGANBackend:
    """Invoke the local Real-ESRGAN ncnn Vulkan executable."""

    executable: str | Path = "realesrgan-ncnn-vulkan"
    name: str = field(default="realesrgan-ncnn-vulkan", init=False)

    def _executable_path(self) -> Path | None:
        try:
            return find_tool(self.executable)
        except Exception:
            return None

    def is_available(self) -> bool:
        """Return whether the Vulkan executable can be resolved locally."""

        return self._executable_path() is not None

    def supports_input(self, input: str | Path) -> bool:
        """Return whether Real-ESRGAN can consume the given input directly."""

        source = Path(input)
        return source.is_dir() or source.suffix.casefold() in _IMAGE_SUFFIXES

    def upscale(
        self,
        input: str | Path,
        output: str | Path,
        scale: int,
        model: str | None = None,
    ) -> Path:
        """Upscale an input path using Real-ESRGAN's Vulkan CLI."""

        source, destination = prepare_upscale_paths(input, output)
        if not self.supports_input(source):
            raise ValueError(
                "realesrgan-ncnn-vulkan accepts image files or directories, "
                "not video inputs"
            )
        scale = validate_scale(scale)
        executable = self._executable_path()
        if executable is None:
            raise RuntimeError("realesrgan-ncnn-vulkan backend is unavailable")

        argv = [
            str(executable),
            "-i",
            str(source),
            "-o",
            str(destination),
        ]
        if model:
            argv.extend(("-n", str(model)))
        argv.extend(("-s", str(scale)))

        try:
            result = run_command(argv)
        except OSError as exc:
            raise RuntimeError(
                f"realesrgan-ncnn-vulkan backend could not start: {exc}"
            ) from exc
        raise_for_command_failure(result, self.name)
        return destination


RealEsrganBackend = RealESRGANBackend


__all__ = ["RealESRGANBackend", "RealEsrganBackend"]
