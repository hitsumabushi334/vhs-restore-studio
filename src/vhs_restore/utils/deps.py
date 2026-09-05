"""Local dependency discovery and diagnostics."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from .process import run_command
from .system import find_tool


_TOOL_SPECS: tuple[tuple[str, str, bool], ...] = (
    ("ffmpeg", "ffmpeg", True),
    ("ffprobe", "ffprobe", True),
    ("vspipe", "vspipe", False),
    ("video2x", "video2x", False),
    ("realesrgan-ncnn-vulkan", "realesrgan-ncnn-vulkan", False),
)
_VERSION_RE = re.compile(r"\bversion\s+([^\s,]+)", re.IGNORECASE)
_V_VERSION_RE = re.compile(r"\bv(\d+(?:\.\d+)+(?:[-+._][^\s,]+)?)\b")


@dataclass(frozen=True, slots=True)
class ToolStatus:
    """The observed state of one local executable."""

    name: str
    executable: str
    required: bool
    path: Path | None
    available: bool
    version: str | None = None
    expected_version: str | None = None
    error: str | None = None

    @property
    def found(self) -> bool:
        """Return whether the executable was resolved on the local PATH."""

        return self.path is not None


@dataclass(frozen=True, slots=True)
class DependencyReport:
    """A complete, non-throwing snapshot of local tool availability."""

    tools: Mapping[str, ToolStatus]
    tool_versions: Mapping[str, str | None]
    expected_versions: Mapping[str, str]
    required_missing: tuple[str, ...]
    optional_missing: tuple[str, ...]
    messages: tuple[str, ...]

    @property
    def ready(self) -> bool:
        """Return whether all required dependencies are available."""

        return not self.required_missing

    @property
    def is_ready(self) -> bool:
        """Alias for ``ready`` for callers that prefer an explicit name."""

        return self.ready

    @property
    def all_required_available(self) -> bool:
        """Return whether all required dependencies are available."""

        return self.ready

    @property
    def missing_required(self) -> tuple[str, ...]:
        """Alias for ``required_missing``."""

        return self.required_missing

    @property
    def missing_optional(self) -> tuple[str, ...]:
        """Alias for ``optional_missing``."""

        return self.optional_missing

    def _path(self, name: str) -> Path | None:
        status = self.tools.get(name)
        return None if status is None else status.path

    @property
    def ffmpeg(self) -> Path | None:
        return self._path("ffmpeg")

    @property
    def ffmpeg_path(self) -> Path | None:
        return self.ffmpeg

    @property
    def ffprobe(self) -> Path | None:
        return self._path("ffprobe")

    @property
    def ffprobe_path(self) -> Path | None:
        return self.ffprobe

    @property
    def vspipe(self) -> Path | None:
        return self._path("vspipe")

    @property
    def vspipe_path(self) -> Path | None:
        return self.vspipe

    @property
    def video2x(self) -> Path | None:
        return self._path("video2x")

    @property
    def video2x_path(self) -> Path | None:
        return self.video2x

    @property
    def realesrgan_ncnn_vulkan(self) -> Path | None:
        return self._path("realesrgan-ncnn-vulkan")

    @property
    def realesrgan_path(self) -> Path | None:
        return self.realesrgan_ncnn_vulkan

    @property
    def qtgmc_available(self) -> bool:
        status = self.tools.get("vspipe")
        return bool(status and status.available)

    @property
    def ai_backend_available(self) -> bool:
        return any(
            self.tools[name].available
            for name in ("video2x", "realesrgan-ncnn-vulkan")
            if name in self.tools
        )

    @property
    def ai_available(self) -> bool:
        """Alias for ``ai_backend_available``."""

        return self.ai_backend_available


def _versions_candidates() -> tuple[object, ...]:
    project_root = Path(__file__).resolve().parents[3]
    candidates: list[object] = [project_root / "versions.json"]
    try:
        asset = resources.files("vhs_restore").joinpath("assets", "versions.json")
    except (ModuleNotFoundError, TypeError):
        asset = None
    if asset is not None:
        candidates.append(asset)
    return tuple(candidates)


def _load_expected_versions() -> dict[str, str]:
    """Load pinned versions without making diagnostics depend on the file."""

    for candidate in _versions_candidates():
        try:
            values = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            continue
        if not isinstance(values, dict):
            continue
        return {
            str(name): str(version)
            for name, version in values.items()
            if isinstance(name, str) and isinstance(version, (str, int, float))
        }
    return {}


def _extract_version(output: str) -> str | None:
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        match = _VERSION_RE.search(line)
        if match:
            return match.group(1)
        match = _V_VERSION_RE.search(line)
        if match:
            return f"v{match.group(1)}"
        return line.split()[0]
    return None


def _read_tool_version(path: Path) -> tuple[str | None, str | None]:
    try:
        result = run_command([str(path), "--version"])
    except Exception as exc:
        return None, str(exc)

    version = _extract_version(result.stdout or "")
    if result.returncode != 0:
        detail = (result.stdout or "").strip()
        return version, detail or f"command exited with code {result.returncode}"
    return version, None


def detect_dependencies() -> DependencyReport:
    """Detect required and optional local dependencies.

    Discovery is deliberately best-effort: a missing or broken optional
    executable becomes a report entry and a fallback message instead of an
    exception.  Tool commands are always invoked through an argv list.
    """

    expected_versions = _load_expected_versions()
    statuses: dict[str, ToolStatus] = {}
    observed_versions: dict[str, str | None] = {}
    required_missing: list[str] = []
    optional_missing: list[str] = []
    messages: list[str] = []

    for name, executable, required in _TOOL_SPECS:
        try:
            path = find_tool(executable)
        except Exception as exc:
            path = None
            error = str(exc)
        else:
            error = None

        version = None
        if path is not None:
            version, version_error = _read_tool_version(path)
            if version_error is not None:
                error = version_error

        available = path is not None
        status = ToolStatus(
            name=name,
            executable=executable,
            required=required,
            path=path,
            available=available,
            version=version,
            expected_version=expected_versions.get(name),
            error=error,
        )
        statuses[name] = status
        observed_versions[name] = version

        if not available:
            (required_missing if required else optional_missing).append(name)

    if required_missing:
        messages.append(
            "Required dependency unavailable: "
            + ", ".join(required_missing)
            + "."
        )

    if not statuses["vspipe"].available:
        messages.append("QTGMC unavailable; FFmpeg bwdif fallback will be used.")

    if not any(
        statuses[name].available
        for name in ("video2x", "realesrgan-ncnn-vulkan")
    ):
        messages.append("AI backend unavailable; classical scaling will be used.")

    return DependencyReport(
        tools=statuses,
        tool_versions=observed_versions,
        expected_versions=expected_versions,
        required_missing=tuple(required_missing),
        optional_missing=tuple(optional_missing),
        messages=tuple(messages),
    )


def _format_status(status: ToolStatus) -> str:
    if not status.available:
        state = "MISSING" if status.required else "OPTIONAL"
        detail = "required" if status.required else "unavailable (fallback will be used)"
        return f"[{state:<8}] {status.name}  {detail}"

    version = f" version {status.version}" if status.version else ""
    return f"[{'OK':<8}] {status.name}  {status.path}{version}"


def main() -> int:
    """Print human-readable diagnostics for ``doctor.ps1``."""

    report = detect_dependencies()
    for name, _, _ in _TOOL_SPECS:
        print(_format_status(report.tools[name]))
    for message in report.messages:
        print(f"[INFO]    {message}")
    return 0 if report.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
