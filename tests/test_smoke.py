import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _env() -> dict[str, str]:
    """Pin the child to THIS checkout.

    pyproject's `pythonpath` applies to the pytest process only, never to a
    subprocess, so without this the child resolves through whatever the venv's
    editable install happens to point at -- which may be an entirely different
    worktree, silently validating code that is not under test.
    """
    return {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}


def test_cli_help():
    result = subprocess.run(
        [sys.executable, "-m", "agent_foundry", "--help"],
        cwd=REPO_ROOT,
        env=_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "Agent Foundry" in result.stdout
    assert "version" in result.stdout
    assert "doctor" in result.stdout


def test_version_command():
    result = subprocess.run(
        [sys.executable, "-m", "agent_foundry", "version"],
        cwd=REPO_ROOT,
        env=_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "agent-foundry" in result.stdout


def test_doctor_passes():
    result = subprocess.run(
        [sys.executable, "-m", "agent_foundry", "doctor"],
        cwd=REPO_ROOT,
        env=_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "[ok]" in result.stdout
