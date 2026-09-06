import importlib.util
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_main_window_constructs_offscreen():
    """The GUI shell is constructible without media or a display server."""

    try:
        module_spec = importlib.util.find_spec("vhs_restore.gui.main_window")
    except ModuleNotFoundError:
        module_spec = None
    assert module_spec is not None

    from PySide6.QtWidgets import QApplication

    from vhs_restore.gui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    assert window.windowTitle()
    assert window.input_path_edit is not None
    assert window.preset_combo.count() == 5
    assert window.preview_button is not None
    assert window.start_button is not None
    assert window.cancel_button is not None
    assert window.progress_bar is not None
    assert window.log_area is not None

    window.close()
    app.processEvents()


def test_preview_request_uses_slider_position_and_fixed_duration():
    from vhs_restore.analysis.source_info import SourceInfo
    from vhs_restore.gui.preview import build_preview_request
    from vhs_restore.settings import load_preset

    settings = load_preset("natural")
    analysis = SourceInfo(path=Path("日本語 source.mkv"), duration=100.0)
    request = build_preview_request(
        analysis.path,
        analysis,
        settings,
        Path("preview.mkv"),
        85,
    )

    assert request.start == 85.0
    assert request.duration == 10.0
    assert request.settings is settings


def test_job_worker_passes_preview_window_to_runner():
    from vhs_restore.analysis.source_info import SourceInfo
    from vhs_restore.gui.controller import JobWorker
    from vhs_restore.jobs.runner import JobResult
    from vhs_restore.settings import load_preset

    class FakeRunner:
        def __init__(self):
            self.calls = []

        def run(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return JobResult(
                status="completed",
                output_path=Path("preview.mkv"),
                manifest_path=Path("manifest.json"),
                job_id="smoke",
            )

        def cancel(self):
            return None

    runner = FakeRunner()
    worker = JobWorker(
        runner,
        Path("日本語 source.mkv"),
        SourceInfo(path=Path("日本語 source.mkv"), duration=30.0),
        load_preset("natural"),
        Path("preview.mkv"),
        start=25.5,
        duration=10.0,
    )
    results = []
    worker.finished.connect(results.append)
    worker.run()

    assert results and results[0].completed
    assert runner.calls[0][1]["start"] == 25.5
    assert runner.calls[0][1]["duration"] == 10.0


def test_controller_runs_job_on_qthread_and_forwards_progress():
    from PySide6.QtCore import QThread
    from PySide6.QtWidgets import QApplication

    from vhs_restore.analysis.source_info import SourceInfo
    from vhs_restore.gui.controller import RestoreController
    from vhs_restore.jobs.progress import ProgressEvent
    from vhs_restore.jobs.runner import JobResult
    from vhs_restore.settings import load_preset

    class FakeRunner:
        def __init__(self, progress_callback=None):
            self.progress_callback = progress_callback

        def run(self, *args, **kwargs):
            if self.progress_callback is not None:
                self.progress_callback(ProgressEvent(stage="restore", progress=0.5))
            return JobResult(
                status="completed",
                output_path=Path("output.mkv"),
                manifest_path=Path("manifest.json"),
                job_id="threaded-smoke",
            )

        def cancel(self):
            return None

    app = QApplication.instance() or QApplication([])
    controller = RestoreController(runner_factory=FakeRunner)
    results = []
    progress = []
    controller.job_finished.connect(results.append)
    controller.progress.connect(progress.append)

    controller.start_job(
        Path("source.mkv"),
        SourceInfo(path=Path("source.mkv"), duration=30.0),
        load_preset("natural"),
        Path("output.mkv"),
    )

    for _ in range(200):
        app.processEvents()
        if results:
            break
        QThread.msleep(5)

    assert results and results[0].completed
    assert progress and progress[0].stage == "restore"


def test_strong_ai_advanced_dialog_shows_japanese_warning():
    from PySide6.QtWidgets import QApplication

    from vhs_restore.gui.settings import AdvancedSettingsDialog, STRONG_AI_WARNING
    from vhs_restore.settings import load_preset

    app = QApplication.instance() or QApplication([])
    dialog = AdvancedSettingsDialog(load_preset("strong_ai"))

    assert STRONG_AI_WARNING in dialog.warning_label.text()
    assert dialog.get_settings().ai_backend == "realesrgan-ncnn-vulkan"

    dialog.close()
    app.processEvents()


def test_gui_diagnostics_show_realesrgan_image_cli_reason_not_vulkan_failure():
    from pathlib import Path

    from vhs_restore.gui.diagnostics import format_dependency_report
    from vhs_restore.utils.deps import DependencyReport, ToolStatus

    realesrgan = ToolStatus(
        name="realesrgan-ncnn-vulkan",
        executable="realesrgan-ncnn-vulkan",
        required=False,
        path=Path("C:/tools/realesrgan-ncnn-vulkan.exe"),
        available=True,
        version="0.2.0",
        capability_available=False,
        capability_error="image CLI only; not used for video upscale",
    )
    report = DependencyReport(
        tools={"realesrgan-ncnn-vulkan": realesrgan},
        tool_versions={"realesrgan-ncnn-vulkan": "0.2.0"},
        expected_versions={},
        required_missing=(),
        optional_missing=(),
        messages=("AI backend unavailable; classical scaling will be used.",),
        selected_ai_backend=None,
    )
    text = format_dependency_report(report)
    assert "image CLI only; not used for video upscale" in text
    assert "Vulkan probe failed" not in text
    assert "AI backend unavailable" in text
