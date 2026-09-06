"""Local subprocess helpers with explicit process lifecycle control."""

from __future__ import annotations

import csv
import io
import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from subprocess import CompletedProcess


_OUTPUT_ENCODING = "utf-8"


class ProcessTreeTerminationError(RuntimeError):
    """Raised when a live process tree cannot be terminated."""


def _windows_pid_exists(pid: int) -> bool:
    """Return whether Windows still reports ``pid`` as a running process."""

    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            check=False,
            capture_output=True,
            text=True,
            encoding=_OUTPUT_ENCODING,
            errors="replace",
            shell=False,
        )
    except OSError as exc:
        raise ProcessTreeTerminationError(
            f"could not verify whether process {pid} is still running"
        ) from exc

    if result.returncode != 0:
        return False

    for row in csv.reader(io.StringIO(result.stdout or "")):
        if len(row) > 1 and row[1].strip() == str(pid):
            return True
    return False


def kill_process_tree(pid: int) -> None:
    """Terminate a process and its descendants using local OS facilities.

    A missing PID is treated as already terminated.  Windows failures are
    surfaced when ``taskkill`` fails and ``tasklist`` confirms the PID remains
    live, so callers cannot mistake a rejected cancellation for success.
    """

    if pid <= 0:
        raise ValueError("pid must be positive")

    if os.name == "nt":
        try:
            result = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                check=False,
                capture_output=True,
                text=True,
                encoding=_OUTPUT_ENCODING,
                errors="replace",
                shell=False,
            )
        except OSError as exc:
            raise ProcessTreeTerminationError(
                f"could not run taskkill for process {pid}"
            ) from exc

        if result.returncode == 0:
            return
        if not _windows_pid_exists(pid):
            return

        detail = (result.stderr or result.stdout or "").strip()
        raise ProcessTreeTerminationError(
            f"taskkill failed for live process tree {pid}"
            + (f": {detail}" if detail else "")
        )

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError as exc:
        raise ProcessTreeTerminationError(
            f"permission denied while terminating process {pid}"
        ) from exc


class ManagedProcess:
    """A running argv-based command with streamed output and cancellation."""

    def __init__(
        self,
        process: subprocess.Popen[str],
        argv: list[str],
        on_output: Callable[[str], object] | None,
    ) -> None:
        self._process = process
        self._argv = argv
        self._on_output = on_output
        self._output: list[str] = []
        self._callback_error: BaseException | None = None
        self._termination_error: BaseException | None = None
        self._reader = threading.Thread(
            target=self._read_output,
            name=f"vhs-restore-process-{process.pid}",
            daemon=True,
        )
        self._reader.start()

    @property
    def pid(self) -> int:
        """Return the operating-system PID of the spawned process."""

        return self._process.pid

    @property
    def returncode(self) -> int | None:
        """Return the current process return code, if it has exited."""

        return self._process.poll()

    def _read_output(self) -> None:
        stream = self._process.stdout
        if stream is None:
            return

        callback_error: BaseException | None = None
        try:
            for raw_line in stream:
                self._output.append(raw_line)
                if self._on_output is not None:
                    try:
                        self._on_output(raw_line.rstrip("\r\n"))
                    except BaseException as exc:
                        callback_error = exc
                        break
        finally:
            stream.close()

        if callback_error is None:
            return

        self._callback_error = callback_error
        try:
            kill_process_tree(self.pid)
        except BaseException as exc:
            self._termination_error = exc

        try:
            self._process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait()

    def _completed(self) -> CompletedProcess[str]:
        return CompletedProcess(
            args=self._argv,
            returncode=self._process.returncode,
            stdout="".join(self._output),
            stderr=None,
        )

    def wait(self, timeout: float | None = None) -> CompletedProcess[str]:
        """Wait for completion and return a ``CompletedProcess`` result."""

        deadline = None if timeout is None else time.monotonic() + timeout
        self._process.wait(timeout=timeout)

        remaining = None if deadline is None else max(0, deadline - time.monotonic())
        self._reader.join(timeout=remaining)
        if self._reader.is_alive():
            raise subprocess.TimeoutExpired(self._argv, timeout)

        if self._termination_error is not None:
            raise self._termination_error
        if self._callback_error is not None:
            raise self._callback_error
        return self._completed()

    def kill(self) -> None:
        """Terminate this process and its descendants."""

        kill_process_tree(self.pid)


def start_command(
    argv: list[str],
    *,
    cwd: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    on_output: Callable[[str], object] | None = None,
) -> ManagedProcess:
    """Start an argv-based command and return it without waiting."""

    if not argv:
        raise ValueError("argv must contain an executable")

    command_argv = list(argv)
    process = subprocess.Popen(
        command_argv,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding=_OUTPUT_ENCODING,
        errors="replace",
        bufsize=1,
        shell=False,
    )
    return ManagedProcess(process, command_argv, on_output)


def run_command(
    argv: list[str],
    *,
    cwd: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    on_output: Callable[[str], object] | None = None,
) -> CompletedProcess[str]:
    """Run a local command from an argument list and wait for completion.

    ``on_output`` receives each output line without its line ending.  The
    returned ``CompletedProcess.stdout`` retains the original line endings;
    stderr is merged into stdout so callers see tool diagnostics in order.
    """

    return start_command(argv, cwd=cwd, env=env, on_output=on_output).wait()
