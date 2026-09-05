# VHS Restore Studio Design

Date: 2026-09-05
Status: Draft for user review
Project root (runtime): `C:\Users\issho\vhs-restore-studio`
Spec mirror (writable vault): this file

## 1. Goal

Build a Windows-local GUI app that restores USB-captured VHS footage with a fidelity-first pipeline:

source analysis → interlace decision → deinterlace → VHS restoration → optional AI upscale → color/aspect handling → archive/DVD export.

Do not invent heavy nonexistent detail by default. Prefer natural preservation of residual VHS information. Fully local, free/OSS only, Vulkan-first for AMD RX 7900 XT. No CUDA-required path.

## 2. Scope / Non-goals

In scope:
- PySide6 GUI with drag/drop, presets, advanced settings, preview, progress, cancel
- FFprobe + FFmpeg idet multi-point analysis
- QTGMC-first deinterlace with bwdif fallback
- Temporal/chroma restoration modules
- Upscale backends: Video2X, Real-ESRGAN ncnn Vulkan, classical scaler
- Archive HQ / Practical / Compatibility / DVD exports
- Job manifest cache/resume, logs, reproducibility sidecars
- setup.ps1 / run.ps1 / doctor.ps1

Out of scope for MVP:
- DVD ISO burning / authoring UI
- Cloud / paid APIs / Topaz
- Default RIFE / GFPGAN / forced face restoration
- Full-frame PNG dump workflows

## 3. Architecture

Pipeline-first shared builder. Preview and full restore call the same `build_pipeline(settings)`; only start/duration/output differ.

```text
GUI (PySide6)
  └─ Controller
       ├─ Analysis (ffprobe, idet)
       ├─ Pipeline builder (shared)
       │    ├─ deinterlace / denoise / chroma / color
       │    ├─ upscale backend interface
       │    └─ encode profiles
       ├─ Jobs (manifest, cache, progress, cancel)
       └─ Diagnostics (dependency/GPU detection)
```

Key packages under `src/vhs_restore/`:
- `gui/` main window, preview, settings, diagnostics
- `analysis/` ffprobe, interlace, source_info
- `pipeline/` restore stages + encode
- `upscale/` backend abstraction
- `jobs/` manifest/cache/progress
- `utils/` process/paths/logging/system

## 4. Dependency strategy

Detect first; attempt official downloads in setup; degrade gracefully.

Pinned candidates to verify during setup (record final pins in `versions.json`):
- FFmpeg: already present (8.1.1-full Gyan)
- Video2X: official `k4yt3x/video2x` release 6.4.0
- Real-ESRGAN ncnn Vulkan: xinntao release v0.2.0
- VapourSynth: current Windows installer from official docs
- QTGMC via maintained havsfunc / required VS plugins

If QTGMC unavailable → FFmpeg `bwdif` fallback, GUI warns.
If AI backends unavailable → AI controls disabled, status `AI backend unavailable`, Natural/classical paths still work.

External tools are invoked as CLIs with argument lists (`subprocess` list form). No `shell=True`, no path mangling of Japanese characters.

## 5. Analysis & deinterlace rules

On load:
1. FFprobe metadata JSON
2. FFmpeg idet samples near 15% / 50% / 85%
3. Classify Progressive / TFF / BFF / Mixed / Unknown with confidence
4. Warn on metadata vs idet conflict (`Field order uncertain` / `metadata unreliable`)

Cases:
- 29.97i → QTGMC double-rate → 59.94p
- already 59.94p clean → deinterlace OFF
- progressive flag + combing → warn, allow manual override (Auto/TFF/BFF/Progressive)

QTGMC presets abstracted as Fast / Balanced / High / Very High.

## 6. Restoration order

decode → deinterlace → temporal/chroma restoration → light artifact removal → optional AI upscale → resize/aspect → color/output conversion → optional light final sharpen

Defaults stay weak-to-moderate. Stabilization default OFF. RIFE experimental advanced-only, default OFF.

Aspect: preserve 4:3. Archive 1080 path targets 1440×1080 SAR 1:1. Optional 1920×1080 pillarbox only when requested. No 4:3→16:9 stretch.

Color: respect input tags; SD NTSC missing tags may assume BT.601/SMPTE 170M candidate; convert properly for HD (prefer zscale), do not blindly retag.

## 7. GUI / presets / outputs

Main UI: input, analysis summary, restore preset, key sliders/toggles, preview position + 10s preview, output profile, start/cancel, stage progress.

Restore presets (JSON data, not hard-coded logic): Natural, Balanced AI (recommended), Strong AI (Japanese hallucination warning), DVD, Custom.

Output profiles:
- Archive HQ: MKV + FFV1 + FLAC/PCM (size warning)
- Archive Practical: 1440×1080 59.94p H.264/H.265 high quality
- Compatibility: MP4 H.264 AAC
- DVD: 720×480 MPEG-2 + AC-3, proper 59.94p→29.97i field cadence, DVD-5/9 bitrate planner

## 8. Jobs, safety, reproducibility

- Never overwrite source; safe unique output names
- Intermediate videos under `temp/` (lossless/visually-lossless), never mass PNG dumps
- Preflight free-space vs estimate
- Manifest/settings hash resume; reject corrupt intermediates
- Cancel kills process tree; incomplete outputs stay `.partial` and are not presented as final
- Logs under `logs/`; emit `output.settings.json` + `output.log`

## 9. Testing / acceptance focus

Must cover: TFF/BFF 29.97i→59.94p, no double deinterlace on 59.94p, Japanese/space paths, AI-absent Natural path, Vulkan path when present, cancel cleanup, audio sync, preview==full settings.

Acceptance mirrors the instruction checklist: GUI launch, analysis, restore/export paths, 4:3 preservation, progress/cancel/logs, source untouched.

## 10. Implementation order

1. Env/docs pin check
2. Skeleton + scripts
3. Analyzer + idet
4. Shared FFmpeg/VS pipeline + preview
5. GUI shell
6. Upscale backends
7. Presets/export/DVD bitrate
8. Cache/resume/error handling
9. Tests + smoke verification
10. README / licenses / final report

Coordinator/implementers: `gpt-5.6-luna` (xhigh/max). High-risk review: `gpt-5.6-sol`. Requested `cursor/kimi-k3` is unavailable on this spawn allowlist.

## Spec self-review notes

- No TBD left for MVP boundaries
- Architecture matches pipeline-first choice
- Dependency bootstrap explicitly degrades instead of hard-failing app launch
- Temp/output default under project, overridable in settings
