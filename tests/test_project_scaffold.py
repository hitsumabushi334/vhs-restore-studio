import json
import tomllib
from importlib import resources
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSIONS = {
    "python": "3.12.0",
    "setuptools": "78.1.0",
    "pyside6": "6.11.2",
    "pytest": "9.1.1",
    "ffmpeg": "8.1.1-full (Gyan)",
    "video2x": "6.4.0",
    "realesrgan-ncnn-vulkan": "v0.2.0",
    "vapoursynth": "R79",
}


def load_project() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_runtime_directories_are_tracked_with_placeholders():
    for directory in ("logs", "temp", "output", "vendor"):
        assert (ROOT / directory / ".gitkeep").is_file()


def test_versions_are_concrete_and_project_pins_match():
    versions = json.loads((ROOT / "versions.json").read_text(encoding="utf-8"))
    assert versions == EXPECTED_VERSIONS

    project = load_project()
    assert project["build-system"]["requires"] == ["setuptools==78.1.0"]
    assert project["project"]["requires-python"] == ">=3.12"
    assert project["project"]["dependencies"] == ["PySide6==6.11.2"]
    assert project["project"]["optional-dependencies"]["dev"] == ["pytest==9.1.1"]


def test_package_version_is_read_from_the_module():
    project = load_project()
    assert project["project"]["dynamic"] == ["version"]
    assert "version" not in project["project"]
    assert project["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "vhs_restore.__version__"
    }


def test_project_assets_are_declared_and_available_from_the_package():
    project = load_project()
    assert project["tool"]["setuptools"]["package-data"]["vhs_restore"] == [
        "assets/versions.json",
        "assets/presets/*.json",
    ]

    package_assets = resources.files("vhs_restore").joinpath("assets")
    packaged_versions = package_assets.joinpath("versions.json")
    assert packaged_versions.is_file()
    assert packaged_versions.read_text(encoding="utf-8") == (
        ROOT / "versions.json"
    ).read_text(encoding="utf-8")

    for preset in sorted((ROOT / "presets").glob("*.json")):
        packaged_preset = package_assets.joinpath("presets", preset.name)
        assert packaged_preset.is_file()
        assert packaged_preset.read_text(encoding="utf-8") == preset.read_text(
            encoding="utf-8"
        )


def test_setup_fallback_validates_python_version():
    setup_script = (ROOT / "setup.ps1").read_text(encoding="utf-8")
    assert "sys.version_info" in setup_script
    assert "3.12" in setup_script


def test_doctor_checks_project_venv_python():
    doctor_script = (ROOT / "doctor.ps1").read_text(encoding="utf-8")
    assert "$VenvPython = Join-Path" in doctor_script
    assert "Test-VenvPython" in doctor_script
    assert 'Test-Tool -Name "python"' not in doctor_script


def test_install_script_bootstraps_optional_backends():
    install_script = (ROOT / "install.ps1").read_text(encoding="utf-8")
    assert (ROOT / "install.ps1").is_file()
    assert "vhs_restore.utils.bootstrap" in install_script


def test_setup_script_runs_optional_bootstrap():
    setup_script = (ROOT / "setup.ps1").read_text(encoding="utf-8")
    assert "bootstrap" in setup_script or "install.ps1" in setup_script


