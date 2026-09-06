import sys
from pathlib import Path

import pytest

from vhs_restore.analysis.source_info import SourceInfo
from vhs_restore.jobs import runner as runner_module
from vhs_restore.jobs.runner import JobError, RestoreJobRunner
from vhs_restore.pipeline.deinterlace import DeinterlaceDecision
from vhs_restore.pipeline.pipeline import PipelinePlan
from vhs_restore.settings import RestoreSettings
from vhs_restore.utils.process import start_command as real_start_command


def _qtgmc_plan(source: Path, analysis: SourceInfo) -> PipelinePlan:
    script = "import vapoursynth as vs\nimport havsfunc\nclip = vs.core.std.BlankClip()\nclip.set_output()\n"
    decision = DeinterlaceDecision(
        enabled=True,
        method="qtgmc",
        field_order="TFF",
        double_rate=True,
        input_frame_rate=30000 / 1001,
        output_frame_rate=60000 / 1001,
        qtgmc_script=script,
    )
    return PipelinePlan(
        source=source,
        filters=("eq=contrast=1.1",),
        filter_graph="eq=contrast=1.1",
        deinterlace=decision,
        restore_filters=(),
        color_filters=("eq=contrast=1.1",),
        stages=("deinterlace", "color"),
        start=3.0,
        duration=5.0,
        qtgmc_script=script,
        settings=RestoreSettings(),
        analysis=analysis,
    )


def test_restore_runs_vspipe_before_ffmpeg_and_keeps_trim_on_ffmpeg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "interlaced source.avi"
    source.write_bytes(b"source")
    output = tmp_path / "restored.mkv"
    analysis = SourceInfo(path=source, duration=20.0, width=720, height=480)
    plan = _qtgmc_plan(source, analysis)
    captured: list[list[str]] = []

    def fake_start(argv: list[str], **kwargs):
        captured.append(list(argv))
        if "--y4m" not in argv:
            Path(argv[-1]).write_bytes(b"encoded")
        return real_start_command(
            [sys.executable, "-c", "pass"],
            cwd=kwargs.get("cwd"),
            on_output=kwargs.get("on_output"),
        )

    monkeypatch.setattr(runner_module, "build_pipeline", lambda *args, **kwargs: plan)
    monkeypatch.setattr(runner_module, "build_encode_args", lambda *args, **kwargs: [])
    monkeypatch.setattr(runner_module, "start_command", fake_start)

    result = RestoreJobRunner(
        job_dir=tmp_path / "job",
        free_space_checker=lambda _: 10**12,
    ).run(source, analysis, RestoreSettings(), output)

    assert result.status == "completed"
    assert len(captured) == 2
    vspipe_argv, ffmpeg_argv = captured
    assert vspipe_argv[0].casefold().endswith("vspipe")
    qtgmc_dir = tmp_path / "job" / "qtgmc"
    assert vspipe_argv[1:] == [
        "--y4m",
        str(qtgmc_dir / "restore.qtgmc.vpy"),
        "-",
    ]
    assert (qtgmc_dir / "restore.qtgmc.vpy").read_text(encoding="utf-8").startswith(
        "import vapoursynth as vs\nimport havsfunc\n"
    )
    assert ffmpeg_argv[0] == "ffmpeg"
    input_indices = [index for index, value in enumerate(ffmpeg_argv) if value == "-i"]
    assert len(input_indices) == 2
    assert ffmpeg_argv[input_indices[0] + 1] == "pipe:0"
    assert "-ss" not in ffmpeg_argv[: input_indices[0]]
    assert "-t" not in ffmpeg_argv[: input_indices[0]]
    second_input = input_indices[1]
    assert ffmpeg_argv[second_input - 4 : second_input] == ["-ss", "3", "-t", "5"]
    filter_index = ffmpeg_argv.index("-vf")
    assert "trim=start=3:duration=5,setpts=PTS-STARTPTS" in ffmpeg_argv[
        filter_index + 1
    ]
    assert ffmpeg_argv[ffmpeg_argv.index("-map") + 1] == "0:v:0"
    second_map = ffmpeg_argv.index("-map", ffmpeg_argv.index("-map") + 1)
    assert ffmpeg_argv[second_map + 1] == "1:a?"
    assert "eq=contrast=1.1" in ffmpeg_argv[filter_index + 1]



def test_qtgmc_does_not_delete_source_named_like_intermediate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "restore.qtgmc.y4m"
    source.write_bytes(b"original source bytes")
    output = tmp_path / "restored.mkv"
    analysis = SourceInfo(path=source, duration=20.0, width=720, height=480)
    plan = _qtgmc_plan(source, analysis)

    def fake_start(argv: list[str], **kwargs):
        if "--y4m" not in argv:
            Path(argv[-1]).write_bytes(b"encoded")
        return real_start_command(
            [sys.executable, "-c", "pass"],
            cwd=kwargs.get("cwd"),
            on_output=kwargs.get("on_output"),
        )

    monkeypatch.setattr(runner_module, "build_pipeline", lambda *args, **kwargs: plan)
    monkeypatch.setattr(runner_module, "build_encode_args", lambda *args, **kwargs: [])
    monkeypatch.setattr(runner_module, "start_command", fake_start)

    result = RestoreJobRunner(
        job_dir=source.parent,
        free_space_checker=lambda _: 10**12,
    ).run(source, analysis, RestoreSettings(), output)

    assert result.status == "completed"
    assert source.read_bytes() == b"original source bytes"


def test_qtgmc_refuses_to_overwrite_source_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    job_dir = tmp_path / "job"
    source = job_dir / "qtgmc" / "restore.qtgmc.vpy"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"original source script")
    output = tmp_path / "restored.mkv"
    analysis = SourceInfo(path=source, duration=20.0, width=720, height=480)
    plan = _qtgmc_plan(source, analysis)

    monkeypatch.setattr(runner_module, "build_pipeline", lambda *args, **kwargs: plan)
    monkeypatch.setattr(runner_module, "build_encode_args", lambda *args, **kwargs: [])

    with pytest.raises(JobError, match="source script"):
        RestoreJobRunner(
            job_dir=job_dir,
            free_space_checker=lambda _: 10**12,
        ).run(source, analysis, RestoreSettings(), output)

    assert source.read_bytes() == b"original source script"


def test_qtgmc_start_failure_is_a_job_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "interlaced.avi"
    source.write_bytes(b"source")
    output = tmp_path / "restored.mkv"
    analysis = SourceInfo(path=source, duration=20.0, width=720, height=480)
    plan = _qtgmc_plan(source, analysis)
    captured: list[list[str]] = []

    def failing_start(argv: list[str], **kwargs):
        captured.append(list(argv))
        raise FileNotFoundError("vspipe not found")

    monkeypatch.setattr(runner_module, "build_pipeline", lambda *args, **kwargs: plan)
    monkeypatch.setattr(runner_module, "build_encode_args", lambda *args, **kwargs: [])
    monkeypatch.setattr(runner_module, "start_command", failing_start)

    with pytest.raises(JobError, match="vspipe"):
        RestoreJobRunner(
            job_dir=tmp_path / "job",
            free_space_checker=lambda _: 10**12,
        ).run(source, analysis, RestoreSettings(), output)

    assert len(captured) == 1
    assert "--y4m" in captured[0]
    assert not output.exists()


def test_encode_stage_does_not_rerun_qtgmc_for_non_source_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "interlaced.avi"
    source.write_bytes(b"source")
    input_path = tmp_path / "upscaled.mkv"
    input_path.write_bytes(b"upscaled")
    artifact = tmp_path / "final.mkv"
    analysis = SourceInfo(path=source, duration=20.0, width=720, height=480)
    settings = RestoreSettings()
    plan = _qtgmc_plan(source, analysis)
    captured: list[list[str]] = []

    def fake_start(argv: list[str], **kwargs):
        captured.append(list(argv))
        Path(argv[-1]).write_bytes(b"encoded")
        return real_start_command(
            [sys.executable, "-c", "pass"],
            cwd=kwargs.get("cwd"),
            on_output=kwargs.get("on_output"),
        )

    monkeypatch.setattr(runner_module, "start_command", fake_start)
    work_dir = tmp_path / "job"
    work_dir.mkdir()
    runner = RestoreJobRunner()
    runner._work_dir = work_dir
    manifest = runner_module.JobManifest(source, artifact, settings)

    runner._run_ffmpeg_stage(
        stage="encode",
        plan=plan,
        input_path=input_path,
        artifact=artifact,
        encode_args=(),
        manifest=manifest,
        manifest_file=work_dir / "manifest.json",
        duration=5.0,
    )

    assert len(captured) == 1
    assert "--y4m" not in captured[0]
    assert captured[0][captured[0].index("-i") + 1] == str(input_path)
    assert str(source) not in captured[0]
    assert "-map" not in captured[0]
 
def test_process_group_falls_back_to_raw_process_handles():
    class RawProcess:
        def __init__(self):
            self.kill_calls = 0

        def kill(self):
            self.kill_calls += 1

    class WrappedProcess:
        returncode = None

        def __init__(self, raw):
            self._process = raw
            self.kill_calls = 0

        def kill(self):
            self.kill_calls += 1
            raise RuntimeError("tree kill failed")

    raw = RawProcess()
    wrapped = WrappedProcess(raw)
    group = runner_module._ProcessGroup(wrapped)

    with pytest.raises(RuntimeError, match="tree kill failed"):
        group.kill()

    assert wrapped.kill_calls == 1
    assert raw.kill_calls == 1
    assert group._process is raw


def test_qtgmc_cancellation_after_start_kills_producer_and_keeps_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "interlaced.avi"
    source.write_bytes(b"source")
    artifact = tmp_path / "restored.mkv"
    analysis = SourceInfo(path=source, duration=20.0, width=720, height=480)
    plan = _qtgmc_plan(source, analysis)
    runner = RestoreJobRunner()
    work_dir = tmp_path / "job"
    work_dir.mkdir()
    runner._work_dir = work_dir
    manifest = runner_module.JobManifest(source, artifact, RestoreSettings())
    producer = type("Producer", (), {"returncode": None, "stdout": None})()
    producer.kill_calls = 0

    def kill():
        producer.kill_calls += 1

    producer.kill = kill
    monkeypatch.setattr(runner, "_run_qtgmc_stage", lambda **kwargs: producer)
    check_calls = 0

    def check_cancel():
        nonlocal check_calls
        check_calls += 1
        if check_calls == 2:
            raise runner_module._JobCancelledSignal()

    monkeypatch.setattr(runner, "_check_cancel", check_cancel)

    with pytest.raises(runner_module._JobCancelledSignal):
        runner._run_ffmpeg_stage(
            stage="deinterlace",
            plan=plan,
            input_path=source,
            artifact=artifact,
            encode_args=(),
            manifest=manifest,
            manifest_file=work_dir / "manifest.json",
            duration=5.0,
        )

    assert producer.kill_calls == 1
    assert Path(f"{artifact}.partial").exists()
    assert runner.current_process is None
