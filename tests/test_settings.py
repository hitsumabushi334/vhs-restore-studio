import json
from pathlib import Path

import pytest

from vhs_restore.analysis.interlace import InterlaceAnalysis
from vhs_restore.analysis.source_info import SourceInfo
from vhs_restore.settings import RestoreSettings, Warning, load_preset, validate_settings


def test_natural_preset_uses_fidelity_first_defaults():
    settings = load_preset("natural")

    assert settings.name == "Natural"
    assert settings.deinterlace == "auto"
    assert settings.qtgmc_preset == "balanced"
    assert settings.denoise_strength == pytest.approx(0.15)
    assert settings.chroma_repair_strength == pytest.approx(0.2)
    assert settings.artifact_removal_strength == pytest.approx(0.1)
    assert settings.sharpen_strength == pytest.approx(0.0)
    assert settings.stabilization is False
    assert settings.ai_upscale is False
    assert settings.ai_backend == "none"
    assert settings.ai_model is None
    assert settings.ai_scale == 1
    assert settings.preserve_aspect is True
    assert settings.aspect_mode == "preserve_4_3"
    assert settings.output_profile == "archive_practical"


def test_balanced_ai_preset_enables_conservative_vulkan_ai_defaults():
    settings = load_preset("Balanced AI")

    assert settings.name == "Balanced AI"
    assert settings.deinterlace == "auto"
    assert settings.qtgmc_preset == "balanced"
    assert settings.denoise_strength == pytest.approx(0.2)
    assert settings.chroma_repair_strength == pytest.approx(0.25)
    assert settings.artifact_removal_strength == pytest.approx(0.15)
    assert settings.sharpen_strength == pytest.approx(0.05)
    assert settings.stabilization is False
    assert settings.ai_upscale is True
    assert settings.ai_backend == "realesrgan-ncnn-vulkan"
    assert settings.ai_model == "realesrgan-x4plus"
    assert settings.ai_scale == 2
    assert settings.preserve_aspect is True
    assert settings.aspect_mode == "preserve_4_3"


def test_load_preset_accepts_packaged_presets_and_rejects_unknown_names():
    for name in ("natural", "balanced_ai", "strong_ai", "dvd", "archive"):
        settings = load_preset(name)
        assert isinstance(settings, RestoreSettings)
        assert settings.name

    with pytest.raises(ValueError, match="unknown preset"):
        load_preset("not-a-preset")


def test_preset_files_have_the_complete_settings_schema():
    root = Path(__file__).resolve().parents[1]
    required = {
        "name",
        "description",
        "deinterlace",
        "qtgmc_preset",
        "denoise_strength",
        "chroma_repair_strength",
        "artifact_removal_strength",
        "sharpen_strength",
        "stabilization",
        "ai_upscale",
        "ai_backend",
        "ai_model",
        "ai_scale",
        "preserve_aspect",
        "aspect_mode",
        "output_profile",
    }

    for path in sorted((root / "presets").glob("*.json")):
        assert required <= set(json.loads(path.read_text(encoding="utf-8")))


def test_validate_settings_warns_about_combined_over_processing():
    settings = RestoreSettings(
        name="Custom",
        description="test",
        deinterlace="auto",
        qtgmc_preset="very_high",
        denoise_strength=0.85,
        chroma_repair_strength=0.9,
        artifact_removal_strength=0.8,
        sharpen_strength=0.85,
        stabilization=False,
        ai_upscale=True,
        ai_backend="realesrgan-ncnn-vulkan",
        ai_model="realesrgan-x4plus-anime",
        ai_scale=4,
        preserve_aspect=True,
        aspect_mode="preserve_4_3",
        output_profile="archive_practical",
    )
    analysis = SourceInfo(
        path=Path("capture.mkv"),
        width=720,
        height=480,
        frame_rate=30000 / 1001,
        interlace=InterlaceAnalysis("TFF", 1.0),
    )

    warnings = validate_settings(settings, analysis)

    assert warnings
    assert all(isinstance(item, Warning) for item in warnings)
    messages = " ".join(item.message for item in warnings).lower()
    assert "over-processing" in messages
    assert "hallucination" in messages


def test_validate_settings_warns_when_progressive_source_is_forced_to_deinterlace():
    settings = load_preset("natural")
    settings = RestoreSettings(**{**settings.to_dict(), "deinterlace": "tff"})
    analysis = SourceInfo(
        path=Path("progressive.mkv"),
        frame_rate=30000 / 1001,
        interlace=InterlaceAnalysis("Progressive", 1.0),
    )

    warnings = validate_settings(settings, analysis)

    assert any("progressive" in item.message.lower() for item in warnings)


def test_validate_settings_returns_no_warnings_for_natural_progressive_input():
    settings = load_preset("natural")
    analysis = SourceInfo(
        path=Path("progressive.mkv"),
        width=720,
        height=480,
        frame_rate=30000 / 1001,
        interlace=InterlaceAnalysis("Progressive", 1.0),
    )

    assert validate_settings(settings, analysis) == []

