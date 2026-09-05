"""FFmpeg output arguments for the supported restoration profiles."""

from __future__ import annotations

import math

from vhs_restore.analysis.interlace import normalize_field_order
from vhs_restore.analysis.source_info import SourceInfo
from vhs_restore.settings import RestoreSettings

from .dvd import plan_dvd_video_bitrate


_PROFILE_ALIASES = {
    "archive_hq": "archive_hq",
    "archive_practical": "archive_practical",
    "compatibility": "compatibility",
    "dvd": "dvd",
}
_NTSC_FPS = 30000 / 1001
_NTSC_DOUBLE_RATE_FPS = 60000 / 1001


def _profile_name(profile: str) -> str:
    if not isinstance(profile, str):
        raise ValueError("profile must be a supported string")
    key = profile.strip().casefold().replace("-", "_").replace(" ", "_")
    try:
        return _PROFILE_ALIASES[key]
    except KeyError as exc:
        raise ValueError(f"unsupported encode profile: {profile!r}") from exc


def _frame_rate(analysis: SourceInfo) -> float | None:
    value = analysis.frame_rate
    if value is None:
        return None
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return None
    return rate if math.isfinite(rate) and rate > 0.0 else None


def _field_order(analysis: SourceInfo) -> str | None:
    value = normalize_field_order(analysis.field_order)
    if value in {"TFF", "BFF", "Progressive"}:
        return value
    interlace = analysis.interlace
    if interlace is not None:
        value = normalize_field_order(interlace.classification)
        if value in {"TFF", "BFF", "Progressive"}:
            return value
    return None


def _close_to(value: float | None, target: float) -> bool:
    return value is not None and math.isclose(value, target, rel_tol=0.0, abs_tol=0.02)


def _restored_frame_rate(analysis: SourceInfo) -> str | None:
    """Return the expected output rate after the shared restore decision."""

    rate = _frame_rate(analysis)
    order = _field_order(analysis)
    if _close_to(rate, _NTSC_FPS) and order in {"TFF", "BFF"}:
        return "60000/1001"
    if _close_to(rate, _NTSC_DOUBLE_RATE_FPS):
        return "60000/1001"
    if _close_to(rate, _NTSC_FPS):
        return "30000/1001"
    return None if rate is None else f"{rate:g}"


def _dvd_field_order(analysis: SourceInfo) -> str:
    return _field_order(analysis) if _field_order(analysis) in {"TFF", "BFF"} else "TFF"


def _needs_dvd_field_pairing(analysis: SourceInfo) -> bool:
    """Whether the restored stream is expected to be 59.94p."""

    rate = _frame_rate(analysis)
    order = _field_order(analysis)
    if _close_to(rate, _NTSC_DOUBLE_RATE_FPS):
        return True
    return _close_to(rate, _NTSC_FPS) and order in {"TFF", "BFF"}


def _build_dvd_args(analysis: SourceInfo) -> list[str]:
    field_order = _dvd_field_order(analysis)
    interleave = "top" if field_order == "TFF" else "bottom"
    top_field = "1" if field_order == "TFF" else "0"
    duration = analysis.duration
    if duration is None:
        raise ValueError("duration is required for the DVD bitrate planner")

    bitrate = plan_dvd_video_bitrate(duration)
    video_filter = (
        f"tinterlace=interleave_{interleave}"
        if _needs_dvd_field_pairing(analysis)
        else "format=yuv420p"
    )
    return [
        "-target",
        "ntsc-dvd",
        "-f",
        "dvd",
        "-s",
        "720x480",
        "-aspect",
        "4:3",
        "-r",
        "30000/1001",
        "-vf",
        video_filter,
        "-c:v",
        "mpeg2video",
        "-b:v",
        str(bitrate),
        "-maxrate",
        "9000000",
        "-minrate",
        "0",
        "-bufsize",
        "1835008",
        "-flags",
        "+ilme+ildct",
        "-top",
        top_field,
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "ac3",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-ac",
        "2",
    ]


def build_encode_args(
    profile: str,
    analysis: SourceInfo,
    settings: RestoreSettings,
) -> list[str]:
    """Build output-only FFmpeg arguments for one encode profile.

    Input and output paths deliberately stay outside this function so callers
    can reuse the same argument list for preview and full restore jobs.
    """

    if not isinstance(analysis, SourceInfo):
        raise TypeError("analysis must be a SourceInfo instance")
    if not isinstance(settings, RestoreSettings):
        raise TypeError("settings must be a RestoreSettings instance")

    selected = _profile_name(profile)
    if selected == "dvd":
        return _build_dvd_args(analysis)

    if selected == "archive_hq":
        args = [
            "-f",
            "matroska",
            "-c:v",
            "ffv1",
            "-level",
            "3",
            "-coder",
            "1",
            "-context",
            "1",
            "-g",
            "1",
            "-slicecrc",
            "1",
            "-c:a",
            "flac",
        ]
    elif selected == "archive_practical":
        args = [
            "-f",
            "matroska",
            "-c:v",
            "libx264",
            "-preset",
            "slow",
            "-crf",
            "16",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
        ]
    else:
        args = [
            "-f",
            "mp4",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-profile:v",
            "high",
            "-level",
            "4.1",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-movflags",
            "+faststart",
        ]

    output_rate = _restored_frame_rate(analysis)
    if output_rate is not None:
        args.extend(["-r", output_rate])
    return args


__all__ = ["build_encode_args"]
