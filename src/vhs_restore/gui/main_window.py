"""Main PySide6 window for VHS Restore Studio."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMimeData, QTimer, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from vhs_restore.analysis.source_info import SourceInfo
from vhs_restore.gui.controller import RestoreController
from vhs_restore.gui.diagnostics import DiagnosticsDialog, collect_dependency_report
from vhs_restore.gui.preview import build_preview_request
from vhs_restore.gui.settings import (
    DEINTERLACE_OPTIONS,
    OUTPUT_PROFILE_OPTIONS,
    PRESET_OPTIONS,
    AdvancedSettingsDialog,
    STRONG_AI_WARNING,
    add_options,
)
from vhs_restore.settings import RestoreSettings, load_preset, validate_settings
from vhs_restore.utils.deps import DependencyReport


class PathDropLineEdit(QLineEdit):
    """A line edit that accepts local files dragged from Explorer."""

    path_dropped = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setPlaceholderText("Choose a video file or drop it here")

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            if url.isLocalFile():
                path = url.toLocalFile()
                self.setText(path)
                self.path_dropped.emit(path)
                event.acceptProposedAction()
                return
        event.ignore()


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _playable_output_extension(profile: str | None) -> str:
    """Return a Windows-friendly default suffix for the encode profile."""

    if profile in {"compatibility", "archive_practical"}:
        return ".mp4"
    return ".mkv"


def _default_output_path(
    source: Path | None = None,
    profile: str | None = None,
) -> Path:
    extension = _playable_output_extension(profile)
    name = f"restored{extension}"
    if source is not None and source.stem:
        name = f"{source.stem}_restored{extension}"
    return _project_root() / "output" / name


def _same_path(left: Path, right: Path) -> bool:
    return left.resolve(strict=False) == right.resolve(strict=False)


def _format_seconds(value: float | None) -> str:
    if value is None:
        return "unknown"
    total = max(0, int(round(value)))
    minutes, seconds = divmod(total, 60)
    return f"{minutes:02d}:{seconds:02d}"


class MainWindow(QMainWindow):
    """The compact, local-only restore workflow window."""

    def __init__(
        self,
        *,
        controller: RestoreController | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("VHS Restore Studio")
        self.setAcceptDrops(False)

        self.controller = controller or RestoreController(parent=self)
        self._analysis: SourceInfo | None = None
        self._base_settings = load_preset("natural")
        self._dependency_report: DependencyReport | None = None
        self._using_default_output = True

        self._build_ui()
        self._size_to_available_screen()
        self._connect_signals()
        self._apply_preset("natural")
        self._set_running(False)

        # Dependency probing does not touch media and keeps the AI status
        # truthful as soon as the event loop becomes available.
        QTimer.singleShot(0, self._refresh_dependencies)

    def _build_ui(self) -> None:
        self.input_path_edit = PathDropLineEdit(self)
        self.browse_input_button = QPushButton("Browse…", self)
        self.analyze_button = QPushButton("Analyze", self)

        input_row = QHBoxLayout()
        input_row.addWidget(self.input_path_edit, 1)
        input_row.addWidget(self.browse_input_button)
        input_row.addWidget(self.analyze_button)
        input_group = QGroupBox("Input", self)
        input_group.setLayout(input_row)

        self.analysis_panel = QPlainTextEdit(self)
        self.analysis_panel.setReadOnly(True)
        self.analysis_panel.setPlaceholderText("Source analysis appears here.")
        self.analysis_panel.setMinimumHeight(64)
        analysis_group = QGroupBox("Source analysis", self)
        analysis_layout = QVBoxLayout(analysis_group)
        analysis_layout.addWidget(self.analysis_panel)

        self.preset_combo = QComboBox(self)
        add_options(self.preset_combo, PRESET_OPTIONS)
        self.preset_description_label = QLabel(self)
        self.preset_description_label.setWordWrap(True)

        self.deinterlace_combo = QComboBox(self)
        add_options(self.deinterlace_combo, DEINTERLACE_OPTIONS)
        self.denoise_slider, self.denoise_value_label = self._make_strength_slider()
        self.chroma_slider, self.chroma_value_label = self._make_strength_slider()
        self.ai_upscale_check = QCheckBox("Enable AI upscale", self)
        self.ai_status_label = QLabel("AI backend: checking…", self)
        self.ai_status_label.setWordWrap(True)
        self.output_profile_combo = QComboBox(self)
        add_options(self.output_profile_combo, OUTPUT_PROFILE_OPTIONS)
        self.advanced_button = QPushButton("Advanced…", self)

        controls_form = QFormLayout()
        controls_form.addRow("Preset", self.preset_combo)
        controls_form.addRow("Preset details", self.preset_description_label)
        controls_form.addRow("Deinterlace", self.deinterlace_combo)
        controls_form.addRow("Denoise strength", self.denoise_slider)
        controls_form.addRow("", self.denoise_value_label)
        controls_form.addRow("Chroma repair", self.chroma_slider)
        controls_form.addRow("", self.chroma_value_label)
        controls_form.addRow("", self.ai_upscale_check)
        controls_form.addRow("", self.ai_status_label)
        controls_form.addRow("Output profile", self.output_profile_combo)
        controls_form.addRow("", self.advanced_button)
        controls_group = QGroupBox("Restore settings", self)
        controls_group.setLayout(controls_form)

        self.preview_position_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.preview_position_slider.setRange(0, 100)
        self.preview_position_slider.setValue(50)
        self.preview_position_label = QLabel(self)
        self.preview_15_button = QPushButton("15%", self)
        self.preview_50_button = QPushButton("50%", self)
        self.preview_85_button = QPushButton("85%", self)
        self.preview_button = QPushButton("Preview 10 sec", self)
        preview_row = QHBoxLayout()
        preview_row.addWidget(self.preview_position_slider, 1)
        preview_row.addWidget(self.preview_position_label)
        preview_row.addWidget(self.preview_15_button)
        preview_row.addWidget(self.preview_50_button)
        preview_row.addWidget(self.preview_85_button)
        preview_row.addWidget(self.preview_button)
        preview_group = QGroupBox("Preview", self)
        preview_group.setLayout(preview_row)

        self.output_path_edit = QLineEdit(str(_default_output_path()), self)
        self.output_path_edit.setPlaceholderText("Output path (defaults under project output/)")
        self.browse_output_button = QPushButton("Output…", self)
        output_row = QHBoxLayout()
        output_row.addWidget(self.output_path_edit, 1)
        output_row.addWidget(self.browse_output_button)
        output_group = QGroupBox("Output", self)
        output_group.setLayout(output_row)

        self.start_button = QPushButton("Start Restore", self)
        self.cancel_button = QPushButton("Cancel", self)
        self.cancel_button.setEnabled(False)
        self.diagnostics_button = QPushButton("Diagnostics…", self)
        action_row = QHBoxLayout()
        action_row.addWidget(self.start_button)
        action_row.addWidget(self.cancel_button)
        action_row.addStretch(1)
        action_row.addWidget(self.diagnostics_button)

        self.stage_label = QLabel("Idle", self)
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.log_area = QPlainTextEdit(self)
        self.log_area.setReadOnly(True)
        self.log_area.setMinimumHeight(80)

        progress_group = QGroupBox("Progress and log", self)
        progress_layout = QVBoxLayout(progress_group)
        progress_layout.addWidget(self.stage_label)
        progress_layout.addWidget(self.progress_bar)
        progress_layout.addWidget(self.log_area, 1)

        settings_widget = QWidget(self)
        settings_layout = QVBoxLayout(settings_widget)
        settings_layout.addWidget(input_group)
        settings_layout.addWidget(analysis_group)
        settings_layout.addWidget(controls_group)
        settings_layout.addWidget(preview_group)
        settings_layout.addWidget(output_group)
        settings_layout.addLayout(action_row)
        settings_layout.addStretch(1)

        settings_scroll = QScrollArea(self)
        settings_scroll.setObjectName("settings_scroll")
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setWidget(settings_widget)

        splitter = QSplitter(Qt.Orientation.Vertical, self)
        splitter.setObjectName("main_splitter")
        splitter.addWidget(settings_scroll)
        splitter.addWidget(progress_group)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        root = QWidget(self)
        root_layout = QVBoxLayout(root)
        root_layout.addWidget(splitter, 1)
        self.setCentralWidget(root)

    def _size_to_available_screen(self) -> None:
        screen = self.screen()
        if screen is None:
            self.resize(960, 640)
            return

        available = screen.availableGeometry()
        margin = 24
        width = min(880, max(720, available.width() - 2 * margin))
        height = min(620, max(520, available.height() - 2 * margin))
        width = min(width, max(1, available.width() - 2 * margin))
        height = min(height, max(1, available.height() - 2 * margin))
        self.setGeometry(
            available.x() + margin,
            available.y() + margin,
            width,
            height,
        )

    @staticmethod
    def _make_strength_slider() -> tuple[QSlider, QLabel]:
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        label = QLabel("0.00")
        return slider, label

    def _connect_signals(self) -> None:
        self.browse_input_button.clicked.connect(self._browse_input)
        self.analyze_button.clicked.connect(self._analyze_from_field)
        self.input_path_edit.path_dropped.connect(self._set_source_path)
        self.preset_combo.currentIndexChanged.connect(self._preset_index_changed)
        self.denoise_slider.valueChanged.connect(
            lambda value: self.denoise_value_label.setText(f"{value / 100:.2f}")
        )
        self.chroma_slider.valueChanged.connect(
            lambda value: self.chroma_value_label.setText(f"{value / 100:.2f}")
        )
        self.preview_position_slider.valueChanged.connect(self._preview_position_changed)
        self.preview_15_button.clicked.connect(lambda: self.preview_position_slider.setValue(15))
        self.preview_50_button.clicked.connect(lambda: self.preview_position_slider.setValue(50))
        self.preview_85_button.clicked.connect(lambda: self.preview_position_slider.setValue(85))
        self.preview_button.clicked.connect(lambda: self._start_job(preview=True))
        self.start_button.clicked.connect(lambda: self._start_job(preview=False))
        self.cancel_button.clicked.connect(self._cancel_job)
        self.advanced_button.clicked.connect(self._open_advanced_settings)
        self.browse_output_button.clicked.connect(self._browse_output)
        self.output_path_edit.textEdited.connect(self._output_path_edited)
        self.output_profile_combo.currentIndexChanged.connect(self._refresh_default_output_path)
        self.diagnostics_button.clicked.connect(self._show_diagnostics)

        self.controller.analysis_started.connect(self._analysis_started)
        self.controller.analysis_finished.connect(self._analysis_finished)
        self.controller.analysis_failed.connect(self._analysis_failed)
        self.controller.progress.connect(self._progress_received)
        self.controller.job_started.connect(self._job_started)
        self.controller.job_finished.connect(self._job_finished)
        self.controller.job_failed.connect(self._job_failed)

    def _apply_preset(self, key: str) -> None:
        try:
            settings = load_preset(key)
        except (RuntimeError, ValueError) as exc:
            self._append_log(f"Preset error: {exc}")
            return

        self._base_settings = settings
        index = self.preset_combo.findData(key)
        if index >= 0 and self.preset_combo.currentIndex() != index:
            self.preset_combo.blockSignals(True)
            self.preset_combo.setCurrentIndex(index)
            self.preset_combo.blockSignals(False)
        description = settings.description
        if key == "strong_ai":
            description = f"{description}\n警告: {STRONG_AI_WARNING}"
        self.preset_description_label.setText(description)
        self._set_combo_value(self.deinterlace_combo, settings.deinterlace)
        self.denoise_slider.setValue(round(settings.denoise_strength * 100))
        self.chroma_slider.setValue(round(settings.chroma_repair_strength * 100))
        self.ai_upscale_check.setChecked(settings.ai_upscale)
        self._set_combo_value(self.output_profile_combo, settings.output_profile)
        self._update_ai_enablement()
        self._preview_position_changed(self.preview_position_slider.value())
        self._refresh_default_output_path()

    def _preset_index_changed(self, index: int) -> None:
        key = self.preset_combo.itemData(index)
        if key:
            self._apply_preset(str(key))

    def _set_combo_value(self, combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _settings_from_controls(self) -> RestoreSettings:
        values = self._base_settings.to_dict()
        values.update(
            deinterlace=str(self.deinterlace_combo.currentData()),
            denoise_strength=self.denoise_slider.value() / 100.0,
            chroma_repair_strength=self.chroma_slider.value() / 100.0,
            ai_upscale=self.ai_upscale_check.isChecked(),
            output_profile=str(self.output_profile_combo.currentData()),
        )
        return RestoreSettings.from_mapping(values)

    def _browse_input(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose source video",
            str(Path.home()),
            "Video files (*.avi *.mkv *.mp4 *.mov *.ts);;All files (*.*)",
        )
        if path:
            self._set_source_path(path)

    def _set_source_path(self, value: str) -> None:
        path = Path(value).expanduser()
        self.input_path_edit.setText(str(path))
        self._analysis = None
        self.analysis_panel.setPlainText("Analyzing source…")
        if self._using_default_output:
            self.output_path_edit.setText(
                str(_default_output_path(path, self._settings_from_controls().output_profile))
            )
        self._analyze_path(path)

    def _analyze_from_field(self) -> None:
        value = self.input_path_edit.text().strip()
        if value:
            self._analyze_path(Path(value).expanduser())

    def _analyze_path(self, path: Path) -> None:
        if not path.is_file():
            self.analysis_panel.setPlainText(f"Source file not found: {path}")
            self._append_log(f"Source file not found: {path}")
            return
        try:
            self.controller.start_analysis(path)
        except RuntimeError as exc:
            self._append_log(str(exc))

    def _analysis_started(self) -> None:
        self.stage_label.setText("Analyzing source…")
        self.analyze_button.setEnabled(False)

    def _analysis_finished(self, info: SourceInfo) -> None:
        self._analysis = info
        self.analyze_button.setEnabled(True)
        self.analysis_panel.setPlainText(self._format_analysis(info))
        warnings = validate_settings(self._settings_from_controls(), info)
        for warning in warnings:
            self._append_log(f"Warning: {warning.message}")
        self.stage_label.setText("Analysis complete")

    def _analysis_failed(self, message: str) -> None:
        self.analyze_button.setEnabled(True)
        self.analysis_panel.setPlainText(f"Analysis failed: {message}")
        self._append_log(f"Analysis failed: {message}")
        self.stage_label.setText("Analysis failed")

    @staticmethod
    def _format_analysis(info: SourceInfo) -> str:
        resolution = (
            f"{info.width}×{info.height}"
            if info.width is not None and info.height is not None
            else "unknown"
        )
        fps = f"{info.frame_rate:.3f}" if info.frame_rate is not None else "unknown"
        interlace = "unknown"
        confidence = ""
        if info.interlace is not None:
            interlace = info.interlace.classification
            confidence = f" ({info.interlace.confidence:.0%})"
        lines = [
            f"Path: {info.path}",
            f"Duration: {_format_seconds(info.duration)}    Resolution: {resolution}",
            f"Frame rate: {fps}    Field order: {info.field_order or 'unknown'}",
            f"Interlace: {interlace}{confidence}",
            f"Codec: {info.codec_name or 'unknown'}    Pixel format: {info.pixel_format or 'unknown'}",
            f"Audio streams: {info.audio_streams}",
        ]
        lines.extend(f"Warning: {warning}" for warning in info.warnings)
        return "\n".join(lines)

    def _preview_position_changed(self, value: int) -> None:
        if self._analysis is None:
            self.preview_position_label.setText(f"{value}%")
            return
        duration = self._analysis.duration or 0.0
        start = build_preview_request(
            self._analysis.path,
            self._analysis,
            self._settings_from_controls(),
            Path("preview.mkv"),
            value,
        ).start
        self.preview_position_label.setText(
            f"{value}% ({_format_seconds(start)} / {_format_seconds(duration)})"
        )

    def _refresh_default_output_path(self, *_args) -> None:
        if not self._using_default_output:
            return
        source_text = self.input_path_edit.text().strip()
        source = Path(source_text).expanduser() if source_text else None
        profile = str(self.output_profile_combo.currentData() or "")
        self.output_path_edit.setText(str(_default_output_path(source, profile)))

    def _resolve_output_path(self, source: Path) -> Path:
        value = self.output_path_edit.text().strip()
        profile = self._settings_from_controls().output_profile
        path = Path(value).expanduser() if value else _default_output_path(source, profile)
        if path.exists() and path.is_dir():
            path = path / f"{source.stem}_restored{_playable_output_extension(profile)}"
        if _playable_output_extension(profile) == ".mp4" and path.suffix.casefold() != ".mp4":
            path = path.with_suffix(".mp4")
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _start_job(self, *, preview: bool) -> None:
        if self._analysis is None:
            self._append_log("Analyze a source before starting a restore.")
            self._analyze_from_field()
            return

        source = Path(self.input_path_edit.text()).expanduser()
        output = self._resolve_output_path(source)
        if _same_path(source, output):
            self._append_log("Output must differ from the source media; source was not touched.")
            return

        settings = self._settings_from_controls()
        warnings = validate_settings(settings, self._analysis)
        for warning in warnings:
            self._append_log(f"Warning: {warning.message}")

        start = None
        duration = None
        if preview:
            preview_output = output.with_name(f"{output.stem}.preview{output.suffix or '.mkv'}")
            request = build_preview_request(
                source,
                self._analysis,
                settings,
                preview_output,
                self.preview_position_slider.value(),
            )
            output = request.output
            start = request.start
            duration = request.duration
            self._append_log(
                f"Preview: start={start:.2f}s duration={duration:.0f}s output={output}"
            )
        else:
            self._append_log(f"Restore output: {output}")

        try:
            self.controller.start_job(
                source,
                self._analysis,
                settings,
                output,
                start=start,
                duration=duration,
                preview=preview,
            )
        except (RuntimeError, ValueError, TypeError) as exc:
            self._append_log(f"Could not start job: {exc}")

    def _job_started(self, preview: bool) -> None:
        self._set_running(True)
        self.stage_label.setText("Preview started" if preview else "Restore started")
        self.progress_bar.setValue(0)

    def _progress_received(self, event: object) -> None:
        stage = getattr(event, "stage", "job")
        progress = float(getattr(event, "progress", 0.0))
        message = str(getattr(event, "message", ""))
        status = str(getattr(event, "status", "running"))
        self.progress_bar.setValue(round(max(0.0, min(1.0, progress)) * 100))
        self.stage_label.setText(f"{stage}: {status}")
        if message:
            self._append_log(f"[{stage}] {message}")

    def _job_finished(self, result: object) -> None:
        self._set_running(False)
        status = str(getattr(result, "status", "completed"))
        if status == "completed":
            self.progress_bar.setValue(100)
            self.stage_label.setText("Completed")
            self._append_log(f"Completed: {getattr(result, 'output_path', '')}")
        elif status == "cancelled":
            self.stage_label.setText("Cancelled")
            self._append_log(f"Cancelled; partial output: {getattr(result, 'partial_path', '')}")
        else:
            self.stage_label.setText(status)

    def _job_failed(self, message: str) -> None:
        self._set_running(False)
        self.stage_label.setText("Job failed")
        self._append_log(f"Job failed: {message}")

    def _cancel_job(self) -> None:
        self.controller.cancel()
        self._append_log("Cancellation requested.")

    def _set_running(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.preview_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        self.browse_input_button.setEnabled(not running)
        self.analyze_button.setEnabled(not running)

    def _open_advanced_settings(self) -> None:
        dialog = AdvancedSettingsDialog(self._settings_from_controls(), parent=self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        updated = dialog.get_settings()
        self._base_settings = updated
        self._set_combo_value(self.deinterlace_combo, updated.deinterlace)
        self._set_combo_value(self.output_profile_combo, updated.output_profile)
        self.ai_upscale_check.setChecked(updated.ai_upscale)
        self._append_log("Advanced settings updated.")

    def _browse_output(self) -> None:
        profile = self._settings_from_controls().output_profile
        default_path = str(
            self.output_path_edit.text().strip()
            or _default_output_path(profile=profile)
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Choose output file",
            default_path,
            "Video files (*.mkv *.mp4 *.mov);;All files (*.*)",
        )
        if path:
            self._using_default_output = False
            self.output_path_edit.setText(path)

    def _output_path_edited(self, _value: str) -> None:
        self._using_default_output = False

    def _refresh_dependencies(self) -> None:
        try:
            report = collect_dependency_report()
        except Exception as exc:
            self.ai_status_label.setText(f"Dependency detection failed: {exc}")
            self._append_log(f"Dependency detection failed: {exc}")
            return

        self._dependency_report = report
        if report.ai_backend_available:
            backend = report.selected_ai_backend or "Vulkan backend"
            self.ai_status_label.setText(f"AI backend available: {backend}")
        else:
            message = next(
                (item for item in report.messages if "AI backend unavailable" in item),
                "AI backend unavailable; classical scaling will be used.",
            )
            self.ai_status_label.setText(message)
            self.ai_upscale_check.setToolTip(message)
        self._update_ai_enablement()
        self._append_log("Dependency check complete.")

    def _update_ai_enablement(self) -> None:
        """Keep AI controls honest when no Vulkan-capable backend is present."""

        if self._dependency_report is None:
            self.ai_upscale_check.setEnabled(True)
            return
        available = self._dependency_report.ai_backend_available
        self.ai_upscale_check.setEnabled(available)
        if not available and self.ai_upscale_check.isChecked():
            self.ai_upscale_check.setChecked(False)

    def _show_diagnostics(self) -> None:
        self._refresh_dependencies()
        if self._dependency_report is not None:
            DiagnosticsDialog(self._dependency_report, parent=self).exec()

    def _append_log(self, message: str) -> None:
        if hasattr(self, "log_area"):
            self.log_area.appendPlainText(str(message))

    def closeEvent(self, event) -> None:
        self.controller.close()
        event.accept()


__all__ = ["MainWindow", "PathDropLineEdit"]
