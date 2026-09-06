import csv
import io
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from vhs_restore.utils.logging import setup_job_logger
from vhs_restore.utils import process as process_utils
from vhs_restore.utils.process import kill_process_tree, run_command, start_command
from vhs_restore.utils.system import find_tool, free_disk_space


def _pid_is_running(pid: int) -> bool:
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
            )
        except OSError:
            return False
        if result.returncode != 0:
            return False
        for row in csv.reader(io.StringIO(result.stdout)):
            if len(row) > 1 and row[1].strip() == str(pid):
                return True
        return False

    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def _windows_sleep_process_stays_alive(tmp_path: Path) -> bool:
    """Return whether a short-lived sleep child survives a cheap preflight."""
    process = subprocess.Popen(
        [sys.executable, "-u", "-c", "import time; time.sleep(2)"],
        cwd=tmp_path,
    )
    deadline = time.monotonic() + 1.0
    try:
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        return process.poll() is None
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=2)



def _wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def test_run_command_uses_argv_list_and_streams_combined_output(tmp_path: Path):
    script = (
        "import sys; "
        "print(sys.argv[1]); "
        "print(sys.argv[2], file=sys.stderr)"
    )
    argv = [
        sys.executable,
        "-X",
        "utf8",
        "-u",
        "-c",
        script,
        "日本語 path",
        "space (and) [brackets]",
    ]
    received: list[str] = []

    result = run_command(argv, cwd=tmp_path, on_output=received.append)

    assert result.args == argv
    assert result.returncode == 0
    assert received == ["日本語 path", "space (and) [brackets]"]
    assert result.stdout.splitlines() == received


def test_run_command_passes_environment_without_shell(tmp_path: Path):
    script = "import os; print(os.environ['VHS_RESTORE_TEST_VALUE'])"
    env = os.environ.copy()
    env["VHS_RESTORE_TEST_VALUE"] = "local-only"

    result = run_command([sys.executable, "-c", script], cwd=tmp_path, env=env)

    assert result.returncode == 0
    assert result.stdout.strip() == "local-only"


def test_run_command_decodes_utf8_output_explicitly(tmp_path: Path):
    script = (
        "import sys; "
        "sys.stdout.buffer.write('日本語 ✓\\n'.encode('utf-8')); "
        "sys.stdout.flush()"
    )

    result = run_command([sys.executable, "-c", script], cwd=tmp_path)

    assert result.stdout == "日本語 ✓\n"


def test_run_command_callback_failure_kills_and_waits_for_child(tmp_path: Path):
    script = "import os, time; print(os.getpid(), flush=True); time.sleep(60)"
    child_pid: int | None = None

    def fail_on_output(line: str):
        nonlocal child_pid
        child_pid = int(line)
        raise RuntimeError("callback failed")

    try:
        with pytest.raises(RuntimeError, match="callback failed"):
            run_command(
                [sys.executable, "-u", "-c", script],
                cwd=tmp_path,
                on_output=fail_on_output,
            )

        assert child_pid is not None
        assert _wait_until(lambda: not _pid_is_running(child_pid))
    finally:
        if child_pid is not None and _pid_is_running(child_pid):
            kill_process_tree(child_pid)


def test_windows_pid_exists_treats_tasklist_failure_as_unverifiable(
    monkeypatch: pytest.MonkeyPatch,
):
    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            argv,
            1,
            stdout="",
            stderr="ERROR: Access is denied.",
        )

    monkeypatch.setattr(process_utils.subprocess, "run", fake_run)

    with pytest.raises(process_utils.ProcessTreeTerminationError):
        process_utils._windows_pid_exists(2468)


def test_windows_pid_exists_keeps_a_matching_csv_row_live(
    monkeypatch: pytest.MonkeyPatch,
):
    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout='"python.exe","2468","Console","1","1,024 K"\r\n',
            stderr="",
        )

    monkeypatch.setattr(process_utils.subprocess, "run", fake_run)

    assert process_utils._windows_pid_exists(2468) is True


def test_pid_is_running_treats_tasklist_failure_as_missing(
    monkeypatch: pytest.MonkeyPatch,
):
    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            argv,
            1,
            stdout="",
            stderr="ERROR: Access is denied.",
        )

    monkeypatch.setattr(process_utils.os, "name", "nt")
    monkeypatch.setattr(process_utils.subprocess, "run", fake_run)

    assert _pid_is_running(2468) is False


def test_pid_is_running_treats_tasklist_unstartable_as_missing(
    monkeypatch: pytest.MonkeyPatch,
):
    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise PermissionError("Access is denied")

    monkeypatch.setattr(process_utils.os, "name", "nt")
    monkeypatch.setattr(process_utils.subprocess, "run", fake_run)

    assert _pid_is_running(2468) is False


def test_setup_job_logger_writes_utf8_log_once(tmp_path: Path):
    job_dir = tmp_path / "日本語 job [01]"

    logger = setup_job_logger(job_dir)
    logger.info("復元開始")
    for handler in logger.handlers:
        handler.flush()

    same_logger = setup_job_logger(job_dir)
    same_logger.info("完了")
    for handler in same_logger.handlers:
        handler.flush()

    log_path = job_dir / "job.log"
    assert same_logger is logger
    assert len(logger.handlers) == 1
    assert log_path.read_text(encoding="utf-8").count("復元開始") == 1
    assert log_path.read_text(encoding="utf-8").count("完了") == 1
    assert logger.level == logging.INFO


def test_kill_process_tree_accepts_a_missing_pid():
    kill_process_tree(2_147_483_647)


def test_kill_process_tree_surfaces_taskkill_failure_for_a_live_process(
    monkeypatch: pytest.MonkeyPatch,
):
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((argv, kwargs))
        if argv[0] == "taskkill":
            return subprocess.CompletedProcess(
                argv,
                1,
                stdout="ERROR: Access is denied.",
                stderr="",
            )
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout='"python.exe","2468","Console","1","1,024 K"\r\n',
            stderr="",
        )

    monkeypatch.setattr(process_utils.os, "name", "nt")
    monkeypatch.setattr(process_utils.subprocess, "run", fake_run)

    with pytest.raises(process_utils.ProcessTreeTerminationError):
        kill_process_tree(2468)

    assert calls[0][0] == ["taskkill", "/PID", "2468", "/T", "/F"]
    assert calls[0][1]["shell"] is False


def test_kill_process_tree_raises_when_taskkill_and_tasklist_are_unverifiable(
    monkeypatch: pytest.MonkeyPatch,
):
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(
            argv,
            1,
            stdout="",
            stderr="ERROR: Access is denied.",
        )

    monkeypatch.setattr(process_utils.os, "name", "nt")
    monkeypatch.setattr(process_utils.subprocess, "run", fake_run)

    with pytest.raises(process_utils.ProcessTreeTerminationError):
        kill_process_tree(2468)

    assert calls == [
        ["taskkill", "/PID", "2468", "/T", "/F"],
        ["tasklist", "/FI", "PID eq 2468", "/FO", "CSV", "/NH"],
    ]


@pytest.mark.skipif(os.name != "nt", reason="requires Windows taskkill process trees")
def test_kill_process_tree_terminates_windows_parent_and_child(tmp_path: Path):
    if not _windows_sleep_process_stays_alive(tmp_path):
        pytest.skip("sandbox does not keep sleep child processes alive")

    child_script = "import time; time.sleep(60)"
    parent_script = (
        "import subprocess, sys, time; "
        f"child = subprocess.Popen([sys.executable, '-u', '-c', {child_script!r}]); "
        "print(child.pid, flush=True); time.sleep(60)"
    )
    argv = [sys.executable, "-u", "-c", parent_script]
    output: list[str] = []
    managed = start_command(argv, cwd=tmp_path, on_output=output.append)
    child_pid: int | None = None

    try:
        assert managed.pid > 0
        assert _wait_until(lambda: bool(output))
        child_pid = int(output[0])
        assert _pid_is_running(managed.pid)
        assert _pid_is_running(child_pid)

        managed.kill()
        result = managed.wait(timeout=10)

        assert result.args == argv
        assert _wait_until(lambda: not _pid_is_running(managed.pid))
        assert _wait_until(lambda: not _pid_is_running(child_pid))
    finally:
        if _pid_is_running(managed.pid):
            kill_process_tree(managed.pid)
        if child_pid is not None and _pid_is_running(child_pid):
            kill_process_tree(child_pid)
        try:
            managed.wait(timeout=2)
        except (RuntimeError, subprocess.TimeoutExpired):
            pass


def test_free_disk_space_reports_the_filesystem_free_bytes(tmp_path: Path):
    assert free_disk_space(tmp_path) > 0


def test_find_tool_resolves_an_existing_executable():
    assert find_tool(sys.executable) == Path(sys.executable)
