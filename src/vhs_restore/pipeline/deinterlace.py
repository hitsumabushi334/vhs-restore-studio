"""Interlace decisions and QTGMC/FFmpeg deinterlace stage descriptions."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from vhs_restore.analysis.interlace import (
    InterlaceAnalysis,
    normalize_field_order,
)
from vhs_restore.analysis.source_info import SourceInfo
from vhs_restore.settings import RestoreSettings


_INTERLACED_CLASSIFICATIONS = {"TFF", "BFF", "Mixed"}
_QTGMC_PRESETS = {
    "fast": "Fast",
    "balanced": "Medium",
    "high": "Slow",
    "very_high": "Slower",
}


@dataclass(frozen=True, slots=True)
class DeinterlaceDecision:
    """The resolved deinterlace stage for one analyzed source."""

    enabled: bool
    method: str
    field_order: str | None
    double_rate: bool
    input_frame_rate: float | None
    output_frame_rate: float | None
    filter_expression: str | None = None
    qtgmc_script: str | None = None
    reason: str = ""
    warning: str | None = None

    @property
    def mode(self) -> str:
        """Alias for the selected implementation mode."""

        return self.method

    @property
    def output_fps(self) -> float | None:
        """Alias for the post-deinterlace frame rate."""

        return self.output_frame_rate

    @property
    def filter(self) -> str | None:
        """Return the FFmpeg expression when the fallback is selected."""

        return self.filter_expression

    @property
    def script(self) -> str | None:
        """Return the generated VapourSynth script, if any."""

        return self.qtgmc_script


def _classification(analysis: SourceInfo | InterlaceAnalysis | object) -> str | None:
    if isinstance(analysis, SourceInfo):
        if analysis.interlace is not None:
            value = analysis.interlace.classification
        else:
            value = analysis.field_order
    elif isinstance(analysis, InterlaceAnalysis):
        value = analysis.classification
    else:
        value = getattr(analysis, "classification", None)
        if value is None:
            value = getattr(analysis, "field_order", None)

    if value is None:
        return None
    normalized = str(value).strip()
    if normalized.casefold() == "mixed":
        return "Mixed"
    if normalized.casefold() == "unknown":
        return "Unknown"
    return normalize_field_order(normalized) or normalized.upper()


def _frame_rate(analysis: SourceInfo | InterlaceAnalysis | object) -> float | None:
    value = getattr(analysis, "frame_rate", None)
    if value is None:
        value = getattr(analysis, "fps", None)
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value > 0 else None


def _metadata_field_order(analysis: SourceInfo | InterlaceAnalysis | object) -> str | None:
    value = getattr(analysis, "field_order", None)
    if value is None:
        return None
    normalized = normalize_field_order(str(value))
    return normalized if normalized in {"TFF", "BFF"} else None


def _source_path(analysis: SourceInfo | InterlaceAnalysis | object) -> Path | None:
    value = getattr(analysis, "path", None)
    return None if value is None else Path(value)


def _forced_field_order(mode: str) -> str | None:
    if mode == "tff":
        return "TFF"
    if mode == "bff":
        return "BFF"
    return None


def _resolve_interlaced_field_order(
    classification: str | None,
    analysis: SourceInfo | InterlaceAnalysis | object,
) -> str:
    if classification in {"TFF", "BFF"}:
        return classification
    return _metadata_field_order(analysis) or "TFF"


def _is_clean_progressive_5994p(
    classification: str | None,
    frame_rate: float | None,
) -> bool:
    return (
        classification == "Progressive"
        and frame_rate is not None
        and math.isclose(frame_rate, 60000 / 1001, rel_tol=0.0, abs_tol=0.02)
    )


def _qtgmc_preset_name(value: str) -> str:
    return _QTGMC_PRESETS.get(str(value).strip().casefold(), "Medium")


def generate_qtgmc_script(
    source: Path,
    *,
    field_order: str = "TFF",
    preset: str = "balanced",
) -> str:
    """Generate a self-contained QTGMC VapourSynth graph description.

    The script intentionally contains no preview window or output path.  That
    keeps the restoration graph identical for preview and full restore; the
    caller controls trimming and encoding around this graph.
    """

    field_order = field_order.upper()
    if field_order not in {"TFF", "BFF"}:
        raise ValueError("field_order must be TFF or BFF")

    source_literal = repr(str(Path(source)))
    qtgmc_preset = _qtgmc_preset_name(preset)
    return "\n".join(
        (
            "import vapoursynth as vs",
            "import havsfunc",
            "",
            "core = vs.core",
            f"clip = core.ffms2.Source({source_literal})",
            (
                "clip = havsfunc.QTGMC(clip, "
                f'Preset="{qtgmc_preset}", '
                f"TFF={field_order == 'TFF'}, FPSDivisor=1)"
            ),
            "clip.set_output()",
            "",
        )
    )


def _bwdif_filter(field_order: str) -> str:
    return f"bwdif=mode=send_field:parity={field_order.casefold()}:deint=all"


def decide_deinterlace(
    analysis: SourceInfo | InterlaceAnalysis | object,
    settings: RestoreSettings | None = None,
    *,
    qtgmc_available: bool = True,
) -> DeinterlaceDecision:
    """Resolve whether and how a source should be deinterlaced.

    ``auto`` follows idet/source analysis.  A clean progressive 59.94p source
    is explicitly kept progressive, preventing a second double-rate pass.
    ``tff`` and ``bff`` remain available as deliberate manual overrides.
    """

    settings = settings or RestoreSettings()
    requested_mode = str(settings.deinterlace).strip().casefold()
    classification = _classification(analysis)
    frame_rate = _frame_rate(analysis)

    forced_order = _forced_field_order(requested_mode)
    if requested_mode in {"off", "progressive"}:
        enabled = False
        field_order = None
        reason = "Deinterlace disabled by settings."
    elif forced_order is not None:
        enabled = True
        field_order = forced_order
        reason = f"{forced_order} deinterlace forced by settings."
    elif _is_clean_progressive_5994p(classification, frame_rate):
        enabled = False
        field_order = None
        reason = "Clean progressive 59.94p source; deinterlace disabled."
    elif classification in _INTERLACED_CLASSIFICATIONS:
        enabled = True
        field_order = _resolve_interlaced_field_order(classification, analysis)
        reason = f"{field_order} interlaced source requires double-rate deinterlace."
    else:
        enabled = False
        field_order = None
        reason = "Source analysis is progressive or unknown; deinterlace disabled."

    if not enabled:
        return DeinterlaceDecision(
            enabled=False,
            method="off",
            field_order=None,
            double_rate=False,
            input_frame_rate=frame_rate,
            output_frame_rate=frame_rate,
            reason=reason,
        )

    output_frame_rate = None if frame_rate is None else frame_rate * 2.0
    if qtgmc_available:
        source = _source_path(analysis)
        script = None
        if source is not None:
            script = generate_qtgmc_script(
                source,
                field_order=field_order or "TFF",
                preset=settings.qtgmc_preset,
            )
        return DeinterlaceDecision(
            enabled=True,
            method="qtgmc",
            field_order=field_order,
            double_rate=True,
            input_frame_rate=frame_rate,
            output_frame_rate=output_frame_rate,
            qtgmc_script=script,
            reason=reason + " QTGMC selected.",
        )

    warning = "QTGMC unavailable; FFmpeg bwdif fallback will be used."
    return DeinterlaceDecision(
        enabled=True,
        method="bwdif",
        field_order=field_order,
        double_rate=True,
        input_frame_rate=frame_rate,
        output_frame_rate=output_frame_rate,
        filter_expression=_bwdif_filter(field_order or "TFF"),
        reason=reason + " " + warning,
        warning=warning,
    )


# Descriptive aliases keep the stage API easy to discover for callers.
build_deinterlace_decision = decide_deinterlace
build_qtgmc_script = generate_qtgmc_script

