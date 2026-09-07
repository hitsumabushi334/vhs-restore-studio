from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from vhs_restore.analysis.interlace import InterlaceAnalysis
from vhs_restore.analysis.source_info import SourceInfo
from vhs_restore.pipeline import pipeline
from vhs_restore.pipeline.pipeline import build_pipeline, describe_processing_plan
from vhs_restore.settings import RestoreSettings


def _source() -> SourceInfo:
    return SourceInfo(
        path=Path("capture.mkv"),
        width=720,
        height=480,
        frame_rate=30000 / 1001,
        field_order="TFF",
        interlace=InterlaceAnalysis("TFF", confidence=1.0),
    )


def _settings(**changes) -> RestoreSettings:
    return replace(
        RestoreSettings(
            target_resolution="1440x1080",
            ai_upscale=True,
            ai_backend="video2x",
            ai_model="realesrgan-x4plus",
            ai_scale=2,
            denoise_strength=0.28,
            chroma_repair_strength=0.45,
            artifact_removal_strength=0.15,
            sharpen_strength=0.08,
        ),
        **changes,
    )


@pytest.fixture(autouse=True)
def _qtgmc_available(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        pipeline,
        "detect_dependencies",
        lambda: SimpleNamespace(qtgmc_available=False),
    )


def test_ai_pipeline_does_not_pre_resize():
    plan = build_pipeline(_settings(), _source())

    assert all("scale=1440:1080" not in expression for expression in plan.restore_filters)
    assert all(not expression.startswith("pad=") for expression in plan.restore_filters)


def test_ai_input_remains_native_resolution():
    plan = build_pipeline(_settings(), _source())

    assert plan.restore_filters
    assert all(not expression.startswith(("scale=", "pad=")) for expression in plan.restore_filters)


def test_geometry_runs_after_upscale():
    plan = build_pipeline(_settings(), _source())

    assert plan.final_geometry_filters
    assert not set(plan.final_geometry_filters).intersection(plan.restore_filters)
    assert plan.filters.index(plan.final_geometry_filters[0]) > plan.filters.index(plan.restore_filters[-1])


def test_balanced_ai_final_resolution():
    plan = build_pipeline(_settings(), _source())

    assert plan.final_geometry_filters[0].startswith("scale=1440:1080:")
    assert any(expression.startswith("pad=1440:1080") for expression in plan.final_geometry_filters)
    assert "scale=1440:1080" in plan.filter_graph
    assert describe_processing_plan(plan).endswith("Final: 1440x1080")


def test_ai_disabled_pipeline():
    plan = build_pipeline(_settings(ai_upscale=False, ai_backend="none", ai_scale=1, sharpen_strength=0.08), _source())

    assert plan.final_geometry_filters
    assert plan.final_sharpen_filters
    assert all("scale=" not in expression for expression in plan.restore_filters)
    assert all("unsharp=" not in expression for expression in plan.restore_filters)
    assert "unsharp=" in plan.filter_graph


def test_preview_uses_same_pipeline_order():
    settings = _settings()
    source = _source()
    full = build_pipeline(settings, source)
    preview = build_pipeline(settings, source, start=10, duration=5)

    assert preview.filters == full.filters
    assert preview.filter_graph == full.filter_graph
    assert preview.final_geometry_filters == full.final_geometry_filters
    assert preview.final_sharpen_filters == full.final_sharpen_filters


