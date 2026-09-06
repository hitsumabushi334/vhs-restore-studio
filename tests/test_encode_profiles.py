from pathlib import Path

import pytest

from vhs_restore.analysis.interlace import InterlaceAnalysis
from vhs_restore.analysis.source_info import SourceInfo
from vhs_restore.pipeline.encode import build_encode_args
from vhs_restore.settings import RestoreSettings


def _analysis(
    *,
    duration: float = 7200.0,
    frame_rate: float = 30000 / 1001,
    field_order: str | None = "TFF",
    classification: str | None = None,
) -> SourceInfo:
    classification = classification or field_order or "Progressive"
    return SourceInfo(
        path=Path("日本語 capture (raw) [01].avi"),
        duration=duration,
        width=720,
        height=480,
        frame_rate=frame_rate,
        field_order=field_order,
        interlace=InterlaceAnalysis(classification, confidence=1.0),
    )


def _settings(profile: str) -> RestoreSettings:
    return RestoreSettings(output_profile=profile)


def _option(args: list[str], name: str) -> str:
    index = args.index(name)
    return args[index + 1]


def test_archive_hq_uses_lossless_ffv1_in_matroska_with_flac_audio():
    args = build_encode_args(
        "archive_hq",
        _analysis(),
        _settings("archive_hq"),
    )

    assert _option(args, "-f") == "matroska"
    assert _option(args, "-c:v") == "ffv1"
    assert _option(args, "-c:a") == "flac"
    assert "-crf" not in args


def test_archive_practical_uses_high_quality_h264_and_aac():
    args = build_encode_args(
        "archive_practical",
        _analysis(),
        _settings("archive_practical"),
    )

    assert _option(args, "-c:v") == "libx264"
    assert _option(args, "-preset") == "slow"
    assert _option(args, "-crf") == "16"
    assert _option(args, "-c:a") == "aac"
    assert _option(args, "-pix_fmt") == "yuv420p"


def test_compatibility_uses_mp4_h264_aac_and_faststart():
    args = build_encode_args(
        "compatibility",
        _analysis(),
        _settings("compatibility"),
    )

    assert _option(args, "-f") == "mp4"
    assert _option(args, "-c:v") == "libx264"
    assert _option(args, "-profile:v") == "high"
    assert _option(args, "-c:a") == "aac"
    assert _option(args, "-movflags") == "+faststart"


@pytest.mark.parametrize(
    ("field_order", "expected_interleave", "expected_top"),
    [("TFF", "tinterlace=interleave_top", "1"), ("BFF", "tinterlace=interleave_bottom", "0")],
)
def test_dvd_pairs_5994p_frames_into_2997i_fields(
    field_order: str,
    expected_interleave: str,
    expected_top: str,
):
    args = build_encode_args(
        "dvd",
        _analysis(field_order=field_order),
        _settings("dvd"),
    )

    assert _option(args, "-c:v") == "mpeg2video"
    assert _option(args, "-c:a") == "ac3"
    assert _option(args, "-target") == "ntsc-dvd"
    assert _option(args, "-r") == "30000/1001"
    assert expected_interleave in _option(args, "-vf")
    assert _option(args, "-top") == expected_top
    assert "+ilme+ildct" in _option(args, "-flags")
    assert _option(args, "-s") == "720x480"


def test_dvd_uses_progressive_output_without_field_pairing_for_2997p_source():
    args = build_encode_args(
        "dvd",
        _analysis(frame_rate=30000 / 1001, field_order="Progressive"),
        _settings("dvd"),
    )

    assert "tinterlace=" not in _option(args, "-vf")
    assert _option(args, "-r") == "30000/1001"


def test_archive_keeps_actual_5994p_progressive_source_at_5994p():
    args = build_encode_args(
        "archive_practical",
        _analysis(
            frame_rate=60000 / 1001,
            field_order="Progressive",
            classification="Progressive",
        ),
        _settings("archive_practical"),
    )

    assert _option(args, "-r") == "60000/1001"


def test_dvd_packs_actual_5994p_progressive_source_into_explicit_tff_fields():
    args = build_encode_args(
        "dvd",
        _analysis(
            frame_rate=60000 / 1001,
            field_order="Progressive",
            classification="Progressive",
        ),
        _settings("dvd"),
    )

    assert _option(args, "-r") == "30000/1001"
    assert _option(args, "-vf") == "tinterlace=interleave_top"
    assert _option(args, "-top") == "1"


@pytest.mark.parametrize("mode", ["off", "progressive"])
def test_deinterlace_disabled_keeps_2997_tff_at_2997p(mode: str):
    settings = RestoreSettings(deinterlace=mode, output_profile="archive_practical")

    args = build_encode_args("archive_practical", _analysis(), settings)
    dvd_args = build_encode_args(
        "dvd",
        _analysis(),
        RestoreSettings(deinterlace=mode, output_profile="dvd"),
    )

    assert _option(args, "-r") == "30000/1001"
    assert _option(dvd_args, "-r") == "30000/1001"
    assert "tinterlace=" not in _option(dvd_args, "-vf")


@pytest.mark.parametrize(
    ("mode", "expected_rate", "expected_interleave", "expected_top"),
    [
        ("tff", "60000/1001", "tinterlace=interleave_top", "1"),
        ("bff", "60000/1001", "tinterlace=interleave_bottom", "0"),
    ],
)
def test_forced_deinterlace_controls_progressive_2997_cadence(
    mode: str,
    expected_rate: str,
    expected_interleave: str,
    expected_top: str,
):
    analysis = _analysis(
        field_order="Progressive",
        classification="Progressive",
    )
    settings = RestoreSettings(deinterlace=mode, output_profile="dvd")

    archive_args = build_encode_args("archive_practical", analysis, settings)
    dvd_args = build_encode_args("dvd", analysis, settings)

    assert _option(archive_args, "-r") == expected_rate
    assert expected_interleave in _option(dvd_args, "-vf")
    assert _option(dvd_args, "-top") == expected_top


@pytest.mark.parametrize("classification", ["Unknown", "Mixed"])
def test_dvd_rejects_unresolved_field_order(classification: str):
    analysis = _analysis(
        field_order=None,
        classification=classification,
    )

    with pytest.raises(ValueError, match="field order"):
        build_encode_args("dvd", analysis, _settings("dvd"))


def test_dvd_rejects_missing_duration_needed_for_bitrate_planning():
    with pytest.raises(ValueError, match="duration"):
        build_encode_args(
            "dvd",
            _analysis(duration=None),
            _settings("dvd"),
        )


def test_unknown_encode_profile_is_rejected():
    with pytest.raises(ValueError, match="profile"):
        build_encode_args("webm", _analysis(), _settings("webm"))
