# VHS Restore Studio

VHS Restore Studio is a Windows-local PySide6 application for fidelity-first
restoration of USB-captured VHS footage. It keeps the workflow fully local and
free/OSS, uses Vulkan-first optional AI backends, and has no CUDA-required path.

## Features

- Drag and drop a source video from Windows Explorer.
- Inspect source metadata with `ffprobe` and sample interlace mode with `idet`.
- Choose the `natural`, `balanced_ai`, `strong_ai`, `dvd`, or `archive` preset.
- Render a 10-second preview before starting a full restore.
- Track progress and cancel a running job without overwriting the source.
- Export an archive-quality file or DVD-compatible 720x480 output.
- Use the same `vhs_restore.pipeline.pipeline.build_pipeline` for preview and
  full restoration, so the preview reflects the selected full-run processing.

## Setup

From PowerShell in this directory:

```powershell
.\setup.ps1
```

The script creates `.venv`, installs the project in editable mode with its
development tools, and runs the optional backend bootstrap.

To refresh optional Video2X, Real-ESRGAN, and QTGMC components without
re-running the full setup:

```powershell
.\install.ps1
```

## Launch the GUI

Run the PowerShell launcher:

```powershell
.\run.ps1
```

After setup, the module and console entry points are also available:

```powershell
python -m vhs_restore
vhs-restore
```

The GUI accepts dropped source files, displays analysis and dependency
diagnostics, and provides preset selection, preview, restore, progress, and
cancel controls.

## Diagnose the local toolchain

```powershell
.\doctor.ps1
```

The diagnostics command checks the required Python/FFmpeg tools and reports
optional QTGMC and Vulkan AI backends. Missing optional components do not make
the GUI unusable.

## Safety and processing defaults

- Processing order is **Analyze → Restore at native resolution → optional AI
  upscale → Final geometry/aspect → Encode**. Restore does not pre-scale to
  1440x1080 before Video2X.
- Source media is never overwritten; completed and partial outputs use
  separate paths.
- 4:3 source material is preserved. In the post-AI (or AI-off) final geometry
  stage, archive output is scaled to 1440x1080 (4:3), while DVD output remains
  720x480; neither is stretched to 16:9.
- Japanese characters, spaces, parentheses, and brackets in paths are
  supported.
- Preview and full restoration use one shared pipeline builder.
- Processing is local-only: no cloud APIs or uploads are required.
- Optional AI is Vulkan-first for compatible local hardware and never requires
  CUDA. Natural restoration works without AI.

## Known issues and optional backends

- Optional installs from `install.ps1` and setup bootstrap are best-effort.
  Missing `vspipe`/QTGMC, `video2x`, or `realesrgan-ncnn-vulkan` still falls
  back to `bwdif` and the classical scaler.
- FFmpeg/ffprobe are resolved from PATH (for example WinGet Gyan). They are
  not installed into `.venv`.
- Real-ESRGAN is an image CLI and is not used for video processing.

See `versions.json` for the initial dependency/version record and
`THIRD_PARTY_LICENSES.md` for the third-party license register.
