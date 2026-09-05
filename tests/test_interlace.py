import subprocess
from pathlib import Path

import pytest

from vhs_restore.analysis.interlace import analyze_interlace


def _idet_output(*, tff: int, bff: int, progressive: int, undetermined: int = 0) -> str:
    return (
        "[Parsed_idet_0 @ 0x1] Multi frame detection: "
        f"TFF: {tff} BFF: {bff} Progressive: {progressive} "
        f"Undetermined: {undetermined}\n"
    )


@pytest.mark.parametrize(
    ("label", "counts"),
    [
        ("TFF", (dict(tff=20, bff=0, progressive=0),) * 3),
        ("BFF", (dict(tff=0, bff=20, progressive=0),) * 3),
        ("Progressive", (dict(tff=0, bff=0, progressive=20),) * 3),
    ],
)
def test_analyze_interlace_classifies_consistent_samples_and_samples_15_50_85_percent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    label: str,
    counts: tuple[dict[str, int], ...],
):
    source = tmp_path / "日本語 source (raw) [01].avi"
    calls: list[list[str]] = []
    outputs = iter(_idet_output(**sample) for sample in counts)

    def fake_run_command(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, next(outputs), "")

    monkeypatch.setattr("vhs_restore.analysis.interlace.run_command", fake_run_command)

    analysis = analyze_interlace(source, duration=100.0)

    assert analysis.classification == label
    assert len(analysis.samples) == 3
    assert [sample.position for sample in analysis.samples] == pytest.approx(
        [0.15, 0.50, 0.85]
    )
    assert [float(argv[argv.index("-ss") + 1]) for argv in calls] == pytest.approx(
        [15.0, 50.0, 85.0]
    )
    assert all(str(source) in argv for argv in calls)
    assert analysis.confidence == pytest.approx(1.0)


def test_analyze_interlace_classifies_field_order_changes_as_mixed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    outputs = iter(
        [
            _idet_output(tff=20, bff=0, progressive=0),
            _idet_output(tff=0, bff=20, progressive=0),
            _idet_output(tff=20, bff=0, progressive=0),
        ]
    )

    def fake_run_command(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, next(outputs), "")

    monkeypatch.setattr("vhs_restore.analysis.interlace.run_command", fake_run_command)

    analysis = analyze_interlace(tmp_path / "mixed.mkv", duration=10.0)

    assert analysis.classification == "Mixed"
    assert 0.0 < analysis.confidence < 1.0
    assert any("mixed" in warning.lower() for warning in analysis.warnings)


def test_analyze_interlace_classifies_a_single_sample_with_both_field_orders_as_mixed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    output = _idet_output(tff=10, bff=10, progressive=0)

    def fake_run_command(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, output, "")

    monkeypatch.setattr("vhs_restore.analysis.interlace.run_command", fake_run_command)

    analysis = analyze_interlace(tmp_path / "same-sample-mixed.mkv", duration=10.0)

    assert analysis.classification == "Mixed"


def test_analyze_interlace_warns_when_metadata_conflicts_with_idet(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    output = _idet_output(tff=20, bff=0, progressive=0)

    def fake_run_command(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, output, "")

    monkeypatch.setattr("vhs_restore.analysis.interlace.run_command", fake_run_command)

    analysis = analyze_interlace(
        tmp_path / "progressive-tag.mkv",
        duration=10.0,
        metadata_field_order="progressive",
    )

    warnings = " ".join(analysis.warnings).lower()
    assert "field order uncertain" in warnings
    assert "metadata unreliable" in warnings


def test_analyze_interlace_returns_unknown_when_idet_has_no_detections(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    def fake_run_command(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr("vhs_restore.analysis.interlace.run_command", fake_run_command)

    analysis = analyze_interlace(tmp_path / "unknown.mkv", duration=0.0)

    assert analysis.classification == "Unknown"
    assert analysis.confidence == 0.0
    assert len(analysis.samples) == 3
