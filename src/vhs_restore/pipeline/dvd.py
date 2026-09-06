"""DVD-Video bitrate planning helpers."""

from __future__ import annotations

import math
from typing import Final


# Nominal single- and dual-layer DVD capacities.  The planner intentionally
# keeps these in decimal bytes, matching the capacities printed on media.
DVD_CAPACITY_BYTES: Final[dict[str, int]] = {
    "DVD-5": 4_700_000_000,
    "DVD-9": 8_500_000_000,
}
DVD_AUTHORING_OVERHEAD: Final[float] = 0.07
DVD_SAFETY_MARGIN: Final[float] = 0.95
DVD_AUDIO_BITRATE_BPS: Final[int] = 192_000
DVD_MIN_VIDEO_BITRATE_BPS: Final[int] = 1_000_000
DVD_MAX_VIDEO_BITRATE_BPS: Final[int] = 9_000_000
DVD_BITRATE_STEP_BPS: Final[int] = 100_000


def _validated_duration(duration_s: float) -> float:
    if isinstance(duration_s, bool):
        raise ValueError("duration must be a positive finite number")
    try:
        duration = float(duration_s)
    except (TypeError, ValueError) as exc:
        raise ValueError("duration must be a positive finite number") from exc
    if not math.isfinite(duration) or duration <= 0.0:
        raise ValueError("duration must be a positive finite number")
    return duration


def plan_dvd_video_bitrate(
    duration_s: float,
    disc: str = "DVD-5",
) -> int:
    """Return a safe average DVD video bitrate in bits per second.

    The estimate reserves seven percent for authoring/filesystem overhead,
    applies a five percent safety margin, reserves 192 kbps for stereo AC-3,
    caps the result below the DVD-Video video-rate ceiling, and rounds down
    to a 100 kbps boundary for stable muxing headroom.
    """

    duration = _validated_duration(duration_s)
    if disc not in DVD_CAPACITY_BYTES:
        choices = ", ".join(DVD_CAPACITY_BYTES)
        raise ValueError(f"disc must be one of {choices}")

    usable_bits = (
        DVD_CAPACITY_BYTES[disc]
        * 8
        * (1.0 - DVD_AUTHORING_OVERHEAD)
        * DVD_SAFETY_MARGIN
    )
    total_bitrate = usable_bits / duration
    available_video = total_bitrate - DVD_AUDIO_BITRATE_BPS
    if available_video < DVD_MIN_VIDEO_BITRATE_BPS:
        raise ValueError("duration is too long for the minimum DVD video bitrate")

    capped_video = min(available_video, DVD_MAX_VIDEO_BITRATE_BPS)
    planned = int(math.floor(capped_video / DVD_BITRATE_STEP_BPS)) * DVD_BITRATE_STEP_BPS
    if planned < DVD_MIN_VIDEO_BITRATE_BPS:
        raise ValueError("duration is too long for the minimum DVD video bitrate")
    return planned


__all__ = [
    "DVD_AUDIO_BITRATE_BPS",
    "DVD_AUTHORING_OVERHEAD",
    "DVD_BITRATE_STEP_BPS",
    "DVD_CAPACITY_BYTES",
    "DVD_MAX_VIDEO_BITRATE_BPS",
    "DVD_MIN_VIDEO_BITRATE_BPS",
    "DVD_SAFETY_MARGIN",
    "plan_dvd_video_bitrate",
]
