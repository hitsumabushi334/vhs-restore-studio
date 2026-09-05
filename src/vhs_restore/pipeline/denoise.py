"""Conservative temporal/luma denoise stage construction."""

from __future__ import annotations

import math


def _normalized_strength(strength: float) -> float:
    try:
        value = float(strength)
    except (TypeError, ValueError) as exc:
        raise ValueError("denoise strength must be numeric") from exc
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError("denoise strength must be between 0.0 and 1.0")
    return value


def build_denoise_filter(strength: float) -> str | None:
    """Return a weak ``hqdn3d`` expression, or no-op for zero strength."""

    value = _normalized_strength(strength)
    if value == 0.0:
        return None

    luma_spatial = 0.5 + 2.5 * value
    chroma_spatial = 0.25 + 1.75 * value
    luma_temporal = 1.0 + 4.0 * value
    chroma_temporal = 0.5 + 2.5 * value
    return (
        "hqdn3d="
        f"{luma_spatial:.2f}:{chroma_spatial:.2f}:"
        f"{luma_temporal:.2f}:{chroma_temporal:.2f}"
    )


build_denoise_stage = build_denoise_filter

