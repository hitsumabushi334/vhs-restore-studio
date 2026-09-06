from __future__ import annotations

import subprocess
from pathlib import Path

from vhs_restore.utils import deps
from vhs_restore.upscale.base import UpscaleBackend, select_upscale_backend
from vhs_restore.upscale.classical import ClassicalBackend
from vhs_restore.upscale.realesrgan import RealESRGANBackend
from vhs_restore.upscale.video2x import Video2XBackend


class StubBackend:
    def __init__(self, name: str, available: bool):
        self.name = name
        self.available = available
        self.availability_checks = 0

    def is_available(self) -> bool:
        self.availability_checks += 1
        return self.available

    def upscale(
        self,
        input: Path,
        output: Path,
        scale: int,
        model: str | None = None,
    ) -> Path:
        return output


def test_selector_prefers_video2x_then_realesrgan_then_classical():
    video2x = StubBackend("video2x", available=True)
    realesrgan = StubBackend("realesrgan", available=True)
    classical = StubBackend("classical", available=True)

    selected = select_upscale_backend(
        video2x=video2x,
        realesrgan=realesrgan,
        classical=classical,
    )

    assert isinstance(selected, UpscaleBackend)
    assert selected is video2x
    assert video2x.availability_checks == 1
    assert realesrgan.availability_checks == 0


def test_selector_uses_realesrgan_when_video2x_is_unavailable():
    video2x = StubBackend("video2x", available=False)
    realesrgan = StubBackend("realesrgan", available=True)
    classical = StubBackend("classical", available=True)

    selected = select_upscale_backend(
        video2x=video2x,
        realesrgan=realesrgan,
        classical=classical,
    )

    assert selected is realesrgan
    assert video2x.availability_checks == 1
    assert realesrgan.availability_checks == 1


def test_selector_degrades_to_classical_when_ai_backends_are_unavailable():
    video2x = StubBackend("video2x", available=False)
    realesrgan = StubBackend("realesrgan", available=False)
    classical = StubBackend("classical", available=True)

    selected = select_upscale_backend(
        video2x=video2x,
        realesrgan=realesrgan,
        classical=classical,
    )

    assert selected is classical
    assert video2x.availability_checks == 1
    assert realesrgan.availability_checks == 1


def test_video_selection_skips_realesrgan_when_video2x_is_unavailable(
    tmp_path: Path,
):
    video2x = StubBackend("video2x", available=False)
    realesrgan = StubBackend("realesrgan-ncnn-vulkan", available=True)
    classical = StubBackend("classical", available=True)

    selected = select_upscale_backend(
        input=tmp_path / "capture.mp4",
        video2x=video2x,
        realesrgan=realesrgan,
        classical=classical,
    )

    assert selected is classical
    assert video2x.availability_checks == 1
    assert realesrgan.availability_checks == 0


def test_video2x_vulkan_probe_failure_falls_back_to_classical(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setattr(
        "vhs_restore.upscale.video2x.find_tool",
        lambda _: Path("C:/tools/video2x.exe"),
    )
    monkeypatch.setattr(
        "vhs_restore.upscale.classical.find_tool",
        lambda _: Path("C:/tools/ffmpeg.exe"),
    )
    monkeypatch.setattr(
        deps,
        "_probe_video2x_vulkan",
        lambda _: (False, "no Vulkan-capable GPU reported"),
    )

    selected = select_upscale_backend(input=tmp_path / "capture.mp4")

    assert isinstance(selected, ClassicalBackend)


def test_video2x_probe_command_failure_keeps_classical_reachable(
    tmp_path: Path,
    monkeypatch,
):
    probe_calls: list[list[str]] = []

    monkeypatch.setattr(
        "vhs_restore.upscale.video2x.find_tool",
        lambda _: Path("C:/tools/video2x.exe"),
    )
    monkeypatch.setattr(
        "vhs_restore.upscale.classical.find_tool",
        lambda _: Path("C:/tools/ffmpeg.exe"),
    )

    def failed_probe(argv: list[str], **_: object):
        probe_calls.append(argv)
        return subprocess.CompletedProcess(
            argv,
            1,
            stdout="Video2X failed to enumerate Vulkan devices\n",
            stderr=None,
        )

    monkeypatch.setattr(deps, "run_command", failed_probe)

    selected = select_upscale_backend(input=tmp_path / "capture.mp4")

    assert isinstance(selected, ClassicalBackend)
    assert probe_calls == [[str(Path("C:/tools/video2x.exe")), "--list-gpus"]]


def test_default_selector_uses_classical_when_ai_executables_are_missing(monkeypatch):
    monkeypatch.setattr("vhs_restore.upscale.video2x.find_tool", lambda _: None)
    monkeypatch.setattr("vhs_restore.upscale.realesrgan.find_tool", lambda _: None)

    selected = select_upscale_backend()

    assert isinstance(selected, ClassicalBackend)


def test_video2x_upscale_uses_argv_and_a_safe_unique_output(
    tmp_path: Path,
    monkeypatch,
):
    source = tmp_path / "日本語 capture (raw) [01].mp4"
    source.write_bytes(b"source")
    desired = tmp_path / "restored output.mp4"
    desired.write_bytes(b"existing")
    calls: list[list[str]] = []

    monkeypatch.setattr(
        "vhs_restore.upscale.video2x.find_tool",
        lambda _: Path("C:/tools/video2x.exe"),
    )
    monkeypatch.setattr(
        "vhs_restore.upscale.video2x.run_command",
        lambda argv, **_: calls.append(argv)
        or subprocess.CompletedProcess(argv, 0, "", ""),
    )

    result = Video2XBackend().upscale(
        source,
        desired,
        scale=2,
        model="realesrgan-x4plus",
    )

    assert result == tmp_path / "restored output (1).mp4"
    assert result != source
    assert calls == [
        [
            str(Path("C:/tools/video2x.exe")),
            "-i",
            str(source),
            "-o",
            str(result),
            "-p",
            "realesrgan",
            "-s",
            "2",
            "--realesrgan-model",
            "realesrgan-x4plus",
        ]
    ]


def test_realesrgan_upscale_uses_vulkan_cli_and_preserves_unicode_paths(
    tmp_path: Path,
    monkeypatch,
):
    source = tmp_path / "日本語 clip (raw).png"
    source.write_bytes(b"source")
    output = tmp_path / "拡大済み output.png"
    calls: list[list[str]] = []

    monkeypatch.setattr(
        "vhs_restore.upscale.realesrgan.find_tool",
        lambda _: Path("C:/tools/realesrgan-ncnn-vulkan.exe"),
    )
    monkeypatch.setattr(
        "vhs_restore.upscale.realesrgan.run_command",
        lambda argv, **_: calls.append(argv)
        or subprocess.CompletedProcess(argv, 0, "", ""),
    )

    result = RealESRGANBackend().upscale(
        source,
        output,
        scale=4,
        model="realesrgan-x4plus",
    )

    assert result == output
    assert calls == [
        [
            str(Path("C:/tools/realesrgan-ncnn-vulkan.exe")),
            "-i",
            str(source),
            "-o",
            str(output),
            "-n",
            "realesrgan-x4plus",
            "-s",
            "4",
        ]
    ]


def test_classical_upscale_uses_ffmpeg_scale_filter_and_never_overwrites(
    tmp_path: Path,
    monkeypatch,
):
    source = tmp_path / "日本語 capture (raw) [01].mp4"
    source.write_bytes(b"source")
    output = tmp_path / "classical output.mp4"
    calls: list[list[str]] = []

    monkeypatch.setattr(
        "vhs_restore.upscale.classical.find_tool",
        lambda _: Path("C:/tools/ffmpeg.exe"),
    )
    monkeypatch.setattr(
        "vhs_restore.upscale.classical.run_command",
        lambda argv, **_: calls.append(argv)
        or subprocess.CompletedProcess(argv, 0, "", ""),
    )

    result = ClassicalBackend().upscale(source, output, scale=2)

    assert result == output
    assert calls == [
        [
            str(Path("C:/tools/ffmpeg.exe")),
            "-n",
            "-i",
            str(source),
            "-vf",
            "scale=iw*2:ih*2",
            "-c:a",
            "copy",
            str(output),
        ]
    ]


def test_upscale_never_uses_the_source_as_output(
    tmp_path: Path,
    monkeypatch,
):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    calls: list[list[str]] = []

    monkeypatch.setattr(
        "vhs_restore.upscale.classical.find_tool",
        lambda _: Path("C:/tools/ffmpeg.exe"),
    )
    monkeypatch.setattr(
        "vhs_restore.upscale.classical.run_command",
        lambda argv, **_: calls.append(argv)
        or subprocess.CompletedProcess(argv, 0, "", ""),
    )

    result = ClassicalBackend().upscale(source, source, scale=2)

    assert result == tmp_path / "source (1).mp4"
    assert str(source) not in calls[0][-1:]
    assert source.read_bytes() == b"source"


def test_missing_backend_executable_is_reported_as_unavailable(monkeypatch):
    monkeypatch.setattr("vhs_restore.upscale.video2x.find_tool", lambda _: None)
    monkeypatch.setattr("vhs_restore.upscale.realesrgan.find_tool", lambda _: None)
    monkeypatch.setattr("vhs_restore.upscale.classical.find_tool", lambda _: None)

    assert Video2XBackend().is_available() is False
    assert RealESRGANBackend().is_available() is False
    assert ClassicalBackend().is_available() is False


def test_backend_raises_a_diagnostic_when_the_command_fails(
    tmp_path: Path,
    monkeypatch,
):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    output = tmp_path / "output.mp4"

    monkeypatch.setattr(
        "vhs_restore.upscale.classical.find_tool",
        lambda _: Path("C:/tools/ffmpeg.exe"),
    )
    monkeypatch.setattr(
        "vhs_restore.upscale.classical.run_command",
        lambda argv, **_: subprocess.CompletedProcess(
            argv,
            1,
            "ffmpeg failed",
            "",
        ),
    )

    try:
        ClassicalBackend().upscale(source, output, scale=2)
    except RuntimeError as exc:
        assert "ffmpeg" in str(exc)
        assert "ffmpeg failed" in str(exc)
    else:
        raise AssertionError("a failed backend command must raise RuntimeError")
