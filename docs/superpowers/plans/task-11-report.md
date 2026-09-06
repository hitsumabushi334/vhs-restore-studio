# Task 11 report: synthetic end-to-end verification

- Status: Complete. Independent reviewers found no remaining P0/P1 after follow-up fixes.
- Coverage: synthetic E2E (TFF/BFF, 59.94p, Japanese/space paths, audio, cancel, DVD, preview==full), process-tree verification, QTGMC vspipe→ffmpeg pipe with audio map and preview trim.
- Verification: 141 passed, 1 skipped. GUI offscreen MainWindow smoke OK.
- Residual P2: VSPipe stderr is not included in JobError text.
