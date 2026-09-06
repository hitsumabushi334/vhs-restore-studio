import json
import subprocess
from pathlib import Path

import pytest

from vhs_restore.analysis.ffprobe import probe_source
from vhs_restore.analysis.interlace import InterlaceAnalysis
from vhs_restore.analysis.source_info import SourceInfo, save_analysis_json


def test_probe_source_parses_video_metadata_and_preserves_a_path_with_special_chars(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    source = tmp_path / "日本語 clip (raw) [01].mkv"
    fixture = {
        "format": {
            "format_name": "matroska,webm",
            "format_long_name": "Matroska / WebM",
            "duration": "123.456",
            "size": "987654",
            "bit_rate": "64000",
            "tags": {"ENCODER": "fixture"},
        },
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "ffv1",
                "width": 720,
                "height": 480,
                "pix_fmt": "yuv422p10le",
                "avg_frame_rate": "30000/1001",
                "field_order": "tt",
                "tags": {"title": "VHS source"},
            },
            {"index": 1, "codec_type": "audio", "codec_name": "flac"},
        ],
    }
    calls: list[list[str]] = []

    def fake_run_command(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(
            argv,
            0,
            json.dumps(fixture),
            "ffprobe diagnostic: ignored when JSON is valid",
        )

    monkeypatch.setattr("vhs_restore.analysis.ffprobe.run_command", fake_run_command)

    info = probe_source(source)

    assert calls == [
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(source),
        ]
    ]
    assert info.path == source
    assert info.duration == pytest.approx(123.456)
    assert info.width == 720
    assert info.height == 480
    assert info.frame_rate == pytest.approx(30000 / 1001)
    assert info.field_order == "tt"
    assert info.codec_name == "ffv1"
    assert info.pixel_format == "yuv422p10le"
    assert info.format_name == "matroska,webm"
    assert info.size_bytes == 987654
    assert info.audio_streams == 1
    assert info.metadata["title"] == "VHS source"


def test_probe_source_raises_a_useful_error_for_a_failed_ffprobe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    source = tmp_path / "missing source.mkv"

    def fake_run_command(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 1, "", "No such file or directory")

    monkeypatch.setattr("vhs_restore.analysis.ffprobe.run_command", fake_run_command)

    with pytest.raises(RuntimeError, match="ffprobe failed"):
        probe_source(source)


def test_source_info_persists_json_without_overwriting_the_source(tmp_path: Path):
    source = tmp_path / "source.mkv"
    source.write_bytes(b"do not overwrite")
    info = SourceInfo(path=source, duration=12.5, width=720, height=480)
    destination = tmp_path / "analysis" / "source.analysis.json"

    save_analysis_json(info, destination)

    persisted = json.loads(destination.read_text(encoding="utf-8"))
    assert persisted["source_path"] == str(source)
    assert persisted["duration"] == 12.5
    assert source.read_bytes() == b"do not overwrite"


def test_source_info_refuses_the_source_path_as_the_analysis_destination(tmp_path: Path):
    source = tmp_path / "source.mkv"
    source.write_bytes(b"source")
    info = SourceInfo(path=source, duration=1.0)

    with pytest.raises(ValueError, match="source media"):
        save_analysis_json(info, source)


def test_source_info_refuses_a_hard_link_to_the_source_as_the_destination(
    tmp_path: Path,
):
    source = tmp_path / "source.mkv"
    destination = tmp_path / "source.analysis.json"
    source.write_bytes(b"source")
    try:
        destination.hardlink_to(source)
    except OSError as exc:
        pytest.skip(f"hard links unavailable: {exc}")

    info = SourceInfo(path=source, duration=1.0)

    with pytest.raises(ValueError, match="source media"):
        save_analysis_json(info, destination)

    assert source.read_bytes() == b"source"


def test_source_info_attaches_metadata_conflict_warnings_to_idet_analysis():
    info = SourceInfo(path=Path("source.mkv"), field_order="tt")
    idet = InterlaceAnalysis(classification="BFF", confidence=1.0)

    combined = info.with_interlace(idet)

    warnings = " ".join(combined.warnings).lower()
    assert "field order uncertain" in warnings
    assert "metadata unreliable" in warnings
