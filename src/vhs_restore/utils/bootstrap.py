"""Best-effort installation of optional local restoration backends."""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.request import urlretrieve

from .system import find_tool, vendor_root


@dataclass(frozen=True, slots=True)
class VendorPackage:
    name: str
    url: str
    dest: Path
    executable: str


def _vendor_packages() -> tuple[VendorPackage, ...]:
    root = vendor_root()
    return (
        VendorPackage(
            name="video2x",
            url="https://github.com/k4yt3x/video2x/releases/download/6.4.0/video2x-windows-amd64.zip",
            dest=root / "video2x",
            executable="video2x.exe",
        ),
        VendorPackage(
            name="realesrgan-ncnn-vulkan",
            url="https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan/releases/download/v0.2.0/realesrgan-ncnn-vulkan-v0.2.0-windows.zip",
            dest=root / "realesrgan-ncnn-vulkan",
            executable="realesrgan-ncnn-vulkan.exe",
        ),
    )


def _vapoursynth_package() -> VendorPackage:
    return VendorPackage(
        name="vapoursynth",
        url="https://github.com/vapoursynth/vapoursynth/releases/download/R79/VapourSynth64-Portable-R79.zip",
        dest=vendor_root() / "vapoursynth",
        executable="vspipe.exe",
    )


QTGMC_PIP_PACKAGES = ("vapoursynth", "vsrepo", "vsutil")
QTGMC_VSREPO_PLUGINS = (
    "ffms2",
    "mvtools",
    "nnedi3",
    "eedi3",
    "fmtconv",
    "rgvs",
    "dfttest",
    "addgrain",
)


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    urlretrieve(url, dest)


def _find_executable(root: Path, executable: str) -> Path | None:
    if not root.is_dir():
        return None

    direct = root / executable
    if direct.is_file():
        return direct

    for child in root.iterdir():
        if not child.is_dir():
            continue
        nested = child / executable
        if nested.is_file():
            return nested
    return None


def _is_safe_zip_member(name: str) -> bool:
    member = PurePosixPath(name.replace("\\", "/"))
    if member.is_absolute():
        return False
    return ".." not in member.parts


def _extract_zip(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as archive_file:
        for member in archive_file.infolist():
            if not _is_safe_zip_member(member.filename):
                raise ValueError(f"unsafe zip member: {member.filename}")
            archive_file.extract(member, destination)


def _run_command(args: list[str], *, label: str) -> bool:
    try:
        completed = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        print(f"[FAIL]    {label}: {exc}")
        return False

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        if detail:
            detail = detail.splitlines()[-1]
            print(f"[FAIL]    {label}: {detail}")
        else:
            print(f"[FAIL]    {label}: exit code {completed.returncode}")
        return False

    print(f"[OK]      {label}")
    return True


def _install_vendor_package(package: VendorPackage) -> bool:
    existing = _find_executable(package.dest, package.executable)
    if existing is not None:
        print(f"[SKIP]    {package.name}: already present at {existing}")
        return True

    package.dest.mkdir(parents=True, exist_ok=True)
    archive_path = package.dest / f"{package.name}.download.zip"
    try:
        print(f"[FETCH]   {package.name}: {package.url}")
        _download(package.url, archive_path)
        _extract_zip(archive_path, package.dest)
    except Exception as exc:  # noqa: BLE001 - optional installs must not abort setup
        print(f"[FAIL]    {package.name}: {exc}")
        return False
    finally:
        archive_path.unlink(missing_ok=True)

    installed = _find_executable(package.dest, package.executable)
    if installed is None:
        print(f"[FAIL]    {package.name}: {package.executable} not found after extraction")
        return False

    print(f"[OK]      {package.name}: installed at {installed}")
    return True


def _find_vspipe() -> Path | None:
    return find_tool("vspipe")



def _havsfunc_exposes_qtgmc() -> bool:
    try:
        import importlib
        sys.modules.pop("havsfunc", None)
        importlib.invalidate_caches()
        module = importlib.import_module("havsfunc")
        return callable(getattr(module, "QTGMC", None))
    except Exception:
        return False


def _unshadow_qtgmc_havsfunc(vsrepo_cmd: list[str]) -> None:
    if _havsfunc_exposes_qtgmc():
        return
    print("[WARN]    pip havsfunc has no QTGMC; removing it so vsrepo havsfunc can load")
    _run_command(
        [sys.executable, "-m", "pip", "uninstall", "-y", "havsfunc"],
        label="pip uninstall conflicting havsfunc",
    )
    site_packages = Path(sys.executable).resolve().parent.parent / "Lib" / "site-packages"
    leftover = site_packages / "havsfunc"
    if leftover.is_dir():
        shutil.rmtree(leftover, ignore_errors=True)
    _run_command(
        [*vsrepo_cmd, "install", "havsfunc"],
        label="vsrepo reinstall havsfunc with QTGMC",
    )
    if _havsfunc_exposes_qtgmc():
        print("[OK]      havsfunc.QTGMC is importable")
    else:
        print("[WARN]    havsfunc.QTGMC is still unavailable; pipeline will use bwdif")


def _install_qtgmc_stack() -> bool:
    print("[QTGMC]   installing optional VapourSynth/QTGMC stack (best effort)")
    ok = True
    vapoursynth_package = _vapoursynth_package()

    pip_args = [sys.executable, "-m", "pip", "install", *QTGMC_PIP_PACKAGES]
    if not _run_command(pip_args, label="pip install QTGMC Python packages"):
        ok = False

    if not _run_command(
        [sys.executable, "-m", "vapoursynth", "config"],
        label="vapoursynth config",
    ):
        ok = False

    vsrepo = Path(sys.executable).resolve().parent / "vsrepo.exe"
    if not vsrepo.is_file():
        vsrepo = Path(sys.executable).resolve().parent / "vsrepo"
    if vsrepo.is_file():
        vsrepo_cmd = [str(vsrepo)]
    else:
        vsrepo_cmd = [sys.executable, "-m", "vsrepo"]
    if not _run_command([*vsrepo_cmd, "update"], label="vsrepo update"):
        ok = False
    if not _run_command(
        [*vsrepo_cmd, "install", "havsfunc", *QTGMC_VSREPO_PLUGINS],
        label="vsrepo install QTGMC plugins",
    ):
        ok = False

    # PyPI havsfunc (v34+) is a different package and shadows vsrepo's QTGMC module.
    _unshadow_qtgmc_havsfunc(vsrepo_cmd)

    if _find_vspipe() is None:
        print("[WARN]    vspipe missing; attempting portable VapourSynth R79 download")
        if not _install_vendor_package(vapoursynth_package):
            ok = False
        elif _find_vspipe() is None:
            print("[FAIL]    vspipe still missing after portable VapourSynth install")
            ok = False
        else:
            portable_vsrepo = _find_executable(vapoursynth_package.dest, "vsrepo.exe")
            if portable_vsrepo is not None:
                _run_command(
                    [str(portable_vsrepo), "install", *QTGMC_VSREPO_PLUGINS],
                    label="portable vsrepo install QTGMC plugins",
                )

    if _find_vspipe() is None:
        print("[WARN]    QTGMC unavailable; pipeline will use bwdif fallback")
        return False

    print(f"[OK]      QTGMC runtime available at {_find_vspipe()}")
    return ok


def main() -> int:
    """Install optional vendor tools and QTGMC support without aborting setup."""

    vendor_root().mkdir(parents=True, exist_ok=True)

    for package in _vendor_packages():
        _install_vendor_package(package)

    _install_qtgmc_stack()
    print("Optional backend bootstrap finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
