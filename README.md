# VHS Restore Studio

VHS Restore Studio is a Windows-local PySide6 application for fidelity-first
restoration of USB-captured VHS footage. The project is designed for a fully
local, free/OSS workflow with Vulkan-first optional AI backends and no
CUDA-required path.

The package and command-line entry points are scaffolded in Task 1. Analysis,
restoration, export, jobs, and the GUI are added in later tasks.

## Setup

From PowerShell in this directory:

```powershell
.\setup.ps1
```

The script creates `.venv` and installs the project in editable mode with its
development tools.

## Run and diagnose

```powershell
.\run.ps1
.\doctor.ps1
```

`python -m vhs_restore` is also available after setup. The doctor script checks
the local Python/FFmpeg toolchain and reports optional QTGMC and Vulkan AI
backends without making them hard requirements.

## Safety defaults

- Source media is never overwritten.
- Output and intermediate files stay under the project output/temp locations
  unless a later setting explicitly selects another location.
- 4:3 source material is preserved; the pipeline does not stretch it to 16:9.
- Japanese characters, spaces, parentheses, and brackets in paths are supported.
- Preview and full restoration use one shared pipeline builder.

See `versions.json` for the initial dependency/version record and
`THIRD_PARTY_LICENSES.md` for the third-party license register.
