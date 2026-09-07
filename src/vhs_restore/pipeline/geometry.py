"""Final output geometry for the fidelity-first restore pipeline."""

from __future__ import annotations

import math
from typing import Any

from vhs_restore.analysis.source_info import SourceInfo
from vhs_restore.settings import RestoreSettings


_RESOLUTION_TARGETS: dict[str, tuple[int, int]] = {
    "960x720": (960, 720),
    "1280x960": (1280, 960),
    "1440x1080": (1440, 1080),
    "1920x1080": (1920, 1080),
    "720x480": (720, 480),
}


def _positive_dimension(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _source_size(analysis: SourceInfo | object) -> tuple[int | None, int | None]:
    width = getattr(analysis, "width", None)
    height = getattr(analysis, "height", None)
    try:
        width = _positive_dimension(width, "source width") if width is not None else None
    except ValueError:
        width = None
    try:
        height = _positive_dimension(height, "source height") if height is not None else None
    except ValueError:
        height = None
    return width, height


def _target_resolution(settings: RestoreSettings) -> str:
    """Read the v2 target field while tolerating older settings instances."""

    target = getattr(settings, "target_resolution", None)
    if target is None or not str(target).strip():
        profile = str(getattr(settings, "output_profile", "archive_practical")).casefold()
        if profile == "dvd":
            return "720x480"
        return "1440x1080"
    return str(target).strip().casefold()


def resolve_target_size(settings: RestoreSettings, analysis: SourceInfo | object) -> tuple[int, int]:
    """Resolve the final output canvas dimensions for ``settings``.

    ``native`` is the only mode whose dimensions depend on source analysis.
    DVD and explicit 720x480 requests always use the DVD canvas, and the
    pillarbox mode always uses a 16:9 canvas without stretching its picture.
    """

    target = _target_resolution(settings)
    profile = str(getattr(settings, "output_profile", "archive_practical")).casefold()
    if profile == "dvd" or target == "720x480":
        return (720, 480)
    if target == "pillarbox_16_9" or getattr(settings, "aspect_mode", "preserve_4_3") == "pillarbox_16_9":
        return (1920, 1080)
    if target == "native":
        width, height = _source_size(analysis)
        if width is None or height is None:
            raise ValueError("native target resolution requires analyzed source dimensions")
        return width, height
    if target == "custom":
        width = _positive_dimension(getattr(settings, "target_width", None), "target_width")
        height = _positive_dimension(getattr(settings, "target_height", None), "target_height")
        return width, height
    try:
        return _RESOLUTION_TARGETS[target]
    except KeyError as exc:
        supported = ", ".join((*_RESOLUTION_TARGETS, "native", "custom"))
        raise ValueError(f"unsupported target resolution {target!r}; expected {supported}") from exc


def _is_four_three(width: int, height: int) -> bool:
    return math.isclose(width / height, 4 / 3, rel_tol=0.0, abs_tol=0.01)


def _canvas_aspect(width: int, height: int) -> str:
    if _is_four_three(width, height):
        return "4/3"
    if math.isclose(width / height, 16 / 9, rel_tol=0.0, abs_tol=0.01):
        return "16/9"
    return f"{width}/{height}"


def _scale_and_pad(width: int, height: int) -> tuple[str, str]:
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease",
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black",
    )


def build_geometry_filters(
    settings: RestoreSettings,
    analysis: SourceInfo | object,
) -> tuple[str, ...]:
    """Build only final geometry/aspect filters, never restoration filters.

    Every resizing branch uses ``force_original_aspect_ratio=decrease`` and
    pads the remaining canvas.  Thus a 4:3 picture can have bars, but cannot
    be stretched to fill a 16:9 output.
    """

    target = _target_resolution(settings)
    profile = str(getattr(settings, "output_profile", "archive_practical")).casefold()
    if profile == "dvd" or target == "720x480":
        scale, pad = _scale_and_pad(720, 480)
        return (scale, pad, "setsar=8/9", "setdar=4/3")

    if getattr(settings, "aspect_mode", "preserve_4_3") == "pillarbox_16_9":
        scale, _ = _scale_and_pad(1440, 1080)
        return (
            scale,
            "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black",
            "setsar=1",
            "setdar=16/9",
        )

    width, height = resolve_target_size(settings, analysis)
    if target != "native" and (width, height) == (720, 480):
        scale, pad = _scale_and_pad(720, 480)
        return (scale, pad, "setsar=8/9", "setdar=4/3")

    if target != "native" and (width, height) == (1920, 1080):
        scale, _ = _scale_and_pad(1440, 1080)
        return (
            scale,
            "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black",
            "setsar=1",
            "setdar=16/9",
        )

    if target == "native":
        if width == 720 and height == 480:
            scale, pad = _scale_and_pad(720, 480)
            return (scale, pad, "setsar=8/9", "setdar=4/3")
        scale, pad = _scale_and_pad(width, height)
        canvas_aspect = _canvas_aspect(width, height)
        return (scale, pad, "setsar=1", f"setdar={canvas_aspect}")

    scale, pad = _scale_and_pad(width, height)
    return (scale, pad, "setsar=1", f"setdar={_canvas_aspect(width, height)}")
