import pytest

from pathlib import Path

from vhs_restore.utils.paths import safe_output_path


def test_safe_output_path_preserves_japanese_spaces_and_avoids_existing_file(
    tmp_path: Path,
):
    output_dir = tmp_path / "日本語 output (raw) [A]"
    output_dir.mkdir()
    desired = output_dir / "保存済み VHS (テスト) [01].mp4"
    desired.write_bytes(b"source")

    candidate = safe_output_path(desired)

    assert candidate == output_dir / "保存済み VHS (テスト) [01] (1).mp4"
    assert candidate != desired
    assert not candidate.exists()


def test_safe_output_path_increments_until_a_unique_name_is_available(
    tmp_path: Path,
):
    desired = tmp_path / "clip.mp4"
    desired.write_bytes(b"0")
    (tmp_path / "clip (1).mp4").write_bytes(b"1")

    assert safe_output_path(desired) == tmp_path / "clip (2).mp4"


def test_safe_output_path_treats_a_symlink_as_occupied(tmp_path: Path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    desired = tmp_path / "日本語 link.mp4"

    try:
        desired.symlink_to(source)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    assert safe_output_path(desired) == tmp_path / "日本語 link (1).mp4"
