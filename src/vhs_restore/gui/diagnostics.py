"""Dependency diagnostics formatting and dialog."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QPlainTextEdit, QVBoxLayout

from vhs_restore.utils.deps import DependencyReport, detect_dependencies


def format_dependency_report(report: DependencyReport) -> str:
    """Format a dependency snapshot for a copyable diagnostics view."""

    lines = [
        "VHS Restore Studio diagnostics",
        f"Required dependencies ready: {'yes' if report.ready else 'no'}",
        "",
    ]
    for name, status in report.tools.items():
        if status.path is None:
            state = "MISSING" if status.required else "OPTIONAL"
            detail = "required" if status.required else "unavailable; fallback will be used"
        elif not status.available:
            state = "BROKEN"
            detail = status.error or "probe failed"
        else:
            state = "OK" if status.version_matches is not False else "WARN"
            version = f" version {status.version}" if status.version else ""
            detail = f"{status.path}{version}"
            if status.capability_available is False:
                detail += ": Vulkan probe failed"
                if status.capability_error:
                    detail += f" ({status.capability_error})"
        lines.append(f"[{state:<8}] {name}: {detail}")

    lines.append("")
    lines.append("Messages:")
    lines.extend(f"- {message}" for message in report.messages)
    return "\n".join(lines)


class DiagnosticsDialog(QDialog):
    """Show a formatted, copyable ``DependencyReport``."""

    def __init__(self, report: DependencyReport, *, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Dependency diagnostics")
        self.resize(720, 480)

        self.text_area = QPlainTextEdit(self)
        self.text_area.setReadOnly(True)
        self.text_area.setPlainText(format_dependency_report(report))

        close_button = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        close_button.rejected.connect(self.reject)
        close_button.accepted.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(self.text_area)
        layout.addWidget(close_button)


def collect_dependency_report() -> DependencyReport:
    """Run dependency detection for callers that want a fresh snapshot."""

    return detect_dependencies()


__all__ = [
    "DiagnosticsDialog",
    "collect_dependency_report",
    "format_dependency_report",
]
