import importlib
import subprocess
from pathlib import Path

import pytest


def _load_deps_module():
    try:
        return importlib.import_module("vhs_restore.utils.deps")
    except ModuleNotFoundError as exc:
        pytest.fail(f"dependency diagnostics module is missing: {exc}")


def test_detect_dependencies_finds_ffmpeg_and_records_version(
    monkeypatch: pytest.MonkeyPatch,
):
    deps = _load_deps_module()
    ffmpeg_path = Path("C:/tools/ffmpeg.exe")

    def fake_find_tool(name: str) -> Path | None:
        return ffmpeg_path if name == "ffmpeg" else None

    def fake_run_command(argv: list[str], **_: object):
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout="ffmpeg version 8.1.1-full_build-www.gyan.dev\n",
            stderr=None,
        )

    monkeypatch.setattr(deps, "find_tool", fake_find_tool)
    monkeypatch.setattr(deps, "run_command", fake_run_command)

    report = deps.detect_dependencies()

    assert report.ffmpeg == ffmpeg_path
    assert report.ffmpeg_path == ffmpeg_path
    assert report.tools["ffmpeg"].available is True
    assert report.tool_versions["ffmpeg"] == "8.1.1-full_build-www.gyan.dev"
    assert report.expected_versions["ffmpeg"] == "8.1.1-full (Gyan)"


def test_detect_dependencies_reports_missing_ai_backend_without_failing(
    monkeypatch: pytest.MonkeyPatch,
):
    deps = _load_deps_module()
    available = {"ffmpeg", "ffprobe"}

    monkeypatch.setattr(
        deps,
        "find_tool",
        lambda name: Path(f"C:/tools/{name}.exe") if name in available else None,
    )

    report = deps.detect_dependencies()

    assert report.required_missing == ()
    assert report.ai_backend_available is False
    assert report.ai_available is False
    assert any("AI backend unavailable" in message for message in report.messages)
    assert report.tools["video2x"].available is False
    assert report.tools["realesrgan-ncnn-vulkan"].available is False


def test_detect_dependencies_marks_a_vulkan_ai_backend_available(
    monkeypatch: pytest.MonkeyPatch,
):
    deps = _load_deps_module()
    available = {"ffmpeg", "ffprobe", "realesrgan-ncnn-vulkan"}

    monkeypatch.setattr(
        deps,
        "find_tool",
        lambda name: Path(f"C:/tools/{name}.exe") if name in available else None,
    )

    report = deps.detect_dependencies()

    assert report.ai_backend_available is True
    assert not any("AI backend unavailable" in message for message in report.messages)
