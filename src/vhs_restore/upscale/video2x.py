"""Video2X Vulkan backend wrapper."""

from __future__ import annotations

import os

from dataclasses import dataclass, field
from pathlib import Path

from vhs_restore.utils import deps as dependency_probe
from vhs_restore.utils.process import run_command
from vhs_restore.utils.system import find_tool

from .base import (
    prepare_upscale_paths,
    raise_for_command_failure,
    validate_scale,
)

# Video2X 6.x --realesrgan-model values. Packaged presets still use the
# realesrgan-ncnn-vulkan names, which Video2X rejects as invalid arguments.
_VIDEO2X_REALESRGAN_MODELS = {
    "realesr-animevideov3": "realesr-animevideov3",
    "realesr-animevideov3-x2": "realesr-animevideov3",
    "realesr-animevideov3-x3": "realesr-animevideov3",
    "realesr-animevideov3-x4": "realesr-animevideov3",
    "realesrgan-plus": "realesrgan-plus",
    "realesrgan-plus-anime": "realesrgan-plus-anime",
    "realesrgan-plus-x4": "realesrgan-plus",
    "realesrgan-plus-anime-x4": "realesrgan-plus-anime",
    "realesrgan-x4plus": "realesrgan-plus",
    "realesrgan-x4plus-anime": "realesrgan-plus-anime",
}
_FOUR_X_ONLY_MODELS = frozenset({"realesrgan-plus", "realesrgan-plus-anime"})


def resolve_realesrgan_model(model: str | None, scale: int) -> str | None:
    """Map ncnn aliases onto Video2X models; drop names the CLI rejects."""

    if not model:
        return None
    mapped = _VIDEO2X_REALESRGAN_MODELS.get(model.strip().casefold())
    if mapped in _FOUR_X_ONLY_MODELS and scale != 4:
        return "realesr-animevideov3"
    return mapped


@dataclass(frozen=True, slots=True)
class Video2XBackend:
    """Invoke Video2X's Real-ESRGAN Vulkan video path."""

    executable: str | Path = "video2x"
    name: str = field(default="video2x", init=False)

    def _executable_path(self) -> Path | None:
        try:
            return find_tool(self.executable)
        except Exception:
            return None

    def is_available(self) -> bool:
        """Return whether Video2X has a usable Vulkan device."""

        executable = self._executable_path()
        if executable is None:
            return False

        try:
            available, _ = dependency_probe.probe_video2x_vulkan(executable)
        except Exception:
            return False
        return available

    def upscale(
        self,
        input: str | Path,
        output: str | Path,
        scale: int,
        model: str | None = None,
    ) -> Path:
        """Upscale a video through Video2X using its Vulkan backend."""

        source, destination = prepare_upscale_paths(input, output)
        scale = validate_scale(scale)
        executable = self._executable_path()
        if executable is None:
            raise RuntimeError("video2x backend is unavailable")

        argv = [
            str(executable),
            "-i",
            str(source),
            "-o",
            str(destination),
            "-p",
            "realesrgan",
            "-s",
            str(scale),
        ]
        resolved = resolve_realesrgan_model(model, scale)
        if resolved:
            argv.extend(("--realesrgan-model", resolved))
        argv.extend(
            (
                "-c",
                "libx264",
                "--pix-fmt",
                "yuv420p",
                "--thread-count",
                str(os.cpu_count() or 0),
                "-e",
                "preset=ultrafast",
                "-e",
                "crf=18",
            )
        )

        try:
            result = run_command(argv)
        except OSError as exc:
            raise RuntimeError(f"video2x backend could not start: {exc}") from exc
        raise_for_command_failure(result, self.name)
        return destination


Video2xBackend = Video2XBackend


__all__ = ["Video2XBackend", "Video2xBackend", "resolve_realesrgan_model"]
