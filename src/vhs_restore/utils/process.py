"""Local subprocess helpers."""

from __future__ import annotations

import os
import signal
import subprocess
from collections.abc import Callable, Mapping
from subprocess import CompletedProcess


def run_command(
    argv: list[str],
    *,
    cwd: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    on_output: Callable[[str], object] | None = None,
) -> CompletedProcess[str]:
    """Run a local command from an argument list and stream merged output.

    ``on_output`` receives each output line without its line ending.  The
    returned ``CompletedProcess.stdout`` retains the original line endings;
    stderr is merged into stdout so callers see tool diagnostics in order.
    """

    if not argv:
        raise ValueError("argv must contain an executable")

    process = subprocess.Popen(
        argv,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        shell=False,
    )

    output: list[str] = []
    assert process.stdout is not None
    try:
        for raw_line in process.stdout:
            output.append(raw_line)
            if on_output is not None:
                on_output(raw_line.rstrip("\r\n"))
    finally:
        process.stdout.close()

    returncode = process.wait()
    return CompletedProcess(
        args=argv,
        returncode=returncode,
        stdout="".join(output),
        stderr=None,
    )


def kill_process_tree(pid: int) -> None:
    """Terminate a process and its descendants using local OS facilities."""

    if pid <= 0:
        raise ValueError("pid must be positive")

    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
            )
        except FileNotFoundError:
            # A minimal Windows environment may not expose taskkill.  The
            # direct fallback still gives the caller best-effort termination.
            try:
                os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
        return

    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
