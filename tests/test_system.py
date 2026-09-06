from pathlib import Path

import pytest

from vhs_restore.utils.system import find_tool, vendor_root


@pytest.fixture
def isolated_vendor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("VHS_RESTORE_VENDOR", str(tmp_path))
    monkeypatch.setenv("PATH", "")
    return tmp_path


def test_find_tool_returns_existing_explicit_path(tmp_path: Path) -> None:
    tool = tmp_path / "custom-tool.exe"
    tool.write_bytes(b"tool")

    assert find_tool(tool) == tool


def test_find_tool_finds_video2x_in_known_vendor_dir(isolated_vendor: Path) -> None:
    executable = isolated_vendor / "video2x" / "video2x.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"video2x")

    assert find_tool("video2x") == executable


def test_find_tool_finds_realesrgan_in_japanese_nested_vendor_path(
    isolated_vendor: Path,
) -> None:
    executable = isolated_vendor / "tools" / "日本語 tool" / "realesrgan-ncnn-vulkan.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"realesrgan")

    assert find_tool("realesrgan-ncnn-vulkan") == executable


def test_find_tool_returns_none_when_tool_missing(isolated_vendor: Path) -> None:
    assert find_tool("missing-tool") is None


def test_vendor_root_honors_override(isolated_vendor: Path) -> None:
    assert vendor_root() == isolated_vendor
