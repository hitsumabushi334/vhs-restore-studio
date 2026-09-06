# Task 11 report: synthetic end-to-end verification

- Status: Complete. Full suite: 127 passed, 1 skipped.
- Files: `tests/fixtures/media.py`, `tests/test_e2e_synthetic.py`, `README.md`, `src/vhs_restore/utils/process.py`, `tests/test_process.py`, `src/vhs_restore/pipeline/deinterlace.py`.
- Coverage: 29.97i TFF/BFF field order, 59.94p without double deinterlace, Japanese/space paths, source unchanged, preview/full shared `build_pipeline`, cancel leaves `.partial` only, audio duration, DVD 720x480 4:3, 1440x1080 4:3 restore.
- Process: `tasklist` Access denied is treated as "PID not confirmed live" so missing-PID kill is a no-op in restricted environments.
- Known issues remain documented in README (`doctor.ps1` ffmpeg `--version`, optional QTGMC/AI backends).
