"""Per-job UTF-8 logging."""

from __future__ import annotations

import logging
from pathlib import Path


def setup_job_logger(job_dir: Path) -> logging.Logger:
    """Create or reuse a logger writing to ``job_dir / 'job.log'``."""

    job_dir = Path(job_dir)
    job_dir.mkdir(parents=True, exist_ok=True)
    log_path = job_dir / "job.log"
    logger_name = f"vhs_restore.job.{job_dir.resolve()}"

    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    for handler in logger.handlers:
        if (
            getattr(handler, "_vhs_restore_job_handler", False)
            and isinstance(handler, logging.FileHandler)
            and Path(handler.baseFilename).resolve() == log_path.resolve()
        ):
            return logger

    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler._vhs_restore_job_handler = True  # type: ignore[attr-defined]
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )
    logger.addHandler(handler)
    return logger

