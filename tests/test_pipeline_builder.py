from pathlib import Path
from types import SimpleNamespace

import pytest

from vhs_restore.analysis.interlace import InterlaceAnalysis
from vhs_restore.analysis.source_info import SourceInfo
from vhs_restore.pipeline import pipeline
from vhs_restore.pipeline.pipeline import build_pipeline
from vhs_restore.settings import RestoreSettings


def _interlaced_source() -> SourceInfo:
    return SourceInfo(
        path=Path("日本語 capture (raw) [01].avi"),
        width=720,
        height=480,
        frame_rate=30000 / 1001,
        field_order="TFF",
        interlace=InterlaceAnalysis("TFF", confidence=1.0),
    )


def test_preview_and_full_builds_share_the_same_filter_graph(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        pipeline,
        "detect_dependencies",
        lambda: SimpleNamespace(qtgmc_available=True),
    )
    settings = RestoreSettings(
        denoise_strength=0.2,
        chroma_repair_strength=0.25,
        artifact_removal_strength=0.1,
        sharpen_strength=0.05,
    )
    analysis = _interlaced_source()

    full = build_pipeline(settings, analysis)
    preview = build_pipeline(settings, analysis, start=12.5, duration=10.0)

    assert isinstance(full.filters, tuple)
    assert preview.filters == full.filters
    assert preview.filter_graph == full.filter_graph
    assert preview.restore_filters == full.restore_filters
    assert preview.color_filters == full.color_filters
    assert preview.deinterlace == full.deinterlace
    assert preview.qtgmc_script == full.qtgmc_script
    assert full.start is None
    assert full.duration is None
    assert preview.start == pytest.approx(12.5)
    assert preview.duration == pytest.approx(10.0)
    assert preview.output is None
    assert full.output is None


def test_pipeline_uses_bwdif_filter_and_surfaces_qtgmc_fallback_warning(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        pipeline,
        "detect_dependencies",
        lambda: SimpleNamespace(qtgmc_available=False),
    )

    plan = build_pipeline(RestoreSettings(), _interlaced_source())

    assert plan.deinterlace.method == "bwdif"
    assert "bwdif=mode=send_field:parity=tff:deint=all" in plan.filters
    assert any("QTGMC unavailable" in warning for warning in plan.warnings)


def test_pipeline_preserves_4_3_without_a_16_9_stretch():
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        pipeline,
        "detect_dependencies",
        lambda: SimpleNamespace(qtgmc_available=False),
    )
    try:
        plan = build_pipeline(RestoreSettings(), _interlaced_source())
    finally:
        monkeypatch.undo()

    assert plan.aspect_ratio == "4:3"
    assert plan.preserve_aspect is True
    assert "16:9" not in plan.filter_graph
    assert "setdar=4/3" in plan.filter_graph

