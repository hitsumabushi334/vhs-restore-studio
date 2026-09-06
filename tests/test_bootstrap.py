import io
import zipfile
from pathlib import Path

import pytest

from vhs_restore.utils import bootstrap


def _make_zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def _install_zip(download_url: str, archive_path: Path) -> None:
    if "video2x" in download_url:
        payload = _make_zip_bytes({"video2x/video2x.exe": b"video2x"})
    elif "realesrgan" in download_url:
        payload = _make_zip_bytes(
            {"realesrgan-ncnn-vulkan/realesrgan-ncnn-vulkan.exe": b"realesrgan"}
        )
    else:
        payload = _make_zip_bytes({"vspipe.exe": b"vspipe"})
    archive_path.write_bytes(payload)


@pytest.fixture
def vendor_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("VHS_RESTORE_VENDOR", str(tmp_path / "vendor"))
    return tmp_path / "vendor"


def test_bootstrap_installs_video2x_and_realesrgan_from_mocked_zip(
    vendor_tree: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(bootstrap, "_download", _install_zip)
    monkeypatch.setattr(bootstrap, "_install_qtgmc_stack", lambda: True)

    assert bootstrap.main() == 0

    video2x_exe = bootstrap._find_executable(vendor_tree / "video2x", "video2x.exe")
    realesrgan_exe = bootstrap._find_executable(
        vendor_tree / "realesrgan-ncnn-vulkan",
        "realesrgan-ncnn-vulkan.exe",
    )
    assert video2x_exe is not None and video2x_exe.is_file()
    assert realesrgan_exe is not None and realesrgan_exe.is_file()


def test_bootstrap_skips_when_executable_already_exists(
    vendor_tree: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    existing = vendor_tree / "video2x" / "video2x.exe"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"existing")

    calls: list[str] = []

    def _download(url: str, dest: Path) -> None:
        calls.append(url)

    monkeypatch.setattr(bootstrap, "_download", _download)
    monkeypatch.setattr(bootstrap, "_install_qtgmc_stack", lambda: True)

    assert bootstrap.main() == 0
    assert not any("video2x" in url for url in calls)


def test_bootstrap_download_error_does_not_raise(
    vendor_tree: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    def _download(_url: str, _dest: Path) -> None:
        raise OSError("network unavailable")

    monkeypatch.setattr(bootstrap, "_download", _download)
    monkeypatch.setattr(bootstrap, "_install_qtgmc_stack", lambda: True)

    assert bootstrap.main() == 0


def test_extract_zip_rejects_zip_slip(tmp_path: Path):
    archive_path = tmp_path / "unsafe.zip"
    archive_path.write_bytes(
        _make_zip_bytes({"../escape.exe": b"bad"})
    )

    with pytest.raises(ValueError, match="unsafe zip member"):
        bootstrap._extract_zip(archive_path, tmp_path / "out")
