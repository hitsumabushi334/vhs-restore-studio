"""FFmpeg output arguments for the supported restoration profiles."""

from __future__ import annotations

import math

from vhs_restore.analysis.interlace import normalize_field_order
from vhs_restore.analysis.source_info import SourceInfo
from vhs_restore.settings import RestoreSettings

from .deinterlace import DeinterlaceDecision, decide_deinterlace
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


def _close_to(value: float | None, target: float) -> bool:
    return value is not None and math.isclose(value, target, rel_tol=0.0, abs_tol=0.02)


def _analysis_classification(analysis: SourceInfo) -> str | None:
    """Return the same classification vocabulary used by deinterlace."""

    if analysis.interlace is not None:
        value = analysis.interlace.classification
    else:
        value = analysis.field_order
    if value is None:
        return None

    normalized = normalize_field_order(str(value))
    if normalized is not None:
        return normalized
    value = str(value).strip()
    if value.casefold() == "mixed":
        return "Mixed"
    if value.casefold() == "unknown":
        return "Unknown"
    return value.upper() or None


def _resolve_deinterlace(
    analysis: SourceInfo,
    settings: RestoreSettings,
) -> DeinterlaceDecision:
    """Resolve cadence from the shared settings-aware pipeline decision."""

    return decide_deinterlace(analysis, settings, qtgmc_available=True)


def _frame_rate_argument(rate: float | None) -> str | None:
    if rate is None:
        return None
    if _close_to(rate, _NTSC_DOUBLE_RATE_FPS):
        return "60000/1001"
    if _close_to(rate, _NTSC_FPS):
        return "30000/1001"
    return f"{rate:g}"


def _restored_frame_rate(
    analysis: SourceInfo,
    settings: RestoreSettings | None = None,
    decision: DeinterlaceDecision | None = None,
) -> str | None:
    """Return the expected output rate after the shared restore decision."""

    settings = settings or RestoreSettings()
    decision = decision or _resolve_deinterlace(analysis, settings)
    rate = decision.output_frame_rate
    if rate is None:
        rate = _frame_rate(analysis)
    return _frame_rate_argument(rate)


def _dvd_field_order(
    analysis: SourceInfo,
    settings: RestoreSettings,
    decision: DeinterlaceDecision,
    *,
    required: bool,
) -> str | None:
    """Resolve DVD dominance without silently guessing uncertain source order."""

    requested_mode = str(settings.deinterlace).strip().casefold()
    if requested_mode in {"tff", "bff"}:
        return requested_mode.upper()

    classification = _analysis_classification(analysis)
    if classification in {None, "Unknown", "Mixed"}:
        raise ValueError(
            "DVD encoding requires a known TFF or BFF field order; "
            f"analysis reported {classification or 'missing'}"
        )
    if classification == "Progressive":
        # Progressive input has no source dominance to preserve.  NTSC DVD
        # still needs an explicit dominance when 59.94p is packed into fields.
        return "TFF" if required else None
    if classification in {"TFF", "BFF"}:
        return classification
    if decision.field_order in {"TFF", "BFF"}:
        return decision.field_order
    raise ValueError(
        "DVD encoding requires a resolved TFF or BFF field order; "
        f"analysis reported {classification}"
    )


def _needs_dvd_field_pairing(
    analysis: SourceInfo,
    settings: RestoreSettings | None = None,
    decision: DeinterlaceDecision | None = None,
) -> bool:
    """Whether the restored stream is expected to be 59.94p."""

    settings = settings or RestoreSettings()
    decision = decision or _resolve_deinterlace(analysis, settings)
    return _close_to(decision.output_frame_rate, _NTSC_DOUBLE_RATE_FPS)


def _build_dvd_args(
    analysis: SourceInfo,
    settings: RestoreSettings,
    decision: DeinterlaceDecision,
) -> list[str]:
    needs_pairing = _needs_dvd_field_pairing(analysis, settings, decision)
    field_order = _dvd_field_order(
        analysis,
        settings,
        decision,
        required=needs_pairing,
    )
    duration = analysis.duration
    if duration is None:
        raise ValueError("duration is required for the DVD bitrate planner")

    bitrate = plan_dvd_video_bitrate(duration)
    if needs_pairing:
        interleave = "top" if field_order == "TFF" else "bottom"
        video_filter = f"tinterlace=interleave_{interleave}"
    else:
        video_filter = "format=yuv420p"

    args = [
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
    if field_order is not None:
        top_field = "1" if field_order == "TFF" else "0"
        insert_at = args.index("-pix_fmt")
        args[insert_at:insert_at] = ["-top", top_field]
    return args


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
    decision = _resolve_deinterlace(analysis, settings)
    if selected == "dvd":
        return _build_dvd_args(analysis, settings, decision)

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

    output_rate = _restored_frame_rate(analysis, settings, decision)
    if output_rate is not None:
        args.extend(["-r", output_rate])
    return args


__all__ = ["build_encode_args"]
