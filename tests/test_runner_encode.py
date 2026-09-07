import sys
from pathlib import Path

import pytest

from vhs_restore.analysis.source_info import SourceInfo
from vhs_restore.jobs import runner as runner_module
from vhs_restore.jobs.cache import JobCache
from vhs_restore.jobs.runner import JobError, RestoreJobRunner, build_ffmpeg_argv
from vhs_restore.pipeline.deinterlace import DeinterlaceDecision
from vhs_restore.pipeline.pipeline import PipelinePlan
from vhs_restore.settings import RestoreSettings
from vhs_restore.utils.process import start_command as real_start_command


_EMPTY_MP4 = (
    b"\x00\x00\x00 ftypisom\x00\x00\x02\x00isomiso2avc1mp41"
    b"\x00\x00\x00\x08free"
)


def _analysis(source: Path) -> SourceInfo:
    return SourceInfo(path=source, duration=442.98, width=720, height=480, frame_rate=30.0)


def _plan(source: Path, analysis: SourceInfo) -> PipelinePlan:
    return PipelinePlan(
        source=source,
        filters=("scale=1440:1080",),
        filter_graph="scale=1440:1080",
        deinterlace=DeinterlaceDecision(
            enabled=False,
            method="off",
            field_order=None,
            double_rate=False,
            input_frame_rate=None,
            output_frame_rate=None,
        ),
        restore_filters=("scale=1440:1080",),
        color_filters=(),
        stages=("restore",),
        start=221.492,
        duration=10.0,
        settings=RestoreSettings(),
        analysis=analysis,
    )


def test_source_restore_keeps_preview_window_and_filters(tmp_path: Path):
    source = tmp_path / "動物園.mp4"
    source.write_bytes(b"source")
    analysis = _analysis(source)
    argv = build_ffmpeg_argv(
        _plan(source, analysis),
        tmp_path / "restore.mkv",
        input_path=source,
        encode_args=("-f", "matroska", "-c:v", "ffv1"),
        progress=False,
    )

    input_index = argv.index("-i")
    assert argv[input_index - 4 : input_index] == ["-ss", "221.492", "-t", "10"]
    assert argv[argv.index("-vf") + 1] == "scale=1440:1080"


def test_encode_of_upscaled_preview_does_not_reseek_or_rescaler(tmp_path: Path):
    source = tmp_path / "動物園.mp4"
    source.write_bytes(b"source")
    upscaled = tmp_path / "upscaled.mkv"
    upscaled.write_bytes(b"upscaled")
    analysis = _analysis(source)
    argv = build_ffmpeg_argv(
        _plan(source, analysis),
        tmp_path / "preview.mp4",
        input_path=upscaled,
        encode_args=("-f", "mp4", "-c:v", "libx264", "-pix_fmt", "yuv420p"),
        progress=False,
    )

    assert "-ss" not in argv
    assert "-t" not in argv
    assert "-vf" not in argv
    assert argv[argv.index("-i") + 1] == str(upscaled)


def test_empty_ffmpeg_container_is_a_job_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "動物園.mp4"
    source.write_bytes(b"source")
    upscaled = tmp_path / "upscaled.mkv"
    upscaled.write_bytes(b"upscaled")
    artifact = tmp_path / "preview.mp4"
    artifact.write_bytes(_EMPTY_MP4)
    analysis = _analysis(source)
    plan = _plan(source, analysis)
    work_dir = tmp_path / "job"
    work_dir.mkdir()

    def fake_start(argv: list[str], **kwargs):
        on_output = kwargs.get("on_output")
        if callable(on_output):
            on_output("Output file is empty, nothing was encoded")
        Path(argv[-1]).write_bytes(_EMPTY_MP4)
        return real_start_command(
            [sys.executable, "-c", "pass"],
            cwd=kwargs.get("cwd"),
            on_output=kwargs.get("on_output"),
        )

    monkeypatch.setattr(runner_module, "start_command", fake_start)
    runner = RestoreJobRunner()
    runner._work_dir = work_dir
    manifest = runner_module.JobManifest(source, artifact, RestoreSettings())

    with pytest.raises(JobError, match="empty"):
        runner._run_ffmpeg_stage(
            stage="encode",
            plan=plan,
            input_path=upscaled,
            artifact=artifact,
            encode_args=("-f", "mp4"),
            manifest=manifest,
            manifest_file=work_dir / "manifest.json",
            duration=10.0,
        )


def test_cache_lookup_skips_empty_mp4_final(tmp_path: Path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    artifact = tmp_path / "preview.mp4"
    artifact.write_bytes(_EMPTY_MP4)
    cache = JobCache(tmp_path / "cache")
    cache.store(
        "final",
        artifact,
        source_hash="source",
        settings_hash="settings",
    )
    runner = RestoreJobRunner()
    manifest = runner_module.JobManifest(
        source,
        artifact,
        RestoreSettings(),
        source_hash="source",
        settings_hash="settings",
    )
    manifest.mark_stage("final", status="completed", artifact=artifact)

    assert runner._cache_artifact(cache, manifest, "final") is None
