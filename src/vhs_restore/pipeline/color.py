"""Compatibility wrapper for the final geometry stage."""

from __future__ import annotations

from vhs_restore.settings import RestoreSettings

from .geometry import build_geometry_filters


def build_color_filters(
    settings: RestoreSettings,
    analysis: object | None = None,
) -> tuple[str, ...]:
    """Return the aspect-safe final geometry filters.

    ``analysis`` is optional for compatibility with older callers; all
    non-native output modes resolve their dimensions without it.
    """

    return build_geometry_filters(settings, analysis)


build_color_stage = build_color_filters
