"""Qt-threaded adapters for source analysis and restore jobs."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal, Slot

from vhs_restore.analysis.ffprobe import probe_source
from vhs_restore.analysis.interlace import analyze_interlace
from vhs_restore.analysis.source_info import SourceInfo
from vhs_restore.jobs.progress import ProgressEvent
from vhs_restore.jobs.runner import JobResult, RestoreJobRunner
from vhs_restore.settings import RestoreSettings


def _error_text(error: BaseException) -> str:
    """Return a compact, user-facing error string."""

    message = str(error).strip()
    return message or error.__class__.__name__


class AnalysisWorker(QObject):
    """Run FFprobe and multi-point idet analysis on a worker thread."""

    finished = Signal(object)
    failed = Signal(str)
    log = Signal(str)

    def __init__(
        self,
        source: str | Path,
        *,
        probe: Callable[[Path], SourceInfo] | None = None,
        interlace: Callable[..., Any] | None = None,
    ) -> None:
        super().__init__()
        self.source = Path(source)
        self._probe = probe or probe_source
        self._interlace = interlace or analyze_interlace

    @Slot()
    def run(self) -> None:
        """Analyze the source and emit one completed ``SourceInfo`` value."""

        try:
            self.log.emit(f"Analyzing source: {self.source}")
            info = self._probe(self.source)
            if info.duration is not None:
                idet = self._interlace(
                    info.path,
                    info.duration,
                    metadata_field_order=info.field_order,
                )
                info = info.with_interlace(idet)
            self.finished.emit(info)
        except Exception as exc:
            self.failed.emit(_error_text(exc))


class JobWorker(QObject):
    """Run one ``RestoreJobRunner`` call on a worker thread."""

    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(object)

    def __init__(
        self,
        runner: RestoreJobRunner | None,
        source: str | Path,
        analysis: SourceInfo,
        settings: RestoreSettings,
        output: str | Path,
        *,
        start: float | None = None,
        duration: float | None = None,
    ) -> None:
        super().__init__()
        self.runner = runner
        self.source = Path(source)
        self.analysis = analysis
        self.settings = settings
        self.output = Path(output)
        self.start = start
        self.duration = duration

    @Slot()
    def run(self) -> None:
        """Execute the configured job and translate exceptions to a signal."""

        if self.runner is None:
            self.failed.emit("RestoreJobRunner is not configured")
            return
        try:
            result = self.runner.run(
                self.source,
                self.analysis,
                self.settings,
                self.output,
                start=self.start,
                duration=self.duration,
            )
            self.finished.emit(result)
        except Exception as exc:
            self.failed.emit(_error_text(exc))

    def cancel(self) -> None:
        """Request cancellation of the active runner."""

        if self.runner is not None:
            self.runner.cancel()


class RestoreController(QObject):
    """Coordinate analysis and jobs while keeping GUI work on the UI thread."""

    analysis_started = Signal()
    analysis_finished = Signal(object)
    analysis_failed = Signal(str)

    job_started = Signal(bool)
    progress = Signal(object)
    job_finished = Signal(object)
    job_failed = Signal(str)

    def __init__(
        self,
        *,
        runner_factory: Callable[..., RestoreJobRunner] | None = None,
        probe: Callable[[Path], SourceInfo] | None = None,
        interlace: Callable[..., Any] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._runner_factory = runner_factory or RestoreJobRunner
        self._probe = probe
        self._interlace = interlace
        self._analysis_thread: QThread | None = None
        self._analysis_worker: AnalysisWorker | None = None
        self._job_thread: QThread | None = None
        self._job_worker: JobWorker | None = None
        self._active_runner: RestoreJobRunner | None = None

    @property
    def active_runner(self) -> RestoreJobRunner | None:
        """Return the active runner, if a job is running."""

        return self._active_runner

    @property
    def busy(self) -> bool:
        """Return whether analysis or a restore job currently occupies a thread."""

        analysis_running = bool(
            self._analysis_thread is not None and self._analysis_thread.isRunning()
        )
        job_running = bool(self._job_thread is not None and self._job_thread.isRunning())
        return analysis_running or job_running

    def start_analysis(self, source: str | Path) -> None:
        """Start source analysis on a fresh ``QThread``."""

        if self.busy:
            raise RuntimeError("another analysis or restore job is already running")

        worker = AnalysisWorker(
            source,
            probe=self._probe,
            interlace=self._interlace,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self.analysis_finished)
        worker.failed.connect(self.analysis_failed)
        worker.log.connect(self._forward_log)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda: self._clear_analysis(thread))

        self._analysis_worker = worker
        self._analysis_thread = thread
        self.analysis_started.emit()
        thread.start()

    def start_job(
        self,
        source: str | Path,
        analysis: SourceInfo,
        settings: RestoreSettings,
        output: str | Path,
        *,
        start: float | None = None,
        duration: float | None = None,
        runner: RestoreJobRunner | None = None,
        preview: bool = False,
    ) -> None:
        """Start a full restore or preview job on a fresh ``QThread``."""

        if self.busy:
            raise RuntimeError("another analysis or restore job is already running")

        worker = JobWorker(
            runner,
            source,
            analysis,
            settings,
            output,
            start=start,
            duration=duration,
        )
        if runner is None:
            worker.runner = self._runner_factory(progress_callback=worker.progress.emit)
        else:
            callback = getattr(runner, "progress_callback", None)
            if callback is None and hasattr(runner, "progress_callback"):
                runner.progress_callback = worker.progress.emit

        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.progress)
        worker.finished.connect(self.job_finished)
        worker.failed.connect(self.job_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda: self._clear_job(thread))

        self._job_worker = worker
        self._job_thread = thread
        self._active_runner = worker.runner
        self.job_started.emit(bool(preview))
        thread.start()

    def cancel(self) -> None:
        """Cancel the active restore job, including its current subprocess."""

        runner = self._active_runner
        if runner is not None:
            runner.cancel()

    def close(self) -> None:
        """Request cancellation before the owning window is destroyed."""

        self.cancel()

    def _forward_log(self, message: str) -> None:
        # Kept as a method so callers can connect a log signal without adding
        # another public signal just for analysis progress.
        self.progress.emit(
            ProgressEvent(stage="analysis", progress=0.0, message=message)
        )

    def _clear_analysis(self, thread: QThread) -> None:
        if self._analysis_thread is thread:
            self._analysis_thread = None
            self._analysis_worker = None

    def _clear_job(self, thread: QThread) -> None:
        if self._job_thread is thread:
            self._job_thread = None
            self._job_worker = None
            self._active_runner = None


Controller = RestoreController

__all__ = [
    "AnalysisWorker",
    "Controller",
    "JobWorker",
    "RestoreController",
]
