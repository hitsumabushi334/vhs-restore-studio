"""Cancelable, resumable restore-job orchestration."""

from __future__ import annotations

import hashlib
import logging
import math
import os
import re
import subprocess
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vhs_restore.analysis.source_info import SourceInfo
from vhs_restore.pipeline.encode import build_encode_args
from vhs_restore.pipeline.pipeline import PipelinePlan, build_pipeline
from vhs_restore.settings import RestoreSettings
from vhs_restore.upscale.base import UpscaleBackend, select_upscale_backend
from vhs_restore.utils.logging import setup_job_logger
from vhs_restore.utils.paths import safe_output_path
from vhs_restore.utils.process import ManagedProcess, start_command
from vhs_restore.utils.system import find_tool, free_disk_space

from .cache import JobCache
from .manifest import (
    JobManifest,
    load_manifest,
    save_manifest,
    settings_hash,
    source_hash,
)
from .progress import CancellationToken, ProgressEvent, ProgressReporter


class JobError(RuntimeError):
    """Base class for restore job failures."""


class JobCancelledError(JobError):
    """Raised by run_or_raise after cancellation."""


class InsufficientDiskSpaceError(JobError):
    """Raised before a job starts when its output filesystem is too full."""

    def __init__(self, available: int, required: int, path: Path) -> None:
        self.available = int(available)
        self.required = int(required)
        self.path = Path(path)
        super().__init__(
            f"insufficient free space for restore job at {self.path}: "
            f"{self.available} bytes available, {self.required} required"
        )


class JobAlreadyRunningError(JobError):
    """Raised when one runner instance is asked to execute two jobs at once."""


class _JobCancelledSignal(Exception):
    """Internal control flow used after a live process has been terminated."""


class _ProcessGroup:
    """Treat the QTGMC producer and FFmpeg consumer as one cancelable stage."""

    def __init__(self, *processes: Any) -> None:
        self._processes = tuple(process for process in processes if process is not None)
        self._process = (
            getattr(self._processes[0], "_process", None) if self._processes else None
        )

    @property
    def returncode(self) -> int | None:
        returncode: int | None = 0
        for process in self._processes:
            returncode = getattr(process, "returncode", None)
            if returncode is None:
                return None
        return returncode

    def kill(self) -> None:
        first_error: BaseException | None = None
        for process in self._processes:
            try:
                process.kill()
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
                raw_process = getattr(process, "_process", None)
                force_kill = getattr(raw_process, "kill", None)
                if callable(force_kill):
                    try:
                        force_kill()
                    except BaseException:
                        pass
        if first_error is not None:
            raise first_error

    def wait(self, timeout: float | None = None) -> Any:
        deadline = None if timeout is None else time.monotonic() + timeout
        result: Any = None
        for index, process in enumerate(self._processes):
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            current = process.wait() if remaining is None else process.wait(timeout=remaining)
            if index == 0:
                result = current
        return result


@dataclass(frozen=True, slots=True)
class JobResult:
    """Outcome returned by a completed or cancelled restore job."""

    status: str
    output_path: Path
    manifest_path: Path
    job_id: str
    events: tuple[ProgressEvent, ...] = ()
    resumed: bool = False
    partial_path: Path | None = None
    error: str | None = None

    @property
    def output(self) -> Path:
        return self.output_path

    @property
    def partial_output(self) -> Path | None:
        return self.partial_path

    @property
    def cancelled(self) -> bool:
        return self.status == "cancelled"

    @property
    def completed(self) -> bool:
        return self.status == "completed"

    def __fspath__(self) -> str:
        return os.fspath(self.output_path)


def _as_number(value: float | None) -> str | None:
    if value is None:
        return None
    return f"{float(value):g}"


def _vspipe_y4m_args(executable: str | Path) -> list[str]:
    """Return the VSPipe flag that writes Y4M to stdout.

    VapourSynth R74+ replaced ``--y4m`` with ``--container y4m``.
    """

    try:
        result = subprocess.run(
            [str(executable), "--help"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ["--y4m"]
    help_text = f"{result.stdout}\n{result.stderr}".casefold()
    if "--container" in help_text:
        return ["--container", "y4m"]
    return ["--y4m"]


def _wait_process_exit(process: object, timeout: float = 5.0) -> None:
    """Reap a killed producer so its stderr pipe can reach EOF."""

    wait = getattr(process, "wait", None)
    if not callable(wait):
        return

    def call_wait(limit: float) -> None:
        try:
            wait(timeout=limit)
        except TypeError:
            wait()

    try:
        call_wait(timeout)
        return
    except subprocess.TimeoutExpired:
        pass
    except Exception:
        return

    for target in (process, getattr(process, "_process", None)):
        if target is None:
            continue
        kill = getattr(target, "kill", None)
        if not callable(kill):
            continue
        try:
            kill()
        except Exception:
            pass
    try:
        call_wait(timeout)
    except Exception:
        return


def _qtgmc_stderr_text(process: object) -> str:
    """Return drained VSPipe stderr for QTGMC JobError messages."""

    thread = getattr(process, "_qtgmc_stderr_thread", None)
    if thread is not None:
        join = getattr(thread, "join", None)
        if callable(join):
            join(timeout=5)

    chunks: list[bytes] = list(getattr(process, "_qtgmc_stderr", []) or [])
    thread_alive = bool(getattr(thread, "is_alive", lambda: False)())
    # The drain thread owns the pipe. Never issue a second blocking read
    # while that thread is still running.
    if not chunks and not thread_alive:
        stream = getattr(process, "stderr", None)
        if stream is None:
            stream = getattr(getattr(process, "_process", None), "stderr", None)
        if stream is not None:
            try:
                leftover = stream.read()
            except BaseException:
                leftover = None
            if leftover:
                if isinstance(leftover, bytes):
                    chunks.append(leftover)
                else:
                    chunks.append(str(leftover).encode("utf-8", errors="replace"))
    return b"".join(chunks).decode("utf-8", errors="replace").strip()


def _vspipe_exit_is_broken_pipe(returncode: int | None, stderr_text: str) -> bool:
    """Return whether a vspipe failure is the expected closed-pipe exit."""

    if returncode in (None, 0):
        return False
    normalized = stderr_text.casefold()
    failure_markers = (
        "failed to retrieve frame",
        "script evaluation failed",
        "script error",
        "python exception",
        "error evaluating",
    )
    if any(marker in normalized for marker in failure_markers):
        return False
    unsigned = returncode & 0xFFFFFFFF
    if returncode in {141, 109} or unsigned == 0xC000014B:
        return True
    pipe_markers = (
        "broken pipe",
        "error writing to stdout",
        "writing to stdout",
        "fwrite() call failed",
    )
    if not any(marker in normalized for marker in pipe_markers):
        return False
    if "fwrite() call failed" in normalized:
        return re.search(r"errno\s*:\s*(32|109)\b", normalized) is not None
    return True


def _merge_pipeline_filter(args: list[str], filter_graph: str) -> list[str]:
    if not filter_graph:
        return args
    for index, value in enumerate(args[:-1]):
        if value in {"-vf", "-filter:v"}:
            current = args[index + 1]
            args[index + 1] = f"{filter_graph},{current}" if current else filter_graph
            return args
    args.extend(("-vf", filter_graph))
    return args


def build_ffmpeg_argv(
    plan: PipelinePlan,
    output: str | os.PathLike[str] | Path,
    *,
    input_path: str | os.PathLike[str] | Path | None = None,
    audio_source: str | os.PathLike[str] | Path | None = None,
    encode_args: Iterable[str] = (),
    ffmpeg_executable: str | os.PathLike[str] = "ffmpeg",
    include_pipeline_filters: bool = True,
    progress: bool = True,
) -> list[str]:
    """Build one shell-free FFmpeg argv list for a pipeline stage."""

    if not isinstance(plan, PipelinePlan):
        raise TypeError("plan must be a PipelinePlan instance")
    input_value = Path(input_path) if input_path is not None else plan.source
    output_value = Path(output)
    audio_value = Path(audio_source) if audio_source is not None else None
    args = [str(item) for item in encode_args]
    start = _as_number(plan.start)
    duration = _as_number(plan.duration)
    pipe_input = str(input_value) == "pipe:0"
    filter_graph = plan.filter_graph if include_pipeline_filters else ""
    if filter_graph:
        _merge_pipeline_filter(args, filter_graph)

    argv = [str(ffmpeg_executable), "-hide_banner", "-nostdin", "-y"]
    if progress:
        argv.extend(("-progress", "pipe:1", "-nostats"))
    if not pipe_input:
        if start is not None:
            argv.extend(("-ss", start))
        if duration is not None:
            argv.extend(("-t", duration))
    argv.extend(("-i", str(input_value)))
    if audio_value is not None:
        if start is not None:
            argv.extend(("-ss", start))
        if duration is not None:
            argv.extend(("-t", duration))
        argv.extend(("-i", str(audio_value)))
    argv.extend(args)
    if audio_value is not None:
        argv.extend(("-map", "0:v:0", "-map", "1:a?"))
    argv.append(str(output_value))
    return argv


def _intermediate_encode_args() -> list[str]:
    """Return a lossless, seekable container for job-owned intermediates."""

    return [
        "-f",
        "matroska",
        "-c:v",
        "ffv1",
        "-level",
        "3",
        "-coder",
        "1",
        "-context",
        "1",
        "-g",
        "1",
        "-slicecrc",
        "1",
        "-c:a",
        "flac",
    ]


def _partial_path(path: Path) -> Path:
    return Path(f"{path}.partial")


def _backend_partial_path(path: Path) -> Path:
    suffix = "".join(path.suffixes)
    stem = path.name[: -len(suffix)] if suffix else path.name
    return path.with_name(f"{stem}.partial{suffix}")


def estimate_required_space(
    source: str | os.PathLike[str] | Path,
    settings: RestoreSettings,
    analysis: SourceInfo | None = None,
) -> int:
    """Estimate bytes needed for output plus job-owned intermediate stages."""

    source_path = Path(source)
    source_size = source_path.stat().st_size
    bitrate_size = 0
    if analysis is not None and analysis.duration and analysis.bit_rate:
        bitrate_size = int(max(0.0, float(analysis.duration)) * int(analysis.bit_rate) / 8)
    base = max(source_size, bitrate_size, 1)
    profile = str(settings.output_profile).casefold()
    profile_multiplier = {
        "archive_hq": 4.0,
        "archive_practical": 2.0,
        "compatibility": 1.5,
        "dvd": 1.5,
    }.get(profile, 2.0)
    intermediate_multiplier = 1.0 if settings.ai_upscale and settings.ai_scale > 1 else 0.0
    upscale_multiplier = (
        float(max(1, settings.ai_scale))
        if settings.ai_upscale and settings.ai_scale > 1
        else 0.0
    )
    estimate = base * (profile_multiplier + intermediate_multiplier + upscale_multiplier)
    return max(64 * 1024 * 1024, int(estimate))


def _default_job_id(source: Path, output: Path, source_digest: str, settings_digest: str) -> str:
    payload = "\0".join(
        (
            str(source.resolve(strict=False)),
            str(output.resolve(strict=False)),
            source_digest,
            settings_digest,
        )
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:20]


def _same_path(left: Path, right: Path) -> bool:
    return left.resolve(strict=False) == right.resolve(strict=False)


class RestoreJobRunner:
    """Run shared restoration stages with manifest-backed resume and cancel."""

    def __init__(
        self,
        *,
        job_dir: str | os.PathLike[str] | Path | None = None,
        cache_dir: str | os.PathLike[str] | Path | None = None,
        ffmpeg_executable: str | os.PathLike[str] = "ffmpeg",
        upscale_backend: UpscaleBackend | None = None,
        start_command_factory: Callable[..., ManagedProcess] | None = None,
        free_space_checker: Callable[[Path], int] = free_disk_space,
        minimum_free_space: int = 0,
        min_free_space: int | None = None,
        progress_callback: Callable[[ProgressEvent], object] | None = None,
    ) -> None:
        self.job_dir = None if job_dir is None else Path(job_dir)
        self.cache_dir = None if cache_dir is None else Path(cache_dir)
        self.ffmpeg_executable = ffmpeg_executable
        self.upscale_backend = upscale_backend
        self._start_command = start_command_factory or start_command
        self._free_space_checker = free_space_checker
        self.minimum_free_space = int(
            minimum_free_space if min_free_space is None else min_free_space
        )
        self.progress_callback = progress_callback
        self._lock = threading.RLock()
        self._running = False
        self._cancel_event = threading.Event()
        self._cancel_finished = threading.Event()
        self._cancel_finished.set()
        self._external_cancel: threading.Event | CancellationToken | None = None
        self._current_process: ManagedProcess | Any | None = None
        self._current_stage: str | None = None
        self._cancel_error: BaseException | None = None
        self._reporter: ProgressReporter | None = None
        self._logger: logging.Logger | None = None
        self._work_dir: Path | None = None

    @property
    def current_process(self) -> ManagedProcess | Any | None:
        """Return the active process, if a cancelable stage is running."""

        with self._lock:
            return self._current_process

    @property
    def current_stage(self) -> str | None:
        with self._lock:
            return self._current_stage

    @property
    def cancelled(self) -> bool:
        return self._is_cancelled()

    def cancel(self) -> None:
        """Request cancellation and terminate the active process tree."""

        with self._lock:
            self._cancel_finished.clear()
            self._cancel_event.set()
            process = self._current_process
        try:
            if process is None:
                return
            returncode = getattr(process, "returncode", None)
            if returncode is None:
                process.kill()
        except BaseException as exc:
            self._cancel_error = exc
            # ManagedProcess has already attempted the OS-level tree kill.
            # If Windows rejects that operation (for example under a
            # restricted service token), terminate the owned Popen handle so
            # the runner cannot remain blocked forever in wait().  The
            # original tree-kill error remains available for diagnostics.
            raw_process = getattr(process, "_process", None)
            force_kill = getattr(raw_process, "kill", None)
            if callable(force_kill):
                try:
                    force_kill()
                except BaseException as fallback_error:
                    self._cancel_error = fallback_error
        finally:
            self._cancel_finished.set()

    def _is_cancelled(self) -> bool:
        if self._cancel_event.is_set():
            return True
        external = self._external_cancel
        if external is None:
            return False
        if isinstance(external, CancellationToken):
            return external.is_cancelled()
        return external.is_set()

    def _wait_for_cancel_completion(self) -> None:
        if not self._cancel_finished.wait(timeout=30.0):
            raise JobError("restore job cancellation did not finish")

    def _raise_if_cancel_failed(self) -> None:
        self._wait_for_cancel_completion()
        cancel_error = self._cancel_error
        if cancel_error is not None:
            raise JobError("restore job cancellation failed") from cancel_error

    def _check_cancel(self) -> None:
        if self._is_cancelled():
            self._wait_for_cancel_completion()
            self._raise_if_cancel_failed()
            raise _JobCancelledSignal()

    def _set_active(self, stage: str, process: Any) -> None:
        with self._lock:
            self._current_stage = stage
            self._current_process = process

    def _clear_active(self, process: Any) -> None:
        with self._lock:
            if self._current_process is process:
                self._current_process = None
                self._current_stage = None
    def _kill_for_cancel(self, process: Any) -> None:
        try:
            process.kill()
        except BaseException as exc:
            with self._lock:
                if self._cancel_error is None:
                    self._cancel_error = exc

    def _emit(
        self,
        stage: str,
        progress: float,
        message: str = "",
        *,
        status: str = "running",
    ) -> None:
        if self._reporter is not None:
            self._reporter.emit(stage, progress, message, status=status)

    def _load_or_create_manifest(
        self,
        source: Path,
        output: Path,
        settings: RestoreSettings,
        source_digest: str,
        settings_digest: str,
        job_id: str | None,
    ) -> tuple[JobManifest, Path, bool]:
        requested_output = Path(output)
        resolved_id = job_id or _default_job_id(
            source,
            requested_output,
            source_digest,
            settings_digest,
        )
        work_dir = self.job_dir or requested_output.parent / ".vhs-restore" / resolved_id
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        manifest_file = work_dir / "manifest.json"
        existing: JobManifest | None = None
        try:
            existing = load_manifest(manifest_file)
        except (FileNotFoundError, OSError, ValueError):
            existing = None

        if (
            existing is not None
            and existing.can_resume(source, settings)
            and existing.source_hash == source_digest
            and existing.settings_hash == settings_digest
        ):
            manifest = existing
            output_path = existing.output_path
            resumed = True
        else:
            output_path = safe_output_path(requested_output)
            if _same_path(output_path, source):
                raise ValueError("restore output must differ from source media")
            manifest = JobManifest(
                source_path=source,
                output_path=output_path,
                settings=settings,
                job_id=resolved_id,
                source_hash=source_digest,
                settings_hash=settings_digest,
            )
            resumed = False
        self._work_dir = work_dir
        return manifest, manifest_file, resumed

    def _preflight(
        self,
        source: Path,
        output: Path,
        settings: RestoreSettings,
        analysis: SourceInfo | None,
    ) -> int:
        required = estimate_required_space(source, settings, analysis)
        available = int(self._free_space_checker(output.parent))
        required_with_reserve = required + max(0, self.minimum_free_space)
        if available < required_with_reserve:
            raise InsufficientDiskSpaceError(available, required_with_reserve, output.parent)
        return required_with_reserve

    def _cache_artifact(
        self,
        cache: JobCache,
        manifest: JobManifest,
        stage: str,
    ) -> Path | None:
        cached = cache.lookup(
            stage,
            source_hash=manifest.source_hash,
            settings_hash=manifest.settings_hash,
        )
        if cached is not None:
            return cached
        record = manifest.stages.get(stage, {})
        if manifest.stage_is_valid(stage):
            value = record.get("artifact_path")
            if value:
                return Path(value)
        return None

    def _record_cache(
        self,
        cache: JobCache,
        manifest: JobManifest,
        manifest_file: Path,
        stage: str,
        artifact: Path,
    ) -> None:
        cache.store(
            stage,
            artifact,
            source_hash=manifest.source_hash,
            settings_hash=manifest.settings_hash,
        )
        manifest.mark_stage(stage, status="completed", artifact=artifact)
        save_manifest(manifest, manifest_file)

    @staticmethod
    def _parse_progress(line: str, duration: float | None) -> float | None:
        if not duration or duration <= 0:
            return None
        if "out_time_ms=" not in line:
            return None
        try:
            microseconds = int(line.split("out_time_ms=", 1)[1].split()[0])
        except (IndexError, TypeError, ValueError):
            return None
        return max(0.0, min(1.0, microseconds / 1_000_000.0 / duration))

    def _run_qtgmc_stage(self, *, stage: str, plan: PipelinePlan) -> Any:
        """Start the planned QTGMC graph and return its stdout producer."""

        script = plan.qtgmc_script
        work_dir = self._work_dir
        if not script or work_dir is None:
            raise JobError("QTGMC stage has no job work directory or script")

        qtgmc_dir = work_dir / "qtgmc"
        qtgmc_dir.mkdir(parents=True, exist_ok=True)
        script_path = (qtgmc_dir / f"{stage}.qtgmc.vpy").resolve(strict=False)
        if _same_path(script_path, plan.source):
            raise JobError("refusing to overwrite QTGMC source script")
        script_path.write_text(script, encoding="utf-8")

        resolved = find_tool("vspipe")
        executable = resolved if resolved is not None else "vspipe"
        start = _as_number(plan.start)
        duration = _as_number(plan.duration)
        output_frame_rate = plan.deinterlace.output_frame_rate
        if start is not None or duration is not None:
            try:
                resolved_frame_rate = float(output_frame_rate)
            except (TypeError, ValueError):
                resolved_frame_rate = 0.0
            if not math.isfinite(resolved_frame_rate) or resolved_frame_rate <= 0:
                raise JobError(
                    "cannot apply timed QTGMC range without known output frame rate"
                )
            output_frame_rate = resolved_frame_rate
        start_frame = 0
        vspipe_range: list[str] = []
        if start is not None:
            start_frame = round(float(start) * float(output_frame_rate))
        if duration is not None:
            end_frame = start_frame + max(
                1, round(float(duration) * float(output_frame_rate))
            ) - 1
            vspipe_range.extend(("--start", str(start_frame), "--end", str(end_frame)))
        elif start is not None:
            vspipe_range.extend(("--start", str(start_frame)))
        argv = [str(executable), *_vspipe_y4m_args(executable), *vspipe_range, str(script_path), "-"]
        if self._logger is not None:
            self._logger.info("stage=%s argv=%r", stage, argv)

        qtgmc_stderr: list[bytes] = []
        stderr_thread: threading.Thread | None = None
        try:
            process = self._start_command(
                argv,
                cwd=work_dir,
                on_output=None,
                text=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                capture_output=False,
            )
            stderr_stream = getattr(process, "stderr", None)
            if stderr_stream is None:
                raw_process = getattr(process, "_process", None)
                stderr_stream = getattr(raw_process, "stderr", None)
            if stderr_stream is not None:

                def drain_stderr() -> None:
                    try:
                        data = stderr_stream.read()
                    except BaseException as exc:
                        qtgmc_stderr.append(
                            f"{type(exc).__name__}: {exc}".encode(
                                "utf-8", errors="replace"
                            )
                        )
                        return
                    if not data:
                        return
                    if isinstance(data, bytes):
                        qtgmc_stderr.append(data)
                    else:
                        qtgmc_stderr.append(str(data).encode("utf-8", errors="replace"))

                stderr_thread = threading.Thread(
                    target=drain_stderr,
                    name=f"vhs-restore-{stage}-vspipe-stderr",
                    daemon=True,
                )
                stderr_thread.start()
            setattr(process, "_qtgmc_stderr", qtgmc_stderr)
            setattr(process, "_qtgmc_stderr_thread", stderr_thread)
        except BaseException as exc:
            if self._is_cancelled():
                self._wait_for_cancel_completion()
                self._raise_if_cancel_failed()
                raise _JobCancelledSignal() from exc
            raise JobError(f"{stage} QTGMC stage failed to start vspipe: {exc}") from exc

        self._set_active(stage, process)
        return process

    def _run_ffmpeg_stage(
        self,
        *,
        stage: str,
        plan: PipelinePlan,
        input_path: Path,
        artifact: Path,
        encode_args: Iterable[str],
        manifest: JobManifest,
        manifest_file: Path,
        duration: float | None,
    ) -> Path:
        self._check_cancel()
        artifact.parent.mkdir(parents=True, exist_ok=True)
        partial = _partial_path(artifact)
        if partial.exists():
            partial.unlink()
        qtgmc_process: Any | None = None
        ffmpeg_input: Path | str = input_path
        audio_source: Path | None = None
        if (
            plan.deinterlace.method.casefold() == "qtgmc"
            and plan.qtgmc_script
            and _same_path(input_path, plan.source)
        ):
            qtgmc_process = self._run_qtgmc_stage(stage=stage, plan=plan)
            try:
                self._check_cancel()
            except BaseException as exc:
                self._kill_for_cancel(qtgmc_process)
                self._clear_active(qtgmc_process)
                self._ensure_partial(partial)
                self._raise_if_cancel_failed()
                raise _JobCancelledSignal() from exc
            ffmpeg_input = "pipe:0"
            audio_source = plan.source
        argv = build_ffmpeg_argv(
            plan,
            partial,
            input_path=ffmpeg_input,
            audio_source=audio_source,
            encode_args=encode_args,
            ffmpeg_executable=self.ffmpeg_executable,
        )
        if self._logger is not None:
            self._logger.info("stage=%s argv=%r", stage, argv)

        def on_output(line: str) -> None:
            if self._logger is not None:
                self._logger.info("stage=%s %s", stage, line)
            progress = self._parse_progress(line, duration)
            if progress is not None:
                self._emit(stage, progress, line)

        self._emit(stage, 0.0, f"{stage} started")
        ffmpeg_stdin = getattr(qtgmc_process, "stdout", None)
        try:
            if ffmpeg_stdin is None:
                process = self._start_command(
                    argv,
                    cwd=self._work_dir,
                    on_output=on_output,
                )
            else:
                process = self._start_command(
                    argv,
                    cwd=self._work_dir,
                    on_output=on_output,
                    stdin=ffmpeg_stdin,
                    text=False,
                )
        except BaseException as exc:
            if qtgmc_process is not None:
                self._kill_for_cancel(qtgmc_process)
                self._clear_active(qtgmc_process)
            if self._is_cancelled():
                self._ensure_partial(partial)
                self._raise_if_cancel_failed()
                raise _JobCancelledSignal() from exc
            raise
        if ffmpeg_stdin is not None:
            close_stdin = getattr(ffmpeg_stdin, "close", None)
            if callable(close_stdin):
                close_stdin()
        process_group = _ProcessGroup(process, qtgmc_process)
        with self._lock:
            self._current_stage = stage
            self._current_process = process_group
            cancelled_after_spawn = self._is_cancelled()
        if cancelled_after_spawn:
            self._kill_for_cancel(process_group)
            self._ensure_partial(partial)
            self._raise_if_cancel_failed()
            raise _JobCancelledSignal()
        try:
            result = process_group.wait()
        except BaseException as exc:
            if self._is_cancelled():
                self._ensure_partial(partial)
                self._raise_if_cancel_failed()
                raise _JobCancelledSignal() from exc
            if qtgmc_process is not None:
                try:
                    qtgmc_process.kill()
                except BaseException:
                    pass
                _wait_process_exit(qtgmc_process)
            if self._is_cancelled():
                self._ensure_partial(partial)
                self._raise_if_cancel_failed()
                raise _JobCancelledSignal() from exc
            vspipe_detail = (
                _qtgmc_stderr_text(qtgmc_process) if qtgmc_process is not None else ""
            )
            if self._is_cancelled():
                self._ensure_partial(partial)
                self._raise_if_cancel_failed()
                raise _JobCancelledSignal() from exc
            if not isinstance(exc, Exception):
                raise
            suffix = f": {vspipe_detail}" if vspipe_detail else ""
            raise JobError(f"{stage} FFmpeg stage failed{suffix}: {exc}") from exc
        finally:
            self._clear_active(process_group)

        if self._is_cancelled():
            self._ensure_partial(partial)
            self._raise_if_cancel_failed()
            raise _JobCancelledSignal()
        vspipe_detail = (
            _qtgmc_stderr_text(qtgmc_process) if qtgmc_process is not None else ""
        )
        returncode = getattr(result, "returncode", 0)
        if returncode != 0:
            self._ensure_partial(partial)
            details: list[str] = []
            ffmpeg_detail = str(getattr(result, "stdout", "") or "").strip()
            if ffmpeg_detail:
                details.append(ffmpeg_detail)
            if vspipe_detail:
                details.append(vspipe_detail)
            suffix = f": {' | '.join(details)}" if details else ""
            raise JobError(f"{stage} FFmpeg stage failed with exit code {returncode}{suffix}")
        qtgmc_returncode = (
            getattr(qtgmc_process, "returncode", 0) if qtgmc_process is not None else 0
        )
        if qtgmc_returncode not in {0, None} and not _vspipe_exit_is_broken_pipe(
            qtgmc_returncode, vspipe_detail
        ):
            self._ensure_partial(partial)
            suffix = f": {vspipe_detail}" if vspipe_detail else ""
            raise JobError(
                f"{stage} QTGMC stage failed with vspipe exit code "
                f"{qtgmc_returncode}{suffix}"
            )
        if not partial.exists():
            raise JobError(f"{stage} completed without creating {partial}")
        self._promote(partial, artifact)
        manifest.mark_stage(stage, status="completed", artifact=artifact)
        save_manifest(manifest, manifest_file)
        self._emit(stage, 1.0, f"{stage} complete", status="completed")
        return artifact

    def _run_upscale_stage(
        self,
        *,
        backend: UpscaleBackend,
        input_path: Path,
        artifact: Path,
        settings: RestoreSettings,
        stage: str,
        manifest: JobManifest,
        manifest_file: Path,
    ) -> Path:
        self._check_cancel()
        artifact.parent.mkdir(parents=True, exist_ok=True)
        backend_output = _backend_partial_path(artifact)
        if backend_output.exists():
            backend_output.unlink()
        self._emit(stage, 0.0, f"{stage} started")
        starter = getattr(backend, "start", None)
        result_path: Path | None = None

        if callable(starter):
            process = starter(
                input_path,
                backend_output,
                settings.ai_scale,
                settings.ai_model,
            )
            self._set_active(stage, process)
            try:
                result = process.wait()
            except BaseException as exc:
                if self._is_cancelled():
                    self._ensure_partial(backend_output)
                    self._raise_if_cancel_failed()
                    raise _JobCancelledSignal() from exc
                raise
            finally:
                self._clear_active(process)
            if self._is_cancelled():
                self._ensure_partial(backend_output)
                self._raise_if_cancel_failed()
                raise _JobCancelledSignal()
            if isinstance(result, Path):
                result_path = result
            elif getattr(result, "returncode", 0) != 0:
                raise JobError(
                    f"{stage} upscale failed with exit code "
                    f"{getattr(result, 'returncode', 'unknown')}"
                )
        else:
            result = backend.upscale(
                input_path,
                backend_output,
                settings.ai_scale,
                settings.ai_model,
            )
            if result is not None:
                result_path = Path(result)
            if self._is_cancelled():
                self._ensure_partial(backend_output)
                self._raise_if_cancel_failed()
                raise _JobCancelledSignal()

        produced = result_path or backend_output
        if not produced.exists():
            raise JobError(f"{stage} completed without creating {produced}")
        if _same_path(produced, input_path):
            raise ValueError("upscale output must differ from input")
        self._promote(produced, artifact)
        manifest.mark_stage(
            stage,
            status="completed",
            artifact=artifact,
            backend=getattr(backend, "name", "unknown"),
        )
        save_manifest(manifest, manifest_file)
        self._emit(stage, 1.0, f"{stage} complete", status="completed")
        return artifact

    @staticmethod
    def _ensure_partial(path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.touch()
        return path

    @staticmethod
    def _promote(partial: Path, artifact: Path) -> None:
        if not partial.exists():
            raise FileNotFoundError(f"incomplete artifact does not exist: {partial}")
        if artifact.exists():
            raise FileExistsError(f"refusing to overwrite existing artifact: {artifact}")
        partial.rename(artifact)

    def _select_backend(self, settings: RestoreSettings, input_path: Path) -> UpscaleBackend:
        if self.upscale_backend is not None:
            return self.upscale_backend
        if settings.ai_backend == "classical":
            from vhs_restore.upscale.classical import ClassicalBackend

            candidate: UpscaleBackend = ClassicalBackend()
            if candidate.is_available():
                return candidate
        elif settings.ai_backend == "realesrgan-ncnn-vulkan":
            from vhs_restore.upscale.realesrgan import RealESRGANBackend

            candidate = RealESRGANBackend()
            if candidate.is_available() and getattr(
                candidate, "supports_input", lambda _: True
            )(input_path):
                return candidate
        elif settings.ai_backend == "video2x":
            from vhs_restore.upscale.video2x import Video2XBackend

            candidate = Video2XBackend()
            if candidate.is_available():
                return candidate
        return select_upscale_backend(input=input_path)

    def run(
        self,
        source: str | os.PathLike[str] | Path,
        analysis: SourceInfo | None = None,
        settings: RestoreSettings | None = None,
        output: str | os.PathLike[str] | Path | None = None,
        *,
        start: float | None = None,
        duration: float | None = None,
        job_id: str | None = None,
        cancel_event: threading.Event | CancellationToken | None = None,
    ) -> JobResult:
        """Run a restore job, returning a status object instead of raising on cancel."""

        source_path = Path(source)
        if settings is None:
            settings = RestoreSettings()
        if output is None:
            raise TypeError("output is required")
        output_path = Path(output)
        if not source_path.is_file():
            raise FileNotFoundError(f"source media does not exist: {source_path}")
        if not isinstance(settings, RestoreSettings):
            raise TypeError("settings must be a RestoreSettings instance")
        if analysis is None:
            from vhs_restore.analysis.ffprobe import probe_source

            analysis = probe_source(source_path)

        with self._lock:
            if self._running:
                raise JobAlreadyRunningError("this restore job runner is already running")
            self._running = True
            self._cancel_event.clear()
            self._cancel_finished.set()
            self._external_cancel = cancel_event
            self._cancel_error = None

        manifest: JobManifest | None = None
        manifest_file: Path | None = None
        reporter: ProgressReporter | None = None
        try:
            source_digest = source_hash(source_path)
            settings_digest = settings_hash(settings)
            manifest, manifest_file, resumed = self._load_or_create_manifest(
                source_path,
                output_path,
                settings,
                source_digest,
                settings_digest,
                job_id,
            )
            reporter = ProgressReporter(self.progress_callback, job_id=manifest.job_id)
            self._reporter = reporter
            self._logger = setup_job_logger(self._work_dir or manifest_file.parent)
            manifest.status = "preflight"
            save_manifest(manifest, manifest_file)
            self._preflight(source_path, manifest.output_path, settings, analysis)
            self._check_cancel()

            output_path = manifest.output_path
            if _same_path(output_path, source_path):
                raise ValueError("restore output must differ from source media")
            cache_root = self.cache_dir or manifest_file.parent / "cache"
            cache = JobCache(cache_root)

            final_cached = self._cache_artifact(cache, manifest, "final")
            if final_cached is not None and _same_path(final_cached, output_path):
                manifest.status = "completed"
                save_manifest(manifest, manifest_file)
                self._emit("job", 1.0, "job resumed from cache", status="completed")
                return JobResult(
                    status="completed",
                    output_path=output_path,
                    manifest_path=manifest_file,
                    job_id=manifest.job_id,
                    events=tuple(reporter.events),
                    resumed=True,
                )

            manifest.status = "running"
            save_manifest(manifest, manifest_file)
            plan = build_pipeline(
                settings,
                analysis,
                start=start,
                duration=duration,
                output=output_path,
            )
            should_upscale = (
                settings.ai_upscale
                and settings.ai_scale > 1
                and settings.ai_backend != "none"
            )

            if not should_upscale:
                cached_restore = self._cache_artifact(cache, manifest, "restore")
                if cached_restore is not None and _same_path(cached_restore, output_path):
                    manifest.mark_stage("restore", status="completed", artifact=output_path)
                else:
                    encode_args = build_encode_args(
                        settings.output_profile,
                        analysis,
                        settings,
                    )
                    self._run_ffmpeg_stage(
                        stage="restore",
                        plan=plan,
                        input_path=source_path,
                        artifact=output_path,
                        encode_args=encode_args,
                        manifest=manifest,
                        manifest_file=manifest_file,
                        duration=duration or analysis.duration,
                    )
                self._record_cache(cache, manifest, manifest_file, "restore", output_path)
                self._record_cache(cache, manifest, manifest_file, "final", output_path)
            else:
                restore_artifact = cache_root / "restore.mkv"
                cached_restore = self._cache_artifact(cache, manifest, "restore")
                if cached_restore is None:
                    self._run_ffmpeg_stage(
                        stage="restore",
                        plan=plan,
                        input_path=source_path,
                        artifact=restore_artifact,
                        encode_args=_intermediate_encode_args(),
                        manifest=manifest,
                        manifest_file=manifest_file,
                        duration=duration or analysis.duration,
                    )
                    self._record_cache(cache, manifest, manifest_file, "restore", restore_artifact)
                else:
                    restore_artifact = cached_restore
                    self._emit("restore", 1.0, "restore stage resumed", status="completed")

                backend = self._select_backend(settings, restore_artifact)
                upscale_artifact = cache_root / "upscaled.mkv"
                cached_upscale = self._cache_artifact(cache, manifest, "upscale")
                if cached_upscale is None:
                    self._run_upscale_stage(
                        backend=backend,
                        input_path=restore_artifact,
                        artifact=upscale_artifact,
                        settings=settings,
                        stage="upscale",
                        manifest=manifest,
                        manifest_file=manifest_file,
                    )
                    self._record_cache(cache, manifest, manifest_file, "upscale", upscale_artifact)
                else:
                    upscale_artifact = cached_upscale
                    self._emit("upscale", 1.0, "upscale stage resumed", status="completed")

                cached_final = self._cache_artifact(cache, manifest, "final")
                if cached_final is None or not _same_path(cached_final, output_path):
                    encode_args = build_encode_args(
                        settings.output_profile,
                        analysis,
                        settings,
                    )
                    self._run_ffmpeg_stage(
                        stage="encode",
                        plan=plan,
                        input_path=upscale_artifact,
                        artifact=output_path,
                        encode_args=encode_args,
                        manifest=manifest,
                        manifest_file=manifest_file,
                        duration=duration or analysis.duration,
                    )
                    self._record_cache(cache, manifest, manifest_file, "final", output_path)
                else:
                    self._emit("encode", 1.0, "encode stage resumed", status="completed")

            manifest.status = "completed"
            save_manifest(manifest, manifest_file)
            self._emit("job", 1.0, "job complete", status="completed")
            return JobResult(
                status="completed",
                output_path=output_path,
                manifest_path=manifest_file,
                job_id=manifest.job_id,
                events=tuple(reporter.events),
                resumed=resumed,
            )
        except _JobCancelledSignal:
            if manifest is None or manifest_file is None or reporter is None:
                raise JobCancelledError("restore job cancelled before initialization")
            partial = self._ensure_partial(_partial_path(manifest.output_path))
            stage = self.current_stage or "job"
            manifest.mark_stage(stage, status="cancelled", error="cancellation requested")
            manifest.status = "cancelled"
            save_manifest(manifest, manifest_file)
            self._emit(stage, 0.0, "job cancelled", status="cancelled")
            self._emit("job", 0.0, "job cancelled", status="cancelled")
            return JobResult(
                status="cancelled",
                output_path=manifest.output_path,
                manifest_path=manifest_file,
                job_id=manifest.job_id,
                events=tuple(reporter.events),
                resumed=False,
                partial_path=partial,
            )
        except Exception as exc:
            if manifest is not None and manifest_file is not None:
                manifest.status = "failed"
                stage = self.current_stage
                if stage is not None:
                    manifest.mark_stage(stage, status="failed", error=str(exc))
                save_manifest(manifest, manifest_file)
            raise
        finally:
            with self._lock:
                self._running = False
                self._current_process = None
                self._current_stage = None
                self._external_cancel = None
            self._reporter = None
            self._logger = None

    def run_or_raise(self, *args: Any, **kwargs: Any) -> JobResult:
        """Run a job and convert a cancelled result into JobCancelledError."""

        result = self.run(*args, **kwargs)
        if result.cancelled:
            raise JobCancelledError("restore job cancelled")
        return result


def run_restore(
    source: str | os.PathLike[str] | Path,
    analysis: SourceInfo | None = None,
    settings: RestoreSettings | None = None,
    output: str | os.PathLike[str] | Path | None = None,
    *,
    runner: RestoreJobRunner | None = None,
    **kwargs: Any,
) -> JobResult:
    """Functional entry point for callers that do not need a runner object."""

    selected_runner = runner or RestoreJobRunner(
        job_dir=kwargs.pop("job_dir", None),
        cache_dir=kwargs.pop("cache_dir", None),
        ffmpeg_executable=kwargs.pop("ffmpeg_executable", "ffmpeg"),
        upscale_backend=kwargs.pop("upscale_backend", None),
        free_space_checker=kwargs.pop("free_space_checker", free_disk_space),
        minimum_free_space=kwargs.pop("minimum_free_space", 0),
        progress_callback=kwargs.pop("progress_callback", None),
    )
    return selected_runner.run(source, analysis, settings, output, **kwargs)


__all__ = [
    "InsufficientDiskSpaceError",
    "JobAlreadyRunningError",
    "JobCancelledError",
    "JobError",
    "JobResult",
    "RestoreJobRunner",
    "build_ffmpeg_argv",
    "estimate_required_space",
    "run_restore",
]
