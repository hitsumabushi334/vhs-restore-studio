"""The single shared preview/full restore pipeline plan builder."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from vhs_restore.analysis.source_info import SourceInfo
from vhs_restore.settings import RestoreSettings
from vhs_restore.utils.deps import detect_dependencies

from .color import build_color_filters
from .deinterlace import DeinterlaceDecision, decide_deinterlace
from .restore import build_final_sharpen_filter, build_restore_filters


@dataclass(frozen=True, slots=True)
class PipelinePlan:
    """Immutable description of one shared restoration graph."""

    source: Path
    filters: tuple[str, ...]
    filter_graph: str
    deinterlace: DeinterlaceDecision
    restore_filters: tuple[str, ...]
    color_filters: tuple[str, ...]
    stages: tuple[str, ...]
    start: float | None = None
    duration: float | None = None
    output: Path | None = None
    output_frame_rate: float | None = None
    aspect_ratio: str = "4:3"
    preserve_aspect: bool = True
    qtgmc_script: str | None = None
    warnings: tuple[str, ...] = ()
    settings: RestoreSettings | None = None
    analysis: SourceInfo | None = None

    @property
    def input(self) -> Path:
        """Alias for the source media path."""

        return self.source

    @property
    def source_path(self) -> Path:
        """Alias for the source media path."""

        return self.source

    @property
    def input_path(self) -> Path:
        """Alias for the source media path."""

        return self.source

    @property
    def output_path(self) -> Path | None:
        """Return the output slot; the builder never overwrites source media."""

        return self.output

    @property
    def filter_chain(self) -> tuple[str, ...]:
        """Alias for the immutable ordered filter tuple."""

        return self.filters

    @property
    def ffmpeg_filters(self) -> str:
        """Return the comma-separated filter graph representation."""

        return self.filter_graph

    @property
    def output_fps(self) -> float | None:
        """Alias for the final planned video frame rate."""

        return self.output_frame_rate

    @property
    def frame_rate(self) -> float | None:
        """Alias for the final planned video frame rate."""

        return self.output_frame_rate

    @property
    def deinterlace_method(self) -> str:
        """Return ``off``, ``qtgmc``, or ``bwdif`` for callers/UI status."""

        return self.deinterlace.method


def _window_value(value: float | None, *, name: str, allow_zero: bool) -> float | None:
    if value is None:
        return None
    try:
        normalized = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    if normalized < 0.0 or (not allow_zero and normalized == 0.0):
        comparison = ">= 0" if allow_zero else "> 0"
        raise ValueError(f"{name} must be {comparison}")
    return normalized


def _dependency_qtgmc_available() -> tuple[bool, str | None]:
    try:
        report = detect_dependencies()
    except Exception as exc:
        return False, f"QTGMC unavailable; FFmpeg bwdif fallback will be used ({exc})."

    available = getattr(report, "qtgmc_available", None)
    if available is None:
        available = getattr(report, "qtgmc", False)
    return bool(available), None


def _append_warning(warnings: list[str], warning: str) -> None:
    """Append a warning once, collapsing duplicate QTGMC fallback messages."""

    if warning in warnings:
        return
    if warning.casefold().startswith("qtgmc unavailable") and any(
        existing.casefold().startswith("qtgmc unavailable") for existing in warnings
    ):
        return
    warnings.append(warning)


def build_pipeline(
    settings: RestoreSettings,
    analysis: SourceInfo,
    *,
    start: float | None = None,
    duration: float | None = None,
    output: Path | None = None,
) -> PipelinePlan:
    """Build the one filter plan used by both preview and full restore.

    ``start``, ``duration``, and ``output`` are plan metadata only.  They are
    deliberately not interpolated into any filter expression or QTGMC script,
    so preview and full restore cannot drift into different restoration
    settings.
    """

    if not isinstance(settings, RestoreSettings):
        raise TypeError("settings must be a RestoreSettings instance")
    if not isinstance(analysis, SourceInfo):
        raise TypeError("analysis must be a SourceInfo instance")

    normalized_start = _window_value(start, name="start", allow_zero=True)
    normalized_duration = _window_value(duration, name="duration", allow_zero=False)
    normalized_output = None if output is None else Path(output)

    provisional = decide_deinterlace(
        analysis,
        settings,
        qtgmc_available=True,
    )
    dependency_warning: str | None = None
    if provisional.enabled:
        qtgmc_available, dependency_warning = _dependency_qtgmc_available()
        decision = decide_deinterlace(
            analysis,
            settings,
            qtgmc_available=qtgmc_available,
        )
    else:
        decision = provisional

    restore_filters = build_restore_filters(settings)
    color_filters = build_color_filters(settings)
    sharpen = build_final_sharpen_filter(settings.sharpen_strength)

    filters: list[str] = []
    stages: list[str] = []
    if decision.enabled:
        stages.append("deinterlace")
        if decision.filter_expression is not None:
            filters.append(decision.filter_expression)
    filters.extend(restore_filters)
    if settings.denoise_strength > 0.0:
        stages.append("denoise")
    if settings.chroma_repair_strength > 0.0:
        stages.append("chroma")
    if settings.artifact_removal_strength > 0.0:
        stages.append("artifact_removal")
    filters.extend(color_filters)
    stages.append("color")
    if sharpen is not None:
        filters.append(sharpen)
        stages.append("sharpen")

    warnings: list[str] = []
    if dependency_warning is not None:
        _append_warning(warnings, dependency_warning)
    if decision.warning is not None:
        _append_warning(warnings, decision.warning)

    return PipelinePlan(
        source=Path(analysis.path),
        filters=tuple(filters),
        filter_graph=",".join(filters),
        deinterlace=decision,
        restore_filters=restore_filters,
        color_filters=color_filters,
        stages=tuple(stages),
        start=normalized_start,
        duration=normalized_duration,
        output=normalized_output,
        output_frame_rate=decision.output_frame_rate,
        aspect_ratio="4:3",
        preserve_aspect=True,
        qtgmc_script=decision.qtgmc_script,
        warnings=tuple(warnings),
        settings=settings,
        analysis=analysis,
    )
