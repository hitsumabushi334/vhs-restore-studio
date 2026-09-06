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
        detail = (result.stderr or result.stdout or "").strip()
        raise ProcessTreeTerminationError(
            f"could not verify whether process {pid} is still running"
            + (f": {detail}" if detail else "")
        )

    for row in csv.reader(io.StringIO(result.stdout or "")):
        if len(row) > 1 and row[1].strip() == str(pid):
            return True
    return False


def _taskkill_reports_missing_process(result: CompletedProcess[str]) -> bool:
    """Return whether taskkill explicitly reports that the PID is gone."""

    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    normalized = output.casefold()
    return any(
        phrase in normalized
        for phrase in (
            "not found",
            "not running",
            "does not exist",
            "no running instance",
            "no such process",
        )
    )


def kill_process_tree(pid: int) -> None:
    """Terminate a process and its descendants using local OS facilities.

    A missing PID is treated as already terminated.  Windows failures are
    surfaced when ``taskkill`` fails and the PID cannot be verified as gone,
    so callers cannot mistake a rejected cancellation for success.
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
        if _taskkill_reports_missing_process(result):
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
        process: subprocess.Popen[object],
        argv: list[str],
        on_output: Callable[[str], object] | None,
        *,
        capture_output: bool = True,
    ) -> None:
        self._process = process
        self._argv = argv
        self._on_output = on_output
        self._output: list[str] = []
        self._callback_error: BaseException | None = None
        self._termination_error: BaseException | None = None
        self._reader: threading.Thread | None = None
        if capture_output:
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
    def stdout(self):
        """Return the child stdout stream for process pipelines."""

        return self._process.stdout

    @property
    def stderr(self):
        """Return the child stderr stream for process pipelines."""

        return self._process.stderr

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
                if isinstance(raw_line, bytes):
                    line = raw_line.decode(_OUTPUT_ENCODING, errors="replace")
                else:
                    line = raw_line
                self._output.append(line)
                if self._on_output is not None:
                    try:
                        self._on_output(line.rstrip("\r\n"))
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

        if self._reader is not None:
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
    stdin: object | None = None,
    stdout: object = subprocess.PIPE,
    stderr: object = subprocess.STDOUT,
    capture_output: bool = True,
    text: bool = True,
) -> ManagedProcess:
    """Start an argv-based command and return it without waiting."""

    if not argv:
        raise ValueError("argv must contain an executable")

    command_argv = list(argv)
    popen_kwargs: dict[str, object] = {
        "cwd": cwd,
        "env": env,
        "stdin": stdin,
        "stdout": stdout,
        "stderr": stderr,
        "shell": False,
    }
    if text:
        popen_kwargs.update(
            text=True,
            encoding=_OUTPUT_ENCODING,
            errors="replace",
            bufsize=1,
        )
    else:
        popen_kwargs.update(text=False, bufsize=0)
    process = subprocess.Popen(command_argv, **popen_kwargs)
    return ManagedProcess(process, command_argv, on_output, capture_output=capture_output)


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
