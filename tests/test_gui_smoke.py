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

    from PySide6.QtWidgets import QApplication, QSplitter
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
    assert window.processing_plan is not None
    assert window.processing_plan.isReadOnly()
    assert window.target_resolution_combo.count() == 6
    assert window.ai_scale_combo.count() == 2
    splitters = window.findChildren(QSplitter)
    assert any(splitter.count() == 2 for splitter in splitters)

    window.close()
    app.processEvents()


def test_gui_settings_round_trip_target_resolution_and_ai_scale():
    from PySide6.QtWidgets import QApplication

    from vhs_restore.gui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    window._set_combo_value(window.target_resolution_combo, "1920x1080")
    window._set_combo_value(window.ai_scale_combo, 4)
    window.ai_upscale_check.setChecked(True)

    settings = window._settings_from_controls()

    assert settings.target_resolution == "1920x1080"
    assert settings.ai_scale == 4

    window.close()
    app.processEvents()

def test_compatibility_default_output_uses_mp4_suffix(tmp_path):
    from vhs_restore.gui.main_window import MainWindow, _default_output_path
    from PySide6.QtWidgets import QApplication

    assert _default_output_path(Path("capture.avi"), "compatibility").suffix == ".mp4"
    assert _default_output_path(Path("capture.avi"), "archive_practical").suffix == ".mp4"
    assert _default_output_path(Path("capture.avi"), "archive_hq").suffix == ".mp4"
    assert _default_output_path(Path("capture.avi"), None).suffix == ".mp4"
    assert _default_output_path(Path("capture.avi"), "dvd").suffix == ".mpg"

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.output_path_edit.setText(str(tmp_path / "restored.mkv"))
    window._set_combo_value(window.output_profile_combo, "compatibility")

    assert window._resolve_output_path(Path("capture.avi")).suffix == ".mp4"

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


def test_archive_practical_rewrites_mkv_output_to_mp4(tmp_path):
    from PySide6.QtWidgets import QApplication

    from vhs_restore.gui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window._using_default_output = False
    window.output_path_edit.setText(str(tmp_path / "custom restored.mkv"))
    window._set_combo_value(window.output_profile_combo, "archive_practical")

    assert window._resolve_output_path(Path("capture.avi")).suffix == ".mp4"

    window.close()
    app.processEvents()


def test_target_resolution_combo_includes_720x480():
    from PySide6.QtWidgets import QApplication

    from vhs_restore.gui.main_window import MainWindow
    from vhs_restore.gui.settings import TARGET_RESOLUTION_OPTIONS

    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    values = [window.target_resolution_combo.itemData(i) for i in range(window.target_resolution_combo.count())]
    assert "720x480" in values
    assert TARGET_RESOLUTION_OPTIONS == (
        ("Native", "native"),
        ("720x480", "720x480"),
        ("960x720", "960x720"),
        ("1280x960", "1280x960"),
        ("1440x1080", "1440x1080"),
        ("1920x1080 pillarbox", "1920x1080"),
    )

    window.close()
    app.processEvents()


def test_dvd_profile_selects_720x480_target_resolution():
    from PySide6.QtWidgets import QApplication

    from vhs_restore.gui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    window._set_combo_value(window.output_profile_combo, "archive_practical")
    window._sync_target_resolution_with_profile()
    assert window.target_resolution_combo.isEnabled()

    window._set_combo_value(window.output_profile_combo, "dvd")
    window._sync_target_resolution_with_profile()
    assert window.target_resolution_combo.currentData() == "720x480"
    assert not window.target_resolution_combo.isEnabled()
    settings = window._settings_from_controls()
    assert settings.target_resolution == "720x480"

    window.close()
    app.processEvents()
