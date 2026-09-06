"""Classical FFmpeg scaling backend."""

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


@dataclass(frozen=True, slots=True)
class ClassicalBackend:
    """Scale video with FFmpeg while copying the existing audio stream."""

    executable: str | Path = "ffmpeg"
    name: str = field(default="classical", init=False)

    def _executable_path(self) -> Path | None:
        try:
            return find_tool(self.executable)
        except Exception:
            return None

    def is_available(self) -> bool:
        """Return whether FFmpeg can be resolved locally."""

        return self._executable_path() is not None

    def upscale(
        self,
        input: str | Path,
        output: str | Path,
        scale: int,
        model: str | None = None,
    ) -> Path:
        """Scale a video with FFmpeg's CPU ``scale`` filter."""

        del model
        source, destination = prepare_upscale_paths(input, output)
        scale = validate_scale(scale)
        executable = self._executable_path()
        if executable is None:
            raise RuntimeError("classical FFmpeg backend is unavailable")

        argv = [
            str(executable),
            "-n",
            "-i",
            str(source),
            "-vf",
            f"scale=iw*{scale}:ih*{scale}",
            "-c:a",
            "copy",
            str(destination),
        ]

        try:
            result = run_command(argv)
        except OSError as exc:
            raise RuntimeError(f"ffmpeg backend could not start: {exc}") from exc
        raise_for_command_failure(result, self.name)
        return destination


FFmpegBackend = ClassicalBackend


__all__ = ["ClassicalBackend", "FFmpegBackend"]
