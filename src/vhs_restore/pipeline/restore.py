"""Shared VHS restoration stage composition."""

from __future__ import annotations

from vhs_restore.settings import RestoreSettings

from .chroma import build_chroma_repair_filter
from .denoise import build_denoise_filter


def _artifact_filter(strength: float) -> str | None:
    if strength == 0.0:
        return None
    # Keep this stage intentionally light: the settings model caps the value
    # at 1.0 and the default is only a weak deblock pass.
    return f"deblock=filter=weak:block=4:alpha={strength:.2f}:beta={strength:.2f}"


def build_final_sharpen_filter(strength: float) -> str | None:
    if strength == 0.0:
        return None
    amount = 0.15 + 0.85 * strength
    return f"unsharp=5:5:{amount:.2f}:5:5:0.00"


def build_restore_filters(settings: RestoreSettings) -> tuple[str, ...]:
    """Build restoration filters in fidelity-first order.

    Final sharpening is kept separate so the pipeline can place it after
    aspect/color conversion, matching the approved restoration order.
    """

    filters: list[str] = []
    denoise = build_denoise_filter(settings.denoise_strength)
    if denoise is not None:
        filters.append(denoise)

    chroma = build_chroma_repair_filter(settings.chroma_repair_strength)
    if chroma is not None:
        filters.append(chroma)

    artifact = _artifact_filter(settings.artifact_removal_strength)
    if artifact is not None:
        filters.append(artifact)

    return tuple(filters)


build_restore_chain = build_restore_filters

