"""Aspect-safe color and sizing stage construction."""

from __future__ import annotations

from vhs_restore.settings import RestoreSettings


def _scaled_and_padded(width: int, height: int) -> tuple[str, str]:
    scale = f"scale={width}:{height}:force_original_aspect_ratio=decrease"
    pad = f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
    return scale, pad


def build_color_filters(settings: RestoreSettings) -> tuple[str, ...]:
    """Return color/aspect filters that never stretch 4:3 content to 16:9."""

    if settings.aspect_mode == "pillarbox_16_9":
        scale, pad = _scaled_and_padded(1440, 1080)
        return (
            scale,
            "setsar=1",
            "setdar=4/3",
            "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black",
        )

    if settings.output_profile == "dvd":
        scale, pad = _scaled_and_padded(720, 480)
        return (scale, pad, "setsar=8/9", "setdar=4/3")

    scale, pad = _scaled_and_padded(1440, 1080)
    return (scale, pad, "setsar=1", "setdar=4/3")


build_color_stage = build_color_filters

