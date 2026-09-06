"""FFmpeg-generated media fixtures for real restoration smoke tests."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_FFMPEG = shutil.which("ffmpeg")
if _FFMPEG is None:
    pytest.skip("ffmpeg is required for synthetic media fixtures", allow_module_level=True)


_FPS_INTERLACED = "60000/1001"
_FPS_PROGRESSIVE = "60000/1001"
_DURATION = 2.0


def make_video_clip(
    destination: Path,
    *,
    field_order: str | None = None,
    progressive: bool = False,
    duration: float = _DURATION,
) -> Path:
    """Create a tiny 720x480 clip with moving video and a sine-tone audio track.

    ``field_order`` may be ``"tff"`` or ``"bff"``.  Interlaced fixtures start
    with 59.94p test content and use ``tinterlace`` to create 29.97i media;
    progressive fixtures retain 59.94p.  All paths are passed as individual
    subprocess argv values, so Unicode and spaces are exercised directly.
    """

    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    if duration <= 0:
        raise ValueError("duration must be positive")
    normalized_order = None if field_order is None else field_order.casefold()
    if normalized_order not in {None, "tff", "bff"}:
        raise ValueError("field_order must be tff, bff, or None")
    if normalized_order is not None and progressive:
        raise ValueError("progressive clips cannot specify field_order")

    if progressive:
        video_filter = "setfield=prog"
        source_rate = _FPS_PROGRESSIVE
    else:
        source_rate = _FPS_INTERLACED
        if normalized_order is None:
            video_filter = "setfield=prog"
        else:
            video_filter = (
                f"tinterlace=interleave_{'top' if normalized_order == 'tff' else 'bottom'},"
                f"setfield={normalized_order}"
            )

    video_filter = f"{video_filter},setsar=8/9"

    argv = [
        str(_FFMPEG),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size=720x480:rate={source_rate}:duration={duration:g}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:sample_rate=48000:duration={duration:g}",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-vf",
        video_filter,
        "-c:v",
        "mpeg4",
        "-q:v",
        "5",
        "-c:a",
        "aac",
        "-b:a",
        "64k",
        "-shortest",
        str(target),
    ]
    try:
        subprocess.run(argv, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(f"ffmpeg failed to create {target}: {detail}") from exc
    return target


def make_tff_clip(destination: Path, *, duration: float = _DURATION) -> Path:
    """Create a 720x480 29.97i top-field-first clip."""

    return make_video_clip(destination, field_order="tff", duration=duration)


def make_bff_clip(destination: Path, *, duration: float = _DURATION) -> Path:
    """Create a 720x480 29.97i bottom-field-first clip."""

    return make_video_clip(destination, field_order="bff", duration=duration)


def make_progressive_clip(destination: Path, *, duration: float = _DURATION) -> Path:
    """Create a 720x480 59.94p progressive clip."""

    return make_video_clip(destination, progressive=True, duration=duration)
