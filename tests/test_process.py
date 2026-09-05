import logging
import os
import sys
from pathlib import Path

from vhs_restore.utils.logging import setup_job_logger
from vhs_restore.utils.process import kill_process_tree, run_command
from vhs_restore.utils.system import find_tool, free_disk_space


def test_run_command_uses_argv_list_and_streams_combined_output(tmp_path: Path):
    script = (
        "import sys; "
        "print(sys.argv[1]); "
        "print(sys.argv[2], file=sys.stderr)"
    )
    argv = [sys.executable, "-u", "-c", script, "日本語 path", "space (and) [brackets]"]
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


def test_free_disk_space_reports_the_filesystem_free_bytes(tmp_path: Path):
    assert free_disk_space(tmp_path) > 0


def test_find_tool_resolves_an_existing_executable():
    assert find_tool(sys.executable) == Path(sys.executable)
