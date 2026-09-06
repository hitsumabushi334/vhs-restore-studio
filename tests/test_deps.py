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


def test_detect_dependencies_finds_ffprobe_and_reports_qtgmc_fallback(
    monkeypatch: pytest.MonkeyPatch,
):
    deps = _load_deps_module()
    available = {"ffmpeg", "ffprobe", "vspipe"}

    monkeypatch.setattr(
        deps,
        "find_tool",
        lambda name: Path(f"C:/tools/{name}.exe") if name in available else None,
    )

    def fake_run_command(argv: list[str], **_: object):
        if "--info" in argv:
            return subprocess.CompletedProcess(
                argv,
                1,
                stdout="ModuleNotFoundError: No module named 'havsfunc'\n",
                stderr=None,
            )
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=f"{Path(argv[0]).stem} version 1.0.0\n",
            stderr=None,
        )

    monkeypatch.setattr(deps, "run_command", fake_run_command)

    report = deps.detect_dependencies()

    assert report.ffprobe == Path("C:/tools/ffprobe.exe")
    assert report.tools["ffprobe"].available is True
    assert report.tools["vspipe"].found is True
    assert report.tools["vspipe"].available is True
    assert report.qtgmc_available is False
    assert any(
        "QTGMC unavailable" in message and "bwdif" in message
        for message in report.messages
    )


def test_found_but_unusable_required_tool_is_not_available_and_error_is_visible(
    monkeypatch: pytest.MonkeyPatch,
):
    deps = _load_deps_module()
    available = {"ffmpeg", "ffprobe"}

    monkeypatch.setattr(
        deps,
        "find_tool",
        lambda name: Path(f"C:/tools/{name}.exe") if name in available else None,
    )

    def fake_run_command(argv: list[str], **_: object):
        if Path(argv[0]).stem == "ffmpeg":
            return subprocess.CompletedProcess(
                argv,
                1,
                stdout="ffmpeg failed to start\n",
                stderr=None,
            )
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout="ffprobe version 8.1.1\n",
            stderr=None,
        )

    monkeypatch.setattr(deps, "run_command", fake_run_command)

    report = deps.detect_dependencies()

    ffmpeg = report.tools["ffmpeg"]
    assert ffmpeg.found is True
    assert ffmpeg.available is False
    assert "ffmpeg" in report.required_missing
    assert report.ready is False
    assert ffmpeg.error == "ffmpeg failed to start"
    assert "ffmpeg failed to start" in deps._format_status(ffmpeg)
    assert any("ffmpeg failed to start" in message for message in report.messages)


def test_ffmpeg_banner_on_gnu_version_flag_is_still_available(
    monkeypatch: pytest.MonkeyPatch,
):
    deps = _load_deps_module()
    available = {"ffmpeg", "ffprobe"}

    monkeypatch.setattr(
        deps,
        "find_tool",
        lambda name: Path(f"C:/tools/{name}.exe") if name in available else None,
    )

    def fake_run_command(argv: list[str], **_: object):
        stem = Path(argv[0]).stem
        flag = argv[1] if len(argv) > 1 else ""
        if flag == "--version":
            return subprocess.CompletedProcess(
                argv,
                2880417800 if stem == "ffmpeg" else 1,
                stdout=None,
                stderr=f"{stem} version 8.1.1-full_build-www.gyan.dev Copyright (c) 2000-2026\n",
            )
        if flag == "-version":
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=f"{stem} version 8.1.1-full_build-www.gyan.dev\n",
                stderr=None,
            )
        return subprocess.CompletedProcess(argv, 0, stdout=f"{stem} version 1.0.0\n", stderr=None)

    monkeypatch.setattr(deps, "run_command", fake_run_command)

    report = deps.detect_dependencies()

    assert report.ready is True
    assert report.tools["ffmpeg"].available is True
    assert report.tools["ffprobe"].available is True
    assert report.tool_versions["ffmpeg"] == "8.1.1-full_build-www.gyan.dev"
    assert "ffmpeg" not in report.required_missing


def test_realesrgan_usage_output_is_not_marked_broken(
    monkeypatch: pytest.MonkeyPatch,
):
    deps = _load_deps_module()
    available = {"ffmpeg", "ffprobe", "realesrgan-ncnn-vulkan"}

    monkeypatch.setattr(
        deps,
        "find_tool",
        lambda name: Path(f"C:/tools/{name}.exe") if name in available else None,
    )

    def fake_run_command(argv: list[str], **_: object):
        stem = Path(argv[0]).stem
        if stem == "realesrgan-ncnn-vulkan":
            return subprocess.CompletedProcess(
                argv,
                4294967295,
                stdout=None,
                stderr="Usage: realesrgan-ncnn-vulkan -i infile -o outfile [options]...\n-h show this help\n",
            )
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=f"{stem} version 8.1.1\n",
            stderr=None,
        )

    monkeypatch.setattr(deps, "run_command", fake_run_command)

    report = deps.detect_dependencies()

    realesrgan = report.tools["realesrgan-ncnn-vulkan"]
    assert realesrgan.found is True
    assert realesrgan.available is True
    assert realesrgan.error is None
    assert realesrgan.capability_available is False
    assert report.selected_ai_backend is None
    assert "realesrgan-ncnn-vulkan" not in report.optional_missing
    assert "BROKEN" not in deps._format_status(realesrgan)


def test_ffmpeg_usage_or_bare_runtime_number_is_not_available(
    monkeypatch: pytest.MonkeyPatch,
):
    deps = _load_deps_module()
    available = {"ffmpeg", "ffprobe"}

    monkeypatch.setattr(
        deps,
        "find_tool",
        lambda name: Path(f"C:/tools/{name}.exe") if name in available else None,
    )

    def fake_run_command(argv: list[str], **_: object):
        stem = Path(argv[0]).stem
        if stem == "ffmpeg":
            return subprocess.CompletedProcess(
                argv,
                1,
                stdout="This tool requires Windows 10.0 or later\nUsage: ffmpeg-shim [options]\n",
                stderr=None,
            )
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout="ffprobe version 8.1.1\n",
            stderr=None,
        )

    monkeypatch.setattr(deps, "run_command", fake_run_command)

    report = deps.detect_dependencies()

    ffmpeg = report.tools["ffmpeg"]
    assert ffmpeg.found is True
    assert ffmpeg.available is False
    assert "ffmpeg" in report.required_missing
    assert report.ready is False


def test_video2x_is_not_an_ai_backend_without_a_vulkan_capability_probe(
    monkeypatch: pytest.MonkeyPatch,
):
    deps = _load_deps_module()
    available = {"ffmpeg", "ffprobe", "video2x"}

    monkeypatch.setattr(
        deps,
        "find_tool",
        lambda name: Path(f"C:/tools/{name}.exe") if name in available else None,
    )

    def fake_run_command(argv: list[str], **_: object):
        if "--list-gpus" in argv:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout="No Vulkan devices found\n",
                stderr=None,
            )
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=f"{Path(argv[0]).stem} version 6.4.0\n",
            stderr=None,
        )

    monkeypatch.setattr(deps, "run_command", fake_run_command)

    report = deps.detect_dependencies()

    assert report.tools["video2x"].available is True
    assert report.tools["video2x"].capability_available is False
    assert report.selected_ai_backend is None
    assert report.ai_backend_available is False
    assert any("Vulkan" in message for message in report.messages)
    assert any("AI backend unavailable" in message for message in report.messages)


def test_video2x_selected_backend_is_recorded_after_vulkan_probe(
    monkeypatch: pytest.MonkeyPatch,
):
    deps = _load_deps_module()
    available = {"ffmpeg", "ffprobe", "video2x"}

    monkeypatch.setattr(
        deps,
        "find_tool",
        lambda name: Path(f"C:/tools/{name}.exe") if name in available else None,
    )

    def fake_run_command(argv: list[str], **_: object):
        if "--list-gpus" in argv:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout="0. AMD Radeon\n    Vulkan API Version: 1.3.280\n",
                stderr=None,
            )
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=f"{Path(argv[0]).stem} version 6.4.0\n",
            stderr=None,
        )

    monkeypatch.setattr(deps, "run_command", fake_run_command)

    report = deps.detect_dependencies()

    assert report.tools["video2x"].capability_available is True
    assert report.selected_ai_backend == "video2x"
    assert report.ai_backend_available is True


def test_video2x_is_preferred_over_realesrgan_when_both_are_available(
    monkeypatch: pytest.MonkeyPatch,
):
    deps = _load_deps_module()
    available = {
        "ffmpeg",
        "ffprobe",
        "video2x",
        "realesrgan-ncnn-vulkan",
    }

    monkeypatch.setattr(
        deps,
        "find_tool",
        lambda name: Path(f"C:/tools/{name}.exe") if name in available else None,
    )

    def fake_run_command(argv: list[str], **_: object):
        if "--list-gpus" in argv:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout="0. AMD Radeon\n    Vulkan API Version: 1.3.280\n",
                stderr=None,
            )
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=f"{Path(argv[0]).stem} version 1.0.0\n",
            stderr=None,
        )

    monkeypatch.setattr(deps, "run_command", fake_run_command)

    report = deps.detect_dependencies()

    assert report.selected_ai_backend == "video2x"


def test_expected_version_mismatch_is_reported_without_marking_tool_broken(
    monkeypatch: pytest.MonkeyPatch,
):
    deps = _load_deps_module()
    available = {"ffmpeg", "ffprobe"}

    monkeypatch.setattr(
        deps,
        "find_tool",
        lambda name: Path(f"C:/tools/{name}.exe") if name in available else None,
    )

    def fake_run_command(argv: list[str], **_: object):
        version = "7.0.0" if Path(argv[0]).stem == "ffmpeg" else "8.1.1"
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=f"{Path(argv[0]).stem} version {version}\n",
            stderr=None,
        )

    monkeypatch.setattr(deps, "run_command", fake_run_command)

    report = deps.detect_dependencies()

    ffmpeg = report.tools["ffmpeg"]
    assert ffmpeg.available is True
    assert ffmpeg.version_matches is False
    assert any("ffmpeg version mismatch" in message for message in report.messages)


def test_extract_version_scans_all_lines_and_accepts_common_prefixes():
    deps = _load_deps_module()

    assert deps._extract_version("banner\nVideo2X version: 6.4.0\n") == "6.4.0"
    assert deps._extract_version("build info\nrelease v0.2.0 (Vulkan)\n") == "v0.2.0"


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
    monkeypatch.setattr(
        deps,
        "run_command",
        lambda argv, **_: subprocess.CompletedProcess(
            argv,
            0,
            stdout=f"{Path(argv[0]).stem} version 1.0.0\n",
            stderr=None,
        ),
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
    monkeypatch.setattr(
        deps,
        "run_command",
        lambda argv, **_: subprocess.CompletedProcess(
            argv,
            0,
            stdout=f"{Path(argv[0]).stem} version 1.0.0\n",
            stderr=None,
        ),
    )

    report = deps.detect_dependencies()

    assert report.ai_backend_available is True
    assert not any("AI backend unavailable" in message for message in report.messages)
