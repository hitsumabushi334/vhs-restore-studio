import json
from pathlib import Path

import pytest

from vhs_restore.analysis.interlace import InterlaceAnalysis
from vhs_restore.analysis.source_info import SourceInfo
from vhs_restore.jobs.manifest import settings_hash
from vhs_restore.settings import RestoreSettings, Warning, load_preset, validate_settings


def test_natural_preset_uses_fidelity_first_defaults():
    settings = load_preset("natural")

    assert settings.name == "Natural"
    assert settings.deinterlace == "auto"
    assert settings.qtgmc_preset == "high"
    assert settings.denoise_strength == pytest.approx(0.18)
    assert settings.chroma_repair_strength == pytest.approx(0.28)
    assert settings.artifact_removal_strength == pytest.approx(0.1)
    assert settings.sharpen_strength == pytest.approx(0.05)
    assert settings.stabilization is False
    assert settings.ai_upscale is False
    assert settings.ai_backend == "none"
    assert settings.ai_model is None
    assert settings.ai_scale == 1
    assert settings.target_resolution == "1440x1080"
    assert settings.target_width is None
    assert settings.target_height is None
    assert settings.pipeline_version == 2
    assert settings.preserve_aspect is True
    assert settings.aspect_mode == "preserve_4_3"
    assert settings.output_profile == "archive_practical"


def test_balanced_ai_preset_enables_video2x_ai_defaults():
    settings = load_preset("Balanced AI")

    assert settings.name == "Balanced AI"
    assert settings.deinterlace == "auto"
    assert settings.qtgmc_preset == "high"
    assert settings.denoise_strength == pytest.approx(0.28)
    assert settings.chroma_repair_strength == pytest.approx(0.45)
    assert settings.artifact_removal_strength == pytest.approx(0.15)
    assert settings.sharpen_strength == pytest.approx(0.08)
    assert settings.stabilization is False
    assert settings.ai_upscale is True
    assert settings.ai_backend == "video2x"
    assert settings.ai_model == "realesrgan-x4plus"
    assert settings.ai_scale == 2
    assert settings.target_resolution == "1440x1080"
    assert settings.preserve_aspect is True
    assert settings.aspect_mode == "preserve_4_3"




def test_load_preset_accepts_packaged_presets_and_rejects_unknown_names():
    for name in ("natural", "balanced_ai", "strong_ai", "dvd", "archive"):
        settings = load_preset(name)
        assert isinstance(settings, RestoreSettings)
        assert settings.name

    with pytest.raises(ValueError, match="unknown preset"):
        load_preset("not-a-preset")


def test_preset_files_have_the_complete_settings_schema_and_match():
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
        "target_resolution",
        "target_width",
        "target_height",
        "pipeline_version",
        "preserve_aspect",
        "aspect_mode",
        "output_profile",
    }

    root_presets = root / "presets"
    packaged_presets = root / "src" / "vhs_restore" / "assets" / "presets"
    for path in sorted(root_presets.glob("*.json")):
        values = json.loads(path.read_text(encoding="utf-8"))
        assert required <= set(values)
        assert values == json.loads(
            (packaged_presets / path.name).read_text(encoding="utf-8")
        )

def test_from_mapping_accepts_legacy_mapping_and_infers_target_resolution():
    values = load_preset("natural").to_dict()
    values["output_profile"] = "dvd"
    for field in ("target_resolution", "target_width", "target_height", "pipeline_version"):
        values.pop(field)

    settings = RestoreSettings.from_mapping(values)

    assert settings.target_resolution == "720x480"
    assert settings.target_width is None
    assert settings.target_height is None
    assert settings.pipeline_version == 2


def test_from_mapping_rejects_invalid_target_resolution_and_custom_dimensions():
    values = load_preset("natural").to_dict()

    values["target_resolution"] = "1024x768"
    with pytest.raises(ValueError, match="target_resolution"):
        RestoreSettings.from_mapping(values)

    values["target_resolution"] = "custom"
    values["target_width"] = 0
    values["target_height"] = 480
    with pytest.raises(ValueError, match="target_width"):
        RestoreSettings.from_mapping(values)


def test_validate_settings_warns_when_dvd_output_will_downscale_ai():
    settings = RestoreSettings(
        ai_upscale=True,
        ai_backend="video2x",
        ai_model="realesrgan-x4plus",
        ai_scale=2,
        output_profile="dvd",
        target_resolution="720x480",
    )

    warnings = validate_settings(settings, InterlaceAnalysis("Progressive", 1.0))

    assert any(item.code == "dvd-ai" for item in warnings)


def test_settings_hash_includes_pipeline_version():
    values = load_preset("natural").to_dict()
    version_one = {**values, "pipeline_version": 1}
    version_two = {**values, "pipeline_version": 2}

    assert set(version_one) == set(version_two)
    assert settings_hash(version_one) != settings_hash(version_two)

@pytest.mark.parametrize(
    "field",
    ("deinterlace", "qtgmc_preset", "ai_backend", "aspect_mode", "output_profile"),
)
def test_from_mapping_rejects_non_string_enum_values_with_value_error(field):
    values = load_preset("natural").to_dict()
    values[field] = []

    with pytest.raises(ValueError):
        RestoreSettings.from_mapping(values)


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
