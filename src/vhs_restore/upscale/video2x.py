"""Video2X Vulkan backend wrapper."""

from __future__ import annotations

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
        if model:
            argv.extend(("--realesrgan-model", str(model)))

        try:
            result = run_command(argv)
        except OSError as exc:
            raise RuntimeError(f"video2x backend could not start: {exc}") from exc
        raise_for_command_failure(result, self.name)
        return destination


Video2xBackend = Video2XBackend


__all__ = ["Video2XBackend", "Video2xBackend"]
