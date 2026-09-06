"""Chroma-noise repair stage construction."""

from __future__ import annotations

import math


def _normalized_strength(strength: float) -> float:
    try:
        value = float(strength)
    except (TypeError, ValueError) as exc:
        raise ValueError("chroma repair strength must be numeric") from exc
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError("chroma repair strength must be between 0.0 and 1.0")
    return value


def build_chroma_repair_filter(strength: float) -> str | None:
    """Return chroma-only temporal smoothing, preserving luma detail."""

    value = _normalized_strength(strength)
    if value == 0.0:
        return None

    spatial = 0.25 + 2.0 * value
    temporal = 0.5 + 3.0 * value
    return f"hqdn3d=0.00:{spatial:.2f}:0.00:{temporal:.2f}"


build_chroma_filter = build_chroma_repair_filter
build_chroma_stage = build_chroma_repair_filter

