"""Progress events and cooperative cancellation primitives for jobs."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    """One observable job or stage progress update."""

    stage: str
    progress: float = 0.0
    message: str = ""
    status: str = "running"
    job_id: str | None = None
    completed: float | None = None
    total: float | None = None
    timestamp: float = field(default_factory=time.time)

    @property
    def fraction(self) -> float:
        """Alias for the normalized progress value."""

        return self.progress

    @property
    def percent(self) -> float:
        """Return progress as a percentage for simple GUI consumers."""

        return self.progress * 100.0

    @property
    def value(self) -> float:
        """Alias used by generic progress-bar adapters."""

        return self.progress


ProgressCallback = Callable[[ProgressEvent], object]


class ProgressReporter:
    """Create and dispatch progress events while retaining a local history."""

    def __init__(
        self,
        callback: ProgressCallback | None = None,
        *,
        job_id: str | None = None,
    ) -> None:
        self.callback = callback
        self.job_id = job_id
        self.events: list[ProgressEvent] = []

    def emit(
        self,
        stage: str,
        progress: float = 0.0,
        message: str = "",
        *,
        status: str = "running",
        completed: float | None = None,
        total: float | None = None,
    ) -> ProgressEvent:
        event = ProgressEvent(
            stage=str(stage),
            progress=max(0.0, min(1.0, float(progress))),
            message=str(message),
            status=str(status),
            job_id=self.job_id,
            completed=completed,
            total=total,
        )
        self.events.append(event)
        if self.callback is not None:
            self.callback(event)
        return event

    def __call__(self, event: ProgressEvent) -> ProgressEvent:
        self.events.append(event)
        if self.callback is not None:
            self.callback(event)
        return event


class CancellationToken:
    """Thread-safe cooperative cancellation flag for callers and runners."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def cancelled(self) -> bool:
        return self.is_cancelled()

    def wait(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout)

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled():
            raise RuntimeError("job cancellation requested")


__all__ = ["CancellationToken", "ProgressCallback", "ProgressEvent", "ProgressReporter"]
