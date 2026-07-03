"""Unit tests for agent-specific tools, primarily command execution."""

import os
import subprocess
from unittest.mock import MagicMock, patch

# Isolate LanceDB writes before any aw_vision import
os.environ.setdefault("LANCE_DB_DIR", "/tmp/test_aw_vision_db")

from aw_vision.agent import tool_execute_command  # noqa: E402


def test_execute_command_empty():
    """Verify that empty or None commands are rejected."""
    assert "Error: Command cannot be empty." in tool_execute_command("")
    assert "Error: Command cannot be empty." in tool_execute_command(None)


def test_execute_command_unwhitelisted():
    """Verify that unwhitelisted commands are rejected."""
    assert "not whitelisted" in tool_execute_command("ls -la")
    assert "not whitelisted" in tool_execute_command("cat config.toml")
    assert "not whitelisted" in tool_execute_command("sudo rm -rf /")


def test_execute_command_forbidden_chars():
    """Verify that forbidden shell characters and operators are rejected."""
    for char in [";", "&&", "||", "|", ">", "<", "`", "$", "\n", "\r"]:
        cmd = f"gh issue list {char} echo 'bad'"
        assert "forbidden shell operator or character" in tool_execute_command(cmd)


@patch("shutil.which")
def test_execute_command_not_installed(mock_which):
    """Verify that an error is returned when the whitelisted tool is not installed."""
    mock_which.return_value = None
    res = tool_execute_command("gh issue list")
    assert "is not installed or not in PATH" in res


@patch("shutil.which")
@patch("subprocess.run")
def test_execute_command_success_mocked(mock_run, mock_which):
    """Verify that a valid whitelisted command executes and returns output, filtering env."""
    mock_which.return_value = "/usr/bin/gh"

    # Configure mock process
    mock_process = MagicMock()
    mock_process.returncode = 0
    mock_process.stdout = "PRJ-2026-042\nPRJ-2026-089"
    mock_process.stderr = ""
    mock_run.return_value = mock_process

    # Set up some dummy environment variables to test filtering
    with patch.dict(
        os.environ,
        {
            "DUMMY_SECRET_KEY": "dummy_secret_value",
            "GITHUB_TOKEN": "gh_secret_token",
            "GOOGLE_WORKSPACE_CLIENT_ID": "gws_id",
            "GH_USER": "jelle",
        },
    ):
        res = tool_execute_command("gh issue list --state open")

        # Verify result output
        assert res == "PRJ-2026-042\nPRJ-2026-089"

        # Verify mock_run call arguments and environment filtering
        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args

        assert args[0] == ["gh", "issue", "list", "--state", "open"]
        assert kwargs["shell"] is False
        assert kwargs["timeout"] == 10.0

        env = kwargs["env"]
        # Essential env vars must be preserved if present
        if "PATH" in os.environ:
            assert env["PATH"] == os.environ["PATH"]
        if "HOME" in os.environ:
            assert env["HOME"] == os.environ["HOME"]

        # Whitelisted env vars must be present
        assert env["GITHUB_TOKEN"] == "gh_secret_token"
        assert env["GOOGLE_WORKSPACE_CLIENT_ID"] == "gws_id"
        assert env["GH_USER"] == "jelle"

        # Non-whitelisted variables must be excluded
        assert "DUMMY_SECRET_KEY" not in env


@patch("shutil.which")
@patch("subprocess.run")
def test_execute_command_failure_exit_code(mock_run, mock_which):
    """Verify that exit codes and stderr/stdout are structured on command failure."""
    mock_which.return_value = "/usr/bin/gh"

    mock_process = MagicMock()
    mock_process.returncode = 1
    mock_process.stdout = "Partially succeeded text"
    mock_process.stderr = "Command not authenticated or offline"
    mock_run.return_value = mock_process

    res = tool_execute_command("gh issue list")
    assert "failed with exit code 1" in res
    assert "Stdout:\nPartially succeeded text" in res
    assert "Stderr:\nCommand not authenticated or offline" in res


@patch("shutil.which")
@patch("subprocess.run")
def test_execute_command_timeout(mock_run, mock_which):
    """Verify that subprocess timeout is caught and clean error is returned."""
    mock_which.return_value = "/usr/bin/gh"
    mock_run.side_effect = subprocess.TimeoutExpired(cmd=["gh"], timeout=10.0)

    res = tool_execute_command("gh issue list")
    assert "Command execution timed out after 10 seconds" in res
