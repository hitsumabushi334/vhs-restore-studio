import sys
import threading
import time
from pathlib import Path
from subprocess import CompletedProcess


from vhs_restore.analysis.source_info import SourceInfo
from vhs_restore.pipeline.deinterlace import DeinterlaceDecision
from vhs_restore.jobs import runner as runner_module
from vhs_restore.jobs.runner import JobError, RestoreJobRunner
from vhs_restore.pipeline.pipeline import PipelinePlan
from vhs_restore.settings import RestoreSettings
from vhs_restore.utils.process import (
    ProcessTreeTerminationError,
    start_command as real_start_command,
)


def _wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def test_cancel_kill_failure_is_reported_as_job_error(
    tmp_path: Path,
    monkeypatch,
):
    source = tmp_path / "source.avi"
    source.write_bytes(b"source")
    output = tmp_path / "output.mkv"
    settings = RestoreSettings()
    analysis = SourceInfo(path=source, duration=60.0, width=720, height=480)
    plan = PipelinePlan(
        source=source,
        filters=(),
        filter_graph="",
        deinterlace=DeinterlaceDecision(
            enabled=False,
            method="off",
            field_order=None,
            double_rate=False,
            input_frame_rate=None,
            output_frame_rate=None,
        ),
        restore_filters=(),
        color_filters=(),
        stages=(),
        settings=settings,
        analysis=analysis,
    )
    monkeypatch.setattr(runner_module, "build_pipeline", lambda *args, **kwargs: plan)
    monkeypatch.setattr(runner_module, "build_encode_args", lambda *args, **kwargs: [])

    class FailingKillProcess:
        returncode = None

        def __init__(self):
            self.wait_started = threading.Event()
            self.release_wait = threading.Event()

        def wait(self):
            self.wait_started.set()
            assert self.release_wait.wait(timeout=5)
            return CompletedProcess(args=["fake"], returncode=0)

        def kill(self):
            self.release_wait.set()
            raise ProcessTreeTerminationError("tree kill rejected")

    process = FailingKillProcess()
    runner = RestoreJobRunner(
        job_dir=tmp_path / "job",
        start_command_factory=lambda *args, **kwargs: process,
        free_space_checker=lambda _: 10**12,
    )
    error_holder: dict[str, BaseException] = {}

    def run_job() -> None:
        try:
            runner.run(
                source=source,
                analysis=analysis,
                settings=settings,
                output=output,
            )
        except BaseException as exc:
            error_holder["error"] = exc

    thread = threading.Thread(target=run_job)
    thread.start()
    assert _wait_until(process.wait_started.is_set)

    runner.cancel()
    thread.join(timeout=10)

    assert not thread.is_alive()
    error = error_holder.get("error")
    assert isinstance(error, JobError)
    assert isinstance(error.__cause__, ProcessTreeTerminationError)
    assert not isinstance(error, runner_module.JobCancelledError)
    assert output.with_name(f"{output.name}.partial").exists()


def test_cancel_kills_running_stage_and_leaves_partial_output(
    tmp_path: Path,
    monkeypatch,
):
    source = tmp_path / "日本語 capture (raw) [01].avi"
    source.write_bytes(b"source")
    output = tmp_path / "restored output.mkv"
    settings = RestoreSettings()
    analysis = SourceInfo(path=source, duration=60.0, width=720, height=480)
    plan = PipelinePlan(
        source=source,
        filters=(),
        filter_graph="",
        deinterlace=DeinterlaceDecision(
            enabled=False,
            method="off",
            field_order=None,
            double_rate=False,
            input_frame_rate=None,
            output_frame_rate=None,
        ),
        restore_filters=(),
        color_filters=(),
        stages=(),
        settings=settings,
        analysis=analysis,
    )
    monkeypatch.setattr(runner_module, "build_pipeline", lambda *args, **kwargs: plan)
    monkeypatch.setattr(runner_module, "build_encode_args", lambda *args, **kwargs: [])

    captured_argv: list[list[str]] = []

    def blocking_start(argv: list[str], **kwargs):
        captured_argv.append(list(argv))
        return real_start_command(
            [sys.executable, "-u", "-c", "import time; time.sleep(60)"],
            cwd=kwargs.get("cwd"),
            on_output=kwargs.get("on_output"),
        )

    monkeypatch.setattr(runner_module, "start_command", blocking_start)

    runner = RestoreJobRunner(
        job_dir=tmp_path / "job",
        free_space_checker=lambda _: 10**12,
    )
    result_holder: dict[str, object] = {}

    def run_job() -> None:
        result_holder["result"] = runner.run(
            source=source,
            analysis=analysis,
            settings=settings,
            output=output,
        )

    thread = threading.Thread(target=run_job)
    thread.start()
    assert _wait_until(lambda: runner.current_process is not None)

    runner.cancel()
    thread.join(timeout=10)

    assert not thread.is_alive()
    result = result_holder["result"]
    assert getattr(result, "status") == "cancelled"
    assert not output.exists()
    assert Path(f"{output}.partial").exists()
    assert captured_argv
    assert all(isinstance(item, str) for item in captured_argv[0])
    assert str(source) in captured_argv[0]
