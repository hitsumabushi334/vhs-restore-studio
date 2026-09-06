# Task 11 report: synthetic end-to-end verification

- Status: Complete after independent review fixes.
- Files: `tests/fixtures/media.py`, `tests/test_e2e_synthetic.py`, `README.md`, `src/vhs_restore/utils/process.py`, `tests/test_process.py`, `src/vhs_restore/pipeline/deinterlace.py`, `tests/test_deinterlace_decision.py`, `docs/superpowers/plans/HANDOFF-2026-09-06.md`.
- Coverage: 29.97i TFF/BFF, 59.94p without fps-only skip of TFF/BFF, Mixed skip only with progressive metadata, Japanese/space paths, source unchanged, preview/full shared `build_pipeline`, cancel leaves `.partial` only, audio vs video stream duration, DVD 720x480 4:3, source SAR 8/9 → archive 1440x1080 4:3.
- Process: `taskkill` “not found” is a no-op; `tasklist` Access denied after a failed kill is an error (does not report cancel success).
- Verification: 132 passed, 1 skipped (Windows process-tree sleep preflight skip in sandbox).
- Known issues remain in README (`doctor.ps1` ffmpeg `--version`, optional QTGMC/AI backends).
