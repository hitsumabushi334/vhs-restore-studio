# VHS Restore Studio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Windows-local PySide6 app that restores USB-captured VHS footage with a fidelity-first shared pipeline (analysis → deinterlace → VHS restore → optional AI upscale → archive/DVD export).

**Architecture:** Pipeline-first shared `build_pipeline(settings)`. GUI/controller call the same builder for preview and full restore. External tools (FFmpeg, vspipe/QTGMC, Video2X, Real-ESRGAN) are detected/optional backends invoked via argument-list subprocesses. AI/QTGMC absence degrades gracefully.

**Tech Stack:** Python 3.12+, PySide6, FFmpeg/ffprobe, VapourSynth+QTGMC (optional), Video2X 6.4.0 / Real-ESRGAN ncnn Vulkan v0.2.0 (optional), pytest, PowerShell setup scripts.

**Spec:** `docs/superpowers/specs/2026-09-05-vhs-restore-studio-design.md` (mirror under Obsidian projects; runtime root `C:\Users\issho\vhs-restore-studio`)

## Global Constraints

- Fully local OSS only; no cloud/paid APIs/Topaz; no CUDA-required path; Vulkan-first for AMD RX 7900 XT
- Never overwrite source; never stretch 4:3→16:9; never force deinterlace before analysis; never default RIFE/GFPGAN/heavy hallucination
- No full-frame PNG dumps; intermediates are video under `temp/`
- Japanese/space/`()`/`[]` paths must work; use `pathlib.Path` + `subprocess` argument lists (no `shell=True`)
- Preview and full restore must share identical filter settings via one pipeline builder
- App must launch even when AI/QTGMC missing; show `AI backend unavailable` / QTGMC fallback warning
- Pin detected versions into `versions.json`; record third-party licenses
- Controller: `gpt-5.6-luna` xhigh; implementers: `gpt-5.6-luna` max; high-risk review: `gpt-5.6-sol` high; `cursor/kimi-k3` unavailable

---

### Task 1: Project skeleton, packaging, scripts

**Files:**
- Create: `C:\Users\issho\vhs-restore-studio\pyproject.toml`
- Create: `C:\Users\issho\vhs-restore-studio\README.md`
- Create: `C:\Users\issho\vhs-restore-studio\versions.json`
- Create: `C:\Users\issho\vhs-restore-studio\THIRD_PARTY_LICENSES.md`
- Create: `C:\Users\issho\vhs-restore-studio\setup.ps1`
- Create: `C:\Users\issho\vhs-restore-studio\run.ps1`
- Create: `C:\Users\issho\vhs-restore-studio\doctor.ps1`
- Create: `C:\Users\issho\vhs-restore-studio\src\vhs_restore\__init__.py`
- Create: `C:\Users\issho\vhs-restore-studio\src\vhs_restore\__main__.py`
- Create: `C:\Users\issho\vhs-restore-studio\presets\natural.json`
- Create: `C:\Users\issho\vhs-restore-studio\presets\balanced_ai.json`
- Create: `C:\Users\issho\vhs-restore-studio\presets\strong_ai.json`
- Create: `C:\Users\issho\vhs-restore-studio\presets\archive.json`
- Create: `C:\Users\issho\vhs-restore-studio\presets\dvd.json`
- Create: `C:\Users\issho\vhs-restore-studio\tests\test_package_imports.py`
- Create: dirs `logs/`, `temp/`, `output/`, `vendor/`

**Interfaces:**
- Consumes: none
- Produces: installable package `vhs_restore` with console/module entry `python -m vhs_restore`

- [ ] **Step 1: Write failing import test**
```python
from vhs_restore import __version__

def test_version_string():
    assert isinstance(__version__, str) and __version__
```
- [ ] **Step 2: Run test expecting fail** — `pytest tests/test_package_imports.py -v`
- [ ] **Step 3: Create package skeleton, pyproject, scripts, preset JSON stubs, versions.json**
- [ ] **Step 4: Create venv + install editable + pass import test**
- [ ] **Step 5: Commit** `feat: scaffold vhs-restore-studio package`

### Task 2: Path / process / logging utilities

**Files:**
- Create: `src/vhs_restore/utils/paths.py`
- Create: `src/vhs_restore/utils/process.py`
- Create: `src/vhs_restore/utils/logging.py`
- Create: `src/vhs_restore/utils/system.py`
- Create: `tests/test_paths.py`
- Create: `tests/test_process.py`

**Interfaces:**
- Produces:
  - `safe_output_path(desired: Path) -> Path`
  - `run_command(argv: list[str], *, cwd=None, env=None, on_output=None) -> CompletedProcess`
  - `kill_process_tree(pid: int) -> None`
  - `setup_job_logger(job_dir: Path) -> logging.Logger`

- [ ] **Step 1: Failing tests for Japanese/space unique output naming and argv-list process runner**
- [ ] **Step 2: Implement utilities (no shell=True)**
- [ ] **Step 3: Pass tests + commit** `feat: add path/process/logging utilities`

### Task 3: Dependency diagnostics

**Files:**
- Create: `src/vhs_restore/utils/deps.py`
- Create: `tests/test_deps.py`
- Modify: `doctor.ps1`, `setup.ps1`

**Interfaces:**
- Produces: `DependencyReport` dataclass + `detect_dependencies() -> DependencyReport`

- [ ] **Step 1: Tests for missing AI backend reporting and ffmpeg detection**
- [ ] **Step 2: Implement detector; wire doctor.ps1**
- [ ] **Step 3: Commit** `feat: dependency diagnostics`

### Task 4: Source analysis (ffprobe + idet)

**Files:**
- Create: `src/vhs_restore/analysis/ffprobe.py`
- Create: `src/vhs_restore/analysis/interlace.py`
- Create: `src/vhs_restore/analysis/source_info.py`
- Create: `tests/test_ffprobe.py`
- Create: `tests/test_interlace.py`

**Interfaces:**
- Produces:
  - `probe_source(path: Path) -> SourceInfo`
  - `analyze_interlace(path: Path, duration: float) -> InterlaceAnalysis` sampling 15/50/85%

- [ ] **Step 1: Unit tests with fixture JSON / mocked ffmpeg idet output for TFF/BFF/progressive/mixed**
- [ ] **Step 2: Implement analyzers; persist analysis JSON**
- [ ] **Step 3: Commit** `feat: ffprobe and multi-point idet analysis`

### Task 5: Settings model + preset loader + validation

**Files:**
- Create: `src/vhs_restore/settings.py`
- Create: `tests/test_settings.py`
- Modify: preset JSON files with full fields

**Interfaces:**
- Produces: `RestoreSettings` + `load_preset(name: str) -> RestoreSettings` + `validate_settings(settings, analysis) -> list[Warning]`

- [ ] **Step 1: Tests for Natural/Balanced AI defaults and over-processing warnings**
- [ ] **Step 2: Implement settings/presets/validation**
- [ ] **Step 3: Commit** `feat: restore settings and presets`

### Task 6: Shared pipeline builder + deinterlace/restore modules

**Files:**
- Create: `src/vhs_restore/pipeline/pipeline.py`
- Create: `src/vhs_restore/pipeline/deinterlace.py`
- Create: `src/vhs_restore/pipeline/denoise.py`
- Create: `src/vhs_restore/pipeline/chroma.py`
- Create: `src/vhs_restore/pipeline/color.py`
- Create: `src/vhs_restore/pipeline/restore.py`
- Create: `tests/test_pipeline_builder.py`
- Create: `tests/test_deinterlace_decision.py`

**Interfaces:**
- Produces: `build_pipeline(settings: RestoreSettings, analysis: SourceInfo, *, start=None, duration=None) -> PipelinePlan`
- Decision helpers must disable deinterlace for clean 59.94p and enable double-rate for 29.97i

- [ ] **Step 1: Tests for Case A/B/C deinterlace decisions and identical preview/full plan filters**
- [ ] **Step 2: Implement builder + stage modules with QTGMC script generation and bwdif fallback**
- [ ] **Step 3: Commit** `feat: shared restore pipeline builder`

### Task 7: Encode profiles + DVD bitrate planner

**Files:**
- Create: `src/vhs_restore/pipeline/encode.py`
- Create: `src/vhs_restore/pipeline/dvd.py`
- Create: `tests/test_encode_profiles.py`
- Create: `tests/test_dvd_bitrate.py`

**Interfaces:**
- Produces: `build_encode_args(profile, analysis, settings) -> list[str]` and `plan_dvd_video_bitrate(duration_s, disc='DVD-5'|'DVD-9') -> int`

- [ ] **Step 1: Tests for Archive/Compatibility/DVD args and bitrate math with overhead/safety margin**
- [ ] **Step 2: Implement encoders including 59.94p→29.97i field cadence for DVD**
- [ ] **Step 3: Commit** `feat: encode profiles and DVD bitrate planner`

### Task 8: Upscale backend abstraction

**Files:**
- Create: `src/vhs_restore/upscale/base.py`
- Create: `src/vhs_restore/upscale/video2x.py`
- Create: `src/vhs_restore/upscale/realesrgan.py`
- Create: `src/vhs_restore/upscale/classical.py`
- Create: `tests/test_upscale_backends.py`

**Interfaces:**
- Produces: `UpscaleBackend` protocol with `is_available()`, `upscale(input, output, scale, model)` and selector preferring Video2X → RealESRGAN → Classical

- [ ] **Step 1: Tests for selection order and unavailable AI degradation**
- [ ] **Step 2: Implement backends (CLI wrappers + classical FFmpeg scaler)**
- [ ] **Step 3: Commit** `feat: upscale backend abstraction`

### Task 9: Jobs (manifest/cache/progress/cancel) + restore runner

**Files:**
- Create: `src/vhs_restore/jobs/manifest.py`
- Create: `src/vhs_restore/jobs/cache.py`
- Create: `src/vhs_restore/jobs/progress.py`
- Create: `src/vhs_restore/jobs/runner.py`
- Create: `tests/test_manifest.py`
- Create: `tests/test_runner_cancel.py`

**Interfaces:**
- Produces: job manifest resume, progress events, cancel with process-tree kill and `.partial` outputs

- [ ] **Step 1: Tests for resume reuse and cancel cleanup**
- [ ] **Step 2: Implement runner integrating pipeline/upscale/encode + free-space preflight**
- [ ] **Step 3: Commit** `feat: job runner with cache resume and cancel`

### Task 10: GUI shell + diagnostics + preview controls

**Files:**
- Create: `src/vhs_restore/gui/main_window.py`
- Create: `src/vhs_restore/gui/preview.py`
- Create: `src/vhs_restore/gui/settings.py`
- Create: `src/vhs_restore/gui/diagnostics.py`
- Create: `tests/test_gui_smoke.py`

**Interfaces:**
- Consumes: analysis, settings, runner APIs
- Produces: launchable GUI with DnD, analysis panel, presets, preview 10s, progress/cancel, diagnostics

- [ ] **Step 1: Headless smoke test constructing MainWindow**
- [ ] **Step 2: Implement GUI wired to controller methods**
- [ ] **Step 3: Commit** `feat: PySide6 GUI shell`

### Task 11: End-to-end synthetic media tests + smoke verification

**Files:**
- Create: `tests/test_e2e_synthetic.py`
- Create: `tests/fixtures/` generator helpers
- Modify: `README.md` with run/doctor instructions

**Interfaces:**
- Produces: synthetic interlaced fixtures covering TFF/BFF/59.94p/Japanese path/audio sync/preview==full

- [ ] **Step 1: Generate fixtures via ffmpeg and write failing e2e expectations**
- [ ] **Step 2: Make Natural-path e2e pass without AI; verify cancel and source untouched**
- [ ] **Step 3: Run doctor.ps1 + GUI launch smoke; document Known Issues**
- [ ] **Step 4: Commit** `test: synthetic e2e and smoke verification`

---

## Self-review notes

- Spec coverage: analysis, deinterlace cases, pipeline sharing, backends, exports, jobs, GUI, scripts, licenses, Japanese paths covered by Tasks 1–11
- Deferred intentionally: wipe comparison polish, RIFE advanced UI, full VS plugin auto-install if official bootstrap blocked
- No TBD placeholders left for MVP deliverables
