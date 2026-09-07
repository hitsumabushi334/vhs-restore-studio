"""GUI controls for presets and advanced restore overrides."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
)

from vhs_restore.settings import RestoreSettings


PRESET_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Natural", "natural"),
    ("Balanced AI", "balanced_ai"),
    ("Strong AI", "strong_ai"),
    ("DVD", "dvd"),
    ("Archive", "archive"),
)


DEINTERLACE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Auto", "auto"),
    ("Off / progressive", "off"),
    ("TFF", "tff"),
    ("BFF", "bff"),
    ("Progressive", "progressive"),
)


QTGMC_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Fast", "fast"),
    ("Balanced", "balanced"),
    ("High", "high"),
    ("Very High", "very_high"),
)


AI_BACKEND_OPTIONS: tuple[tuple[str, str], ...] = (
    ("None", "none"),
    ("Classical scaler", "classical"),
    ("Real-ESRGAN ncnn Vulkan", "realesrgan-ncnn-vulkan"),
    ("Video2X Vulkan", "video2x"),
)


AI_SCALE_OPTIONS: tuple[tuple[str, int], ...] = (
    ("2x", 2),
    ("4x", 4),
)


TARGET_RESOLUTION_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Native", "native"),
    ("720x480", "720x480"),
    ("960x720", "960x720"),
    ("1280x960", "1280x960"),
    ("1440x1080", "1440x1080"),
    ("1920x1080 pillarbox", "1920x1080"),
)


OUTPUT_PROFILE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Archive HQ", "archive_hq"),
    ("Archive Practical", "archive_practical"),
    ("Compatibility", "compatibility"),
    ("DVD", "dvd"),
)


STRONG_AI_WARNING = (
    "Strong AI は細部や日本語テキストを改変（幻覚）する可能性があります。"
    "プレビューで必ず確認してください。"
)




def add_options(combo: QComboBox, options: Iterable[tuple[str, object]]) -> None:
    """Populate a combo box with display labels and stable setting values."""

    for label, value in options:
        combo.addItem(label, value)


def _set_combo_value(combo: QComboBox, value: object) -> None:
    index = combo.findData(value)
    combo.setCurrentIndex(index if index >= 0 else 0)


def _is_strong_ai(settings: RestoreSettings) -> bool:
    return settings.name.casefold().replace(" ", "_") == "strong_ai"


class AdvancedSettingsDialog(QDialog):
    """Edit deinterlace, QTGMC, and AI backend overrides."""

    def __init__(
        self,
        settings: RestoreSettings,
        *,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle("Advanced restore settings")
        self.setModal(True)

        self.deinterlace_combo = QComboBox(self)
        add_options(self.deinterlace_combo, DEINTERLACE_OPTIONS)
        self.qtgmc_combo = QComboBox(self)
        add_options(self.qtgmc_combo, QTGMC_OPTIONS)
        self.ai_backend_combo = QComboBox(self)
        add_options(self.ai_backend_combo, AI_BACKEND_OPTIONS)

        _set_combo_value(self.deinterlace_combo, settings.deinterlace)
        _set_combo_value(self.qtgmc_combo, settings.qtgmc_preset)
        _set_combo_value(self.ai_backend_combo, settings.ai_backend)

        self.warning_label = QLabel(self)
        self.warning_label.setWordWrap(True)
        self.warning_label.setText(STRONG_AI_WARNING if _is_strong_ai(settings) else "")
        self.warning_label.setVisible(_is_strong_ai(settings))

        form = QFormLayout()
        form.addRow("Deinterlace override", self.deinterlace_combo)
        form.addRow("QTGMC preset", self.qtgmc_combo)
        form.addRow("AI backend", self.ai_backend_combo)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.warning_label)
        layout.addWidget(buttons)

    def get_settings(self) -> RestoreSettings:
        """Return the original settings with accepted advanced overrides."""

        values = self._settings.to_dict()
        values.update(
            deinterlace=str(self.deinterlace_combo.currentData()),
            qtgmc_preset=str(self.qtgmc_combo.currentData()),
            ai_backend=str(self.ai_backend_combo.currentData()),
        )
        return RestoreSettings.from_mapping(values)


SettingsDialog = AdvancedSettingsDialog

__all__ = [
    "AI_BACKEND_OPTIONS",
    "AI_SCALE_OPTIONS",
    "AdvancedSettingsDialog",
    "DEINTERLACE_OPTIONS",
    "OUTPUT_PROFILE_OPTIONS",
    "PRESET_OPTIONS",
    "QTGMC_OPTIONS",
    "STRONG_AI_WARNING",
    "SettingsDialog",
    "TARGET_RESOLUTION_OPTIONS",
    "add_options",
]
