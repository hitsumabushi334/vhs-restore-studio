"""Local dependency discovery and diagnostics."""

from __future__ import annotations

import json
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, replace
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
_VERSION_RE = re.compile(
    r"\bversion\b\s*[:=]?\s*(?P<version>v?\d+(?:\.\d+)+(?:[-+._][^\s,;\)\]]+)?)",
    re.IGNORECASE,
)
_BARE_VERSION_RE = re.compile(
    r"(?<![\w.])(?P<version>v?\d+(?:\.\d+)+(?:[-+._][^\s,;\)\]]+)?)",
    re.IGNORECASE,
)
_NUMERIC_VERSION_RE = re.compile(r"(?<!\d)(?P<version>\d+(?:\.\d+)+)")
_VULKAN_DEVICE_RE = re.compile(r"vulkan\s+api\s+version", re.IGNORECASE)

_QTGMC_PROBE_SCRIPT = """\
import vapoursynth as vs
import havsfunc

if not callable(getattr(havsfunc, "QTGMC", None)):
    raise RuntimeError("havsfunc.QTGMC is unavailable")

clip = vs.core.std.BlankClip(
    width=16,
    height=16,
    length=8,
    format=vs.YUV420P8,
)
clip = vs.core.std.SetFrameProps(clip, _FieldBased=2)
havsfunc.QTGMC(clip, Preset="Fast", TFF=True, FPSDivisor=2).set_output()
"""


@dataclass(frozen=True, slots=True)
class ToolStatus:
    """The observed state of one local executable.

    ``found`` means that PATH resolution returned an executable.  ``available``
    additionally requires a successful version probe (or, for Real-ESRGAN,
    a usage banner proving the image CLI starts).
    """

    name: str
    executable: str
    required: bool
    path: Path | None
    available: bool
    version: str | None = None
    expected_version: str | None = None
    error: str | None = None
    version_matches: bool | None = None
    capability_available: bool | None = None
    capability_error: str | None = None

    @property
    def found(self) -> bool:
        """Return whether the executable was resolved on the local PATH."""

        return self.path is not None

    @property
    def usable(self) -> bool:
        """Return whether the executable passed its basic probe."""

        return self.available


@dataclass(frozen=True, slots=True)
class DependencyReport:
    """A complete, non-throwing snapshot of local tool availability."""

    tools: Mapping[str, ToolStatus]
    tool_versions: Mapping[str, str | None]
    expected_versions: Mapping[str, str]
    required_missing: tuple[str, ...]
    optional_missing: tuple[str, ...]
    messages: tuple[str, ...]
    qtgmc: bool = False
    qtgmc_error: str | None = None
    selected_ai_backend: str | None = None
    version_mismatches: tuple[str, ...] = ()

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
        """Return whether the QTGMC graph probe completed successfully."""

        return self.qtgmc

    @property
    def ai_backend_available(self) -> bool:
        """Return whether a Vulkan-capable AI backend was selected."""

        return self.selected_ai_backend is not None

    @property
    def ai_available(self) -> bool:
        """Alias for ``ai_backend_available``."""

        return self.ai_backend_available

    @property
    def ai_backend(self) -> str | None:
        """Alias for the explicitly selected AI backend name."""

        return self.selected_ai_backend


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
    """Extract a semantic-looking version from noisy tool output."""

    if not output:
        return None

    for pattern in (_VERSION_RE, _BARE_VERSION_RE):
        match = pattern.search(output)
        if match:
            return match.group("version").rstrip(".,;:)")
    return None


def _version_numbers(value: str) -> tuple[int, ...] | None:
    match = _NUMERIC_VERSION_RE.search(value)
    if match is None:
        return None
    return tuple(int(part) for part in match.group("version").split("."))


def _compare_versions(
    observed: str | None,
    expected: str | None,
) -> bool | None:
    """Compare release numbers while tolerating vendor/build labels."""

    if observed is None or expected is None:
        return None

    observed_numbers = _version_numbers(observed)
    expected_numbers = _version_numbers(expected)
    if observed_numbers is not None and expected_numbers is not None:
        return observed_numbers == expected_numbers
    return observed.strip().casefold() == expected.strip().casefold()


def _command_output(result: object) -> str:
    chunks: list[str] = []
    for attribute in ("stdout", "stderr"):
        value = getattr(result, attribute, None)
        if value:
            chunks.append(str(value))
    return "\n".join(chunks)


def _compact_detail(detail: str) -> str:
    compact = " ".join(detail.split())
    return compact[:300]


def _output_looks_like_usage(output: str) -> bool:
    normalized = output.casefold()
    return "usage:" in normalized or "show this help" in normalized


def _read_tool_version(path: Path) -> tuple[str | None, str | None]:
    """Probe a tool without treating GNU/FFmpeg flag differences as failure.

    Gyan FFmpeg 8 accepts ``-version`` (exit 0) but ``--version`` prints a
    banner and returns a non-zero code. ffmpeg/ffprobe are healthy only when
    ``-version`` (or another version flag) exits 0. A non-zero banner is never
    enough. Usage/help is accepted only for Real-ESRGAN, which has no version
    flag.
    """

    stem = path.stem.casefold()
    is_ffmpeg_family = stem in {"ffmpeg", "ffprobe"}
    flags = ("-version", "--version") if is_ffmpeg_family else ("--version", "-version")
    last_error: str | None = None
    usage_seen = False
    for flag in flags:
        try:
            result = run_command([str(path), flag])
        except Exception as exc:
            last_error = _compact_detail(str(exc))
            continue

        output = _command_output(result)
        version = _extract_version(output)
        if result.returncode == 0:
            return version, None
        if stem.startswith("realesrgan") and _output_looks_like_usage(output):
            usage_seen = True
        last_error = _compact_detail(output) or (
            f"command exited with code {result.returncode}"
        )
    if usage_seen:
        return None, None
    return None, last_error


def _probe_qtgmc(path: Path) -> tuple[bool, str | None]:
    """Evaluate a minimal QTGMC graph through the installed VSPipe runtime."""

    try:
        with tempfile.TemporaryDirectory(prefix="vhs-restore-qtgmc-") as directory:
            script_path = Path(directory) / "qtgmc_probe.vpy"
            script_path.write_text(_QTGMC_PROBE_SCRIPT, encoding="utf-8")
            result = run_command(
                [str(path), "--info", str(script_path), "--"]
            )
    except Exception as exc:
        return False, _compact_detail(str(exc))

    output = _command_output(result)
    normalized = output.casefold()
    if any(
        marker in normalized
        for marker in (
            "python exception",
            "script evaluation failed",
            "script error",
            "no module named",
            "qtgmc is unavailable",
        )
    ):
        return False, _compact_detail(output) or f"command exited with code {result.returncode}"
    if result.returncode != 0:
        # VSPipe may exit non-zero while only printing API-deprecation warnings.
        if "warning:" in normalized and "error" not in normalized:
            return True, None
        detail = _compact_detail(output)
        return False, detail or f"command exited with code {result.returncode}"
    return True, None


def _probe_video2x_vulkan(path: Path) -> tuple[bool, str | None]:
    """Require Video2X to enumerate a Vulkan device before selecting it."""

    try:
        result = run_command([str(path), "--list-gpus"])
    except Exception as exc:
        gpu_error = _compact_detail(str(exc))
        result = None
        gpu_error = gpu_error
    else:
        gpu_output = _command_output(result)
        if result.returncode == 0:
            if _VULKAN_DEVICE_RE.search(gpu_output) is not None:
                return True, None
            detail = _compact_detail(gpu_output)
            return False, (
                f"no Vulkan-capable GPU reported: {detail}"
                if detail
                else "no Vulkan-capable GPU reported"
            )
        gpu_error = _compact_detail(gpu_output) or (
            f"command exited with code {result.returncode}"
        )
        unrecognized = "unrecognised option" in gpu_error.casefold() or (
            "unrecognized option" in gpu_error.casefold()
        )
        if not unrecognized:
            return False, gpu_error

    last_error = gpu_error
    for flag in ("--list-devices", "-l"):
        try:
            result = run_command([str(path), flag])
        except Exception as exc:
            last_error = _compact_detail(str(exc))
            continue
        output = _command_output(result)
        if result.returncode != 0:
            last_error = _compact_detail(output) or (
                f"command exited with code {result.returncode}"
            )
            continue
        normalized = output.casefold()
        if not output.strip() or "no vulkan" in normalized or "no device" in normalized:
            last_error = _compact_detail(output) or "no Vulkan-capable GPU reported"
            continue
        return True, None
    return False, last_error


def probe_video2x_vulkan(path: str | Path) -> tuple[bool, str | None]:
    """Return whether Video2X can enumerate a usable Vulkan device."""

    return _probe_video2x_vulkan(Path(path))


def _select_ai_backend(
    statuses: dict[str, ToolStatus],
    messages: list[str],
) -> str | None:
    """Probe optional AI capabilities and return an explicit backend name."""

    video2x = statuses["video2x"]
    if video2x.available:
        capability_available, capability_error = probe_video2x_vulkan(
            video2x.path  # type: ignore[arg-type]
        )
        video2x = replace(
            video2x,
            capability_available=capability_available,
            capability_error=capability_error,
        )
        statuses["video2x"] = video2x
        if not capability_available:
            detail = f": {capability_error}" if capability_error else ""
            messages.append(
                "video2x found but its Vulkan backend is unavailable"
                + detail
                + "."
            )

    realesrgan = replace(
        statuses["realesrgan-ncnn-vulkan"],
        capability_available=False,
        capability_error="image CLI only; not used for video upscale",
    )
    statuses["realesrgan-ncnn-vulkan"] = realesrgan

    if video2x.capability_available:
        return video2x.name
    return None


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
    version_mismatches: list[str] = []

    for name, executable, required in _TOOL_SPECS:
        try:
            path = find_tool(executable)
        except Exception as exc:
            path = None
            error = _compact_detail(str(exc))
        else:
            error = None

        version = None
        if path is not None:
            version, version_error = _read_tool_version(path)
            if version_error is not None:
                error = version_error

        expected_version = expected_versions.get(name)
        version_matches = _compare_versions(version, expected_version)
        available = path is not None and error is None
        status = ToolStatus(
            name=name,
            executable=executable,
            required=required,
            path=path,
            available=available,
            version=version,
            expected_version=expected_version,
            error=error,
            version_matches=version_matches,
        )
        statuses[name] = status
        observed_versions[name] = version

        if not available:
            (required_missing if required else optional_missing).append(name)
        if error:
            messages.append(f"{name} unavailable: {error}")
        if version_matches is False:
            version_mismatches.append(name)
            messages.append(
                f"{name} version mismatch: expected {expected_version}, "
                f"observed {version}."
            )

    if required_missing:
        messages.append(
            "Required dependency unavailable: "
            + ", ".join(required_missing)
            + "."
        )

    qtgmc_available = False
    qtgmc_error: str | None = None
    vspipe = statuses["vspipe"]
    if vspipe.available:
        qtgmc_available, qtgmc_error = _probe_qtgmc(
            vspipe.path  # type: ignore[arg-type]
        )
    elif vspipe.error:
        qtgmc_error = vspipe.error

    if not qtgmc_available:
        detail = f": {qtgmc_error}" if qtgmc_error else ""
        messages.append(
            "QTGMC unavailable"
            + detail
            + "; FFmpeg bwdif fallback will be used."
        )

    selected_ai_backend = _select_ai_backend(statuses, messages)
    if selected_ai_backend is None:
        messages.append("AI backend unavailable; classical scaling will be used.")
    else:
        messages.append(f"AI backend selected: {selected_ai_backend} (Vulkan).")

    return DependencyReport(
        tools=statuses,
        tool_versions=observed_versions,
        expected_versions=expected_versions,
        required_missing=tuple(required_missing),
        optional_missing=tuple(optional_missing),
        messages=tuple(messages),
        qtgmc=qtgmc_available,
        qtgmc_error=qtgmc_error,
        selected_ai_backend=selected_ai_backend,
        version_mismatches=tuple(version_mismatches),
    )


def _format_status(status: ToolStatus) -> str:
    if not status.found:
        state = "MISSING" if status.required else "OPTIONAL"
        detail = "required" if status.required else "unavailable (fallback will be used)"
        if status.error:
            detail += f": {status.error}"
        return f"[{state:<8}] {status.name}  {detail}"

    if not status.available:
        detail = status.error or "probe failed"
        return f"[{'BROKEN':<8}] {status.name}  {status.path}: {detail}"

    state = "WARN" if status.version_matches is False else "OK"
    version = f" version {status.version}" if status.version else ""
    detail = f"{status.path}{version}"
    if status.version_matches is False:
        detail += f" (expected {status.expected_version})"
    if status.capability_available is False:
        if status.capability_error:
            detail += f": {status.capability_error}"
        else:
            detail += ": Vulkan probe failed"
    return f"[{state:<8}] {status.name}  {detail}"


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
