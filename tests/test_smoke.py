import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_cli_help():
    result = subprocess.run(
        [sys.executable, "-m", "agent_foundry", "--help"],
        cwd=REPO_ROOT,
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
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "[ok]" in result.stdout
