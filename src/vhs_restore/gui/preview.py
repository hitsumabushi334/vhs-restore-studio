"""Preview-window calculations shared by the GUI and job controller."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from vhs_restore.analysis.source_info import SourceInfo
from vhs_restore.settings import RestoreSettings


PREVIEW_DURATION = 10.0


def preview_start_seconds(
    source_duration: float | None,
    position_percent: float,
) -> float:
    """Convert a 0--100 position slider value into source seconds."""

    if source_duration is None or source_duration <= 0:
        return 0.0
    position = max(0.0, min(100.0, float(position_percent))) / 100.0
    return float(source_duration) * position


@dataclass(frozen=True, slots=True)
class PreviewRequest:
    """Arguments needed to run a ten-second preview through the job runner."""

    source: Path
    analysis: SourceInfo
    settings: RestoreSettings
    output: Path
    start: float
    duration: float = PREVIEW_DURATION


def build_preview_request(
    source: str | Path,
    analysis: SourceInfo,
    settings: RestoreSettings,
    output: str | Path,
    position_percent: float,
) -> PreviewRequest:
    """Build a preview request without changing restoration settings."""

    return PreviewRequest(
        source=Path(source),
        analysis=analysis,
        settings=settings,
        output=Path(output),
        start=preview_start_seconds(analysis.duration, position_percent),
    )


preview_request = build_preview_request

__all__ = [
    "PREVIEW_DURATION",
    "PreviewRequest",
    "build_preview_request",
    "preview_request",
    "preview_start_seconds",
]
