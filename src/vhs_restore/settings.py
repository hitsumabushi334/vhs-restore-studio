"""Restore settings, packaged presets, and fidelity-safety validation."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from importlib import resources
from typing import Any, Mapping

from vhs_restore.analysis.interlace import InterlaceAnalysis, normalize_field_order
from vhs_restore.analysis.source_info import SourceInfo


_DEINTERLACE_MODES = {"auto", "off", "tff", "bff", "progressive"}
_QTGMC_PRESETS = {"fast", "balanced", "high", "very_high"}
_AI_BACKENDS = {"none", "classical", "realesrgan-ncnn-vulkan", "video2x"}
_ASPECT_MODES = {"preserve_4_3", "pillarbox_16_9"}
_OUTPUT_PROFILES = {
    "archive_hq",
    "archive_practical",
    "compatibility",
    "dvd",
}

_PRESET_FILES = {
    "natural": "natural.json",
    "balanced_ai": "balanced_ai.json",
    "strong_ai": "strong_ai.json",
    "dvd": "dvd.json",
    "archive": "archive.json",
}


@dataclass(frozen=True, slots=True)
class Warning:
    """A non-fatal settings validation warning shown to the user."""

    message: str
    code: str = "settings"
    severity: str = "warning"

    @property
    def text(self) -> str:
        """Return the display text for callers that use a text-like name."""

        return self.message

    @property
    def level(self) -> str:
        """Return the warning severity using the common ``level`` spelling."""

        return self.severity

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class RestoreSettings:
    """All user-selectable settings consumed by the restore pipeline.

    Strength values are normalized to the inclusive range 0.0--1.0 by the
    preset loader.  Validation remains separate so a GUI can construct a
    custom setting and show all applicable warnings at once.
    """

    name: str = "Custom"
    description: str = "User-defined restoration settings."
    deinterlace: str = "auto"
    qtgmc_preset: str = "balanced"
    denoise_strength: float = 0.15
    chroma_repair_strength: float = 0.2
    artifact_removal_strength: float = 0.1
    sharpen_strength: float = 0.0
    stabilization: bool = False
    ai_upscale: bool = False
    ai_backend: str = "none"
    ai_model: str | None = None
    ai_scale: int = 1
    preserve_aspect: bool = True
    aspect_mode: str = "preserve_4_3"
    output_profile: str = "archive_practical"

    @property
    def preset_name(self) -> str:
        """Alias used by UI code that distinguishes a preset from its label."""

        return self.name

    @property
    def temporal_denoise(self) -> float:
        """Alias for the temporal denoise strength used by the pipeline."""

        return self.denoise_strength

    @property
    def chroma_repair(self) -> float:
        """Alias for the chroma repair strength used by the pipeline."""

        return self.chroma_repair_strength

    @property
    def artifact_removal(self) -> float:
        """Alias for the light artifact-removal strength."""

        return self.artifact_removal_strength

    @property
    def final_sharpen(self) -> float:
        """Alias for the optional final sharpen strength."""

        return self.sharpen_strength

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible settings mapping."""

        return asdict(self)

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> RestoreSettings:
        """Build settings from a complete preset mapping.

        Presets are data, so malformed or incomplete files fail at load time
        with a useful ``ValueError`` instead of producing a partial pipeline.
        """

        if not isinstance(values, Mapping):
            raise ValueError("preset data must be a JSON object")

        expected = set(cls.__dataclass_fields__)
        missing = sorted(expected - set(values))
        if missing:
            raise ValueError("preset is missing fields: " + ", ".join(missing))
        unknown = sorted(set(values) - expected)
        if unknown:
            raise ValueError("preset has unknown fields: " + ", ".join(unknown))

        settings = cls(**{field: values[field] for field in expected})
        _validate_preset_values(settings)
        return settings


def _validate_preset_values(settings: RestoreSettings) -> None:
    if not isinstance(settings.name, str) or not settings.name.strip():
        raise ValueError("preset name must be a non-empty string")
    if not isinstance(settings.description, str):
        raise ValueError("preset description must be a string")
    if not isinstance(settings.deinterlace, str):
        raise ValueError("deinterlace must be a string")
    if settings.deinterlace not in _DEINTERLACE_MODES:
        raise ValueError(f"invalid deinterlace mode: {settings.deinterlace!r}")
    if not isinstance(settings.qtgmc_preset, str):
        raise ValueError("qtgmc_preset must be a string")
    if settings.qtgmc_preset not in _QTGMC_PRESETS:
        raise ValueError(f"invalid QTGMC preset: {settings.qtgmc_preset!r}")
    for field in (
        "denoise_strength",
        "chroma_repair_strength",
        "artifact_removal_strength",
        "sharpen_strength",
    ):
        value = getattr(settings, field)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"{field} must be a number")
        if not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0:
            raise ValueError(f"{field} must be between 0.0 and 1.0")
    if not isinstance(settings.stabilization, bool):
        raise ValueError("stabilization must be a boolean")
    if not isinstance(settings.ai_upscale, bool):
        raise ValueError("ai_upscale must be a boolean")
    if not isinstance(settings.ai_backend, str):
        raise ValueError("ai_backend must be a string")
    if settings.ai_backend not in _AI_BACKENDS:
        raise ValueError(f"invalid AI backend: {settings.ai_backend!r}")
    if settings.ai_model is not None and not isinstance(settings.ai_model, str):
        raise ValueError("ai_model must be a string or null")
    if not isinstance(settings.ai_scale, int) or isinstance(settings.ai_scale, bool):
        raise ValueError("ai_scale must be an integer")
    if settings.ai_scale not in {1, 2, 4}:
        raise ValueError("ai_scale must be one of 1, 2, or 4")
    if not isinstance(settings.preserve_aspect, bool):
        raise ValueError("preserve_aspect must be a boolean")
    if not isinstance(settings.aspect_mode, str):
        raise ValueError("aspect_mode must be a string")
    if settings.aspect_mode not in _ASPECT_MODES:
        raise ValueError(f"invalid aspect mode: {settings.aspect_mode!r}")
    if not isinstance(settings.output_profile, str):
        raise ValueError("output_profile must be a string")
    if settings.output_profile not in _OUTPUT_PROFILES:
        raise ValueError(f"invalid output profile: {settings.output_profile!r}")


def _preset_key(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("preset name must be a non-empty string")
    return name.strip().casefold().replace("-", "_").replace(" ", "_")


def load_preset(name: str) -> RestoreSettings:
    """Load one UTF-8 preset from the installed package assets."""

    key = _preset_key(name)
    filename = _PRESET_FILES.get(key)
    if filename is None:
        raise ValueError(f"unknown preset: {name}")

    asset = resources.files("vhs_restore").joinpath("assets", "presets", filename)
    try:
        raw = asset.read_text(encoding="utf-8")
        values = json.loads(raw)
    except FileNotFoundError as exc:
        raise RuntimeError(f"packaged preset is missing: {filename}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in preset {filename}: {exc}") from exc
    return RestoreSettings.from_mapping(values)


def _analysis_classification(analysis: object) -> str | None:
    if isinstance(analysis, SourceInfo):
        if analysis.interlace is not None:
            return analysis.interlace.classification
        return normalize_field_order(analysis.field_order)
    if isinstance(analysis, InterlaceAnalysis):
        return analysis.classification
    value = getattr(analysis, "classification", None)
    return str(value) if value is not None else None


def _warning(message: str, code: str) -> Warning:
    return Warning(message=message, code=code)


def validate_settings(
    settings: RestoreSettings,
    analysis: SourceInfo | InterlaceAnalysis | object,
) -> list[Warning]:
    """Return non-fatal warnings for settings and analyzed source metadata."""

    warnings: list[Warning] = []
    classification = _analysis_classification(analysis)

    if (
        settings.ai_upscale
        and (
            settings.ai_scale >= 4
            or settings.denoise_strength >= 0.5
            or settings.chroma_repair_strength >= 0.5
            or settings.artifact_removal_strength >= 0.5
            or settings.sharpen_strength >= 0.3
            or settings.qtgmc_preset == "very_high"
        )
    ) or max(
        settings.denoise_strength,
        settings.chroma_repair_strength,
        settings.artifact_removal_strength,
        settings.sharpen_strength,
    ) >= 0.8:
        warnings.append(
            _warning(
                "These settings may cause over-processing and remove authentic VHS texture.",
                "over-processing",
            )
        )

    if settings.ai_upscale and (
        settings.ai_scale >= 4
        or (settings.ai_model and "anime" in settings.ai_model.casefold())
    ):
        warnings.append(
            _warning(
                "AI upscaling carries a hallucination risk: it may alter fine detail or Japanese text; review a preview.",
                "ai-hallucination",
            )
        )

    if classification == "Progressive" and settings.deinterlace not in {
        "auto",
        "off",
        "progressive",
    }:
        warnings.append(
            _warning(
                "The source is progressive but a field-order deinterlace was forced; this may soften the image.",
                "progressive-deinterlace",
            )
        )

    if settings.ai_upscale and settings.ai_backend == "none":
        warnings.append(
            _warning(
                "AI upscaling is enabled but no AI backend is selected; use a Vulkan backend or disable AI.",
                "ai-backend",
            )
        )
    if settings.ai_upscale and not settings.ai_model:
        warnings.append(
            _warning(
                "AI upscaling is enabled without a model; the backend may be unavailable.",
                "ai-model",
            )
        )

    if not settings.preserve_aspect or settings.aspect_mode == "pillarbox_16_9":
        warnings.append(
            _warning(
                "Confirm that the output preserves the source 4:3 composition; do not stretch VHS footage to 16:9.",
                "aspect-ratio",
            )
        )

    if settings.stabilization:
        warnings.append(
            _warning(
                "Stabilization is enabled and may change the original framing; use only when needed.",
                "stabilization",
            )
        )

    return warnings
