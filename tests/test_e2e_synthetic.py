"""Real-FFmpeg smoke coverage for the restore pipeline."""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest

from tests.fixtures.media import make_bff_clip, make_progressive_clip, make_tff_clip
from vhs_restore.analysis.ffprobe import probe_source
from vhs_restore.analysis.interlace import analyze_interlace
from vhs_restore.jobs.runner import RestoreJobRunner
from vhs_restore.pipeline.pipeline import build_pipeline
from vhs_restore.settings import load_preset

_FFPROBE = shutil.which("ffprobe")
if _FFPROBE is None:
    pytest.skip("ffprobe is required for synthetic media tests", allow_module_level=True)


def _analyzed(source: Path):
    info = probe_source(source)
    assert info.duration is not None
    interlace = analyze_interlace(
        source,
        info.duration,
        metadata_field_order=info.field_order,
    )
    return info.with_interlace(interlace)


def _probe_media(path: Path) -> dict[str, object]:
    argv = [
        str(_FFPROBE),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    result = subprocess.run(argv, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def _video_stream(metadata: dict[str, object]) -> dict[str, object]:
    streams = metadata.get("streams", [])
    return next(stream for stream in streams if stream.get("codec_type") == "video")


def _aspect_ratio(value: object) -> float:
    numerator, denominator = str(value).replace(":", "/").split("/", 1)
    return float(Fraction(int(numerator), int(denominator)))


def _run_restore(source: Path, output: Path, analysis, settings):
    runner = RestoreJobRunner(
        job_dir=output.parent / "jobs",
        cache_dir=output.parent / "cache",
        free_space_checker=lambda _: 10**12,
        minimum_free_space=0,
    )
    result = runner.run(source, analysis, settings, output)
    assert result.status == "completed"
    assert output.is_file()
    return result


@pytest.mark.parametrize(
    ("maker", "expected"),
    ((make_tff_clip, "TFF"), (make_bff_clip, "BFF")),
)
def test_real_interlace_analysis_preserves_field_order(tmp_path: Path, maker, expected):
    source = maker(tmp_path / f"{expected.lower()} source.mkv")
    analysis = _analyzed(source)

    assert analysis.interlace is not None
    assert analysis.interlace.classification == expected

def test_progressive_5994_source_does_not_enable_deinterlace(tmp_path: Path):
    source = make_progressive_clip(tmp_path / "progressive 59.94p.mkv")
    analysis = _analyzed(source)

    assert analysis.interlace is not None
    # MPEG-4's inter-field compression can make idet report Mixed for a
    # genuinely progressive testsrc2 stream.  The progressive metadata is
    # authoritative for this 59.94p pipeline decision.
    assert analysis.field_order is not None
    assert analysis.field_order.casefold() == "progressive"
    assert analysis.interlace.classification in {"Progressive", "Mixed"}
    plan = build_pipeline(load_preset("natural"), analysis)

    assert plan.deinterlace.enabled is False
    assert plan.deinterlace.method == "off"
    assert "tinterlace" not in plan.filter_graph


def test_interlaced_restore_outputs_double_rate_and_archive_4_3(tmp_path: Path):
    source = make_tff_clip(tmp_path / "capture source.mkv")
    source_stream = _video_stream(_probe_media(source))
    assert _aspect_ratio(source_stream["display_aspect_ratio"]) == pytest.approx(4 / 3, abs=0.01)

    analysis = _analyzed(source)
    settings = replace(load_preset("natural"), output_profile="compatibility")
    output = tmp_path / "restored output.mp4"

    _run_restore(source, output, analysis, settings)
    stream = _video_stream(_probe_media(output))
    frame_rate = float(Fraction(str(stream["avg_frame_rate"])))

    assert frame_rate == pytest.approx(60000 / 1001, abs=0.05)
    assert stream["width"] == 1440
    assert stream["height"] == 1080
    assert _aspect_ratio(stream["display_aspect_ratio"]) == pytest.approx(4 / 3, abs=0.01)


def test_preview_and_full_plans_have_identical_processing_graph(tmp_path: Path):
    source = make_tff_clip(tmp_path / "source.mkv")
    analysis = _analyzed(source)
    settings = replace(load_preset("natural"), output_profile="compatibility")
    full = build_pipeline(settings, analysis, output=tmp_path / "full.mp4")
    preview = build_pipeline(
        settings,
        analysis,
        start=10.0,
        duration=10.0,
        output=tmp_path / "preview.mp4",
    )

    assert preview.filters == full.filters
    assert preview.filter_graph == full.filter_graph
    assert preview.restore_filters == full.restore_filters
    assert preview.color_filters == full.color_filters
    assert preview.deinterlace == full.deinterlace


def test_restore_accepts_japanese_and_space_paths_without_touching_source(tmp_path: Path):
    folder = tmp_path / "マイドライブ" / "VHS captures"
    source = make_tff_clip(folder / "raw tape [01] source.mkv")
    original = source.read_bytes()
    analysis = _analyzed(source)
    output = folder / "restored copy [01].mp4"
    settings = replace(load_preset("natural"), output_profile="compatibility")

    _run_restore(source, output, analysis, settings)

    assert source.read_bytes() == original


def test_cancel_real_ffmpeg_job_leaves_partial_and_no_completed_output(tmp_path: Path):
    source = make_tff_clip(tmp_path / "cancel source.mkv")
    original = source.read_bytes()
    analysis = _analyzed(source)
    output = tmp_path / "cancelled output.mp4"
    settings = replace(load_preset("natural"), output_profile="compatibility")
    runner = RestoreJobRunner(
        job_dir=tmp_path / "jobs",
        cache_dir=tmp_path / "cache",
        free_space_checker=lambda _: 10**12,
        minimum_free_space=0,
    )
    holder: dict[str, object] = {}

    def run_job() -> None:
        holder["result"] = runner.run(source, analysis, settings, output)

    thread = threading.Thread(target=run_job)
    thread.start()
    deadline = time.monotonic() + 10.0
    while runner.current_process is None and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert runner.current_process is not None, "real ffmpeg stage did not start"
    runner.cancel()
    thread.join(timeout=15.0)

    assert not thread.is_alive()
    result = holder["result"]
    assert result.status == "cancelled"
    assert not output.exists()
    assert Path(f"{output}.partial").exists()
    assert source.read_bytes() == original


def test_restore_preserves_audio_duration(tmp_path: Path):
    source = make_progressive_clip(tmp_path / "audio source.mkv")
    source_metadata = _probe_media(source)
    source_duration = float(source_metadata["format"]["duration"])
    analysis = _analyzed(source)
    settings = replace(load_preset("natural"), output_profile="compatibility")
    output = tmp_path / "audio restored.mp4"

    _run_restore(source, output, analysis, settings)
    output_metadata = _probe_media(output)
    output_streams = output_metadata["streams"]
    audio_streams = [stream for stream in output_streams if stream.get("codec_type") == "audio"]
    video_streams = [stream for stream in output_streams if stream.get("codec_type") == "video"]
    assert audio_streams
    assert video_streams
    audio_duration = float(audio_streams[0]["duration"])
    video_duration = float(video_streams[0]["duration"])

    assert abs(audio_duration - video_duration) < 0.15
    assert audio_duration == pytest.approx(source_duration, abs=0.3)
    assert video_duration == pytest.approx(source_duration, abs=0.3)


def test_dvd_preset_encodes_ntsc_4_3_video(tmp_path: Path):
    source = make_tff_clip(tmp_path / "dvd source.mkv")
    source_stream = _video_stream(_probe_media(source))
    assert _aspect_ratio(source_stream["display_aspect_ratio"]) == pytest.approx(4 / 3, abs=0.01)

    analysis = _analyzed(source)
    output = tmp_path / "dvd restored.vob"

    _run_restore(source, output, analysis, load_preset("dvd"))
    stream = _video_stream(_probe_media(output))

    assert stream["width"] == 720
    assert stream["height"] == 480
    assert _aspect_ratio(stream["display_aspect_ratio"]) == pytest.approx(4 / 3, abs=0.01)
