from pathlib import Path

from vhs_restore.analysis.source_info import SourceInfo
from vhs_restore.pipeline.geometry import build_geometry_filters, resolve_target_size
from vhs_restore.settings import RestoreSettings


def _source(*, width: int = 720, height: int = 480) -> SourceInfo:
    return SourceInfo(path=Path("capture.mkv"), width=width, height=height, frame_rate=30000 / 1001)


def test_dvd_geometry():
    settings = RestoreSettings(target_resolution="720x480", output_profile="dvd")

    filters = build_geometry_filters(settings, _source())

    assert resolve_target_size(settings, _source()) == (720, 480)
    assert filters == (
        "scale=720:480:force_original_aspect_ratio=decrease",
        "pad=720:480:(ow-iw)/2:(oh-ih)/2:color=black",
        "setsar=8/9",
        "setdar=4/3",
    )


def test_four_three_aspect():
    settings = RestoreSettings(target_resolution="1920x1080")

    filters = build_geometry_filters(settings, _source())

    assert "scale=1440:1080:force_original_aspect_ratio=decrease" in filters
    assert "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black" in filters
    assert "setdar=16/9" in filters
    assert "scale=1920:1080" not in filters


def test_native_geometry_scales_and_pads_back_to_source_size():
    settings = RestoreSettings(target_resolution="native")

    filters = build_geometry_filters(settings, _source())

    assert "scale=720:480:force_original_aspect_ratio=decrease" in filters
    assert "pad=720:480:(ow-iw)/2:(oh-ih)/2:color=black" in filters
    assert "setsar=8/9" in filters
    assert "setdar=4/3" in filters


def test_custom_geometry_uses_requested_canvas():
    settings = RestoreSettings(
        target_resolution="custom",
        target_width=1280,
        target_height=960,
    )

    assert resolve_target_size(settings, _source()) == (1280, 960)
    filters = build_geometry_filters(settings, _source())
    assert filters[0].startswith("scale=1280:960:")
    assert filters[1].startswith("pad=1280:960:")
