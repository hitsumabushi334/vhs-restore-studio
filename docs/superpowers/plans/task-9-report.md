# Task 9 report: jobs and restore runner

- Status: Complete.
- Commit: `c95ba85` (jobs implementation).
- Files: `src/vhs_restore/jobs/manifest.py`, `cache.py`, `progress.py`, and `runner.py`; tests in `tests/test_manifest.py` and `tests/test_runner_cancel.py`.
- Result: Job manifests/cache support resume, progress events are emitted, and cancellation kills the process tree while preserving a `.partial` output and avoiding source overwrite.
