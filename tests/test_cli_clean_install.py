"""`doctor` must be correct when the package is installed, not just checked out.

Every other test in this suite runs from the repository root, where a path derived
from `__file__` happens to land on the repo. That made a whole class of defect
invisible: `doctor` resolved its project artifacts relative to the installed package
and failed every check on a clean `pip install`. These tests run the CLI from a
working directory outside the repository, and one of them against a genuinely
non-editable install, so the defect cannot come back unnoticed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"


def _run(argv: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True)


def _src_env() -> dict[str, str]:
    """Pin imports to this checkout's src, independent of any editable install."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    env.pop("PYTHONHOME", None)
    return env


def test_source_tree_under_test_is_the_one_that_runs(tmp_path: Path):
    """Guard the harness itself: prove which tree the subprocess imports."""
    result = _run(
        [sys.executable, "-c", "import agent_foundry; print(agent_foundry.__file__)"],
        cwd=tmp_path,
        env=_src_env(),
    )
    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()) == SRC / "agent_foundry" / "__init__.py"


def test_doctor_outside_any_project_reports_skip_and_succeeds(tmp_path: Path):
    """No project in scope is a normal state, not a broken installation."""
    result = _run(
        [sys.executable, "-m", "agent_foundry", "doctor"], cwd=tmp_path, env=_src_env()
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "package self-check" in result.stdout
    assert "[skip]" in result.stdout
    assert "[FAIL]" not in result.stdout


def test_doctor_reports_a_named_project_that_lacks_artifacts(tmp_path: Path):
    """An explicit path that is not a Foundry project fails distinctly (exit 2)."""
    result = _run(
        [sys.executable, "-m", "agent_foundry", "doctor", str(tmp_path)],
        cwd=tmp_path,
        env=_src_env(),
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "product contract" in result.stdout
    assert "[FAIL]" in result.stdout


def test_doctor_finds_this_repository_when_run_from_within_it(tmp_path: Path):
    """Source-checkout behavior must stay useful."""
    result = _run(
        [sys.executable, "-m", "agent_foundry", "doctor"], cwd=REPO_ROOT, env=_src_env()
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert str(REPO_ROOT) in result.stdout
    assert "[skip]" not in result.stdout


def test_doctor_discovers_a_project_root_from_a_nested_directory(tmp_path: Path):
    """Discovery walks upward from CWD — never from the package's own location."""
    project = tmp_path / "consumer"
    (project / "docs" / "contracts").mkdir(parents=True)
    (project / "docs" / "ai").mkdir(parents=True)
    (project / "docs" / "contracts" / "product-boundary.md").write_text("# boundary\n")
    (project / "docs" / "ai" / "PROJECT_AGENT_CONSTITUTION.md").write_text("# rules\n")
    nested = project / "a" / "b" / "c"
    nested.mkdir(parents=True)

    result = _run(
        [sys.executable, "-m", "agent_foundry", "doctor"], cwd=nested, env=_src_env()
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert str(project.resolve()) in result.stdout
    assert "[FAIL]" not in result.stdout


@pytest.mark.skipif(
    shutil.which("pip") is None and not (Path(sys.prefix) / "bin" / "pip").exists(),
    reason="pip unavailable for a clean-install build",
)
def test_non_editable_install_runs_from_an_unrelated_directory(tmp_path: Path):
    """The AF9 clean-install gate, executed rather than assumed.

    This deliberately does NOT use PYTHONPATH or an editable install: it builds and
    installs the distribution into a fresh venv, then runs the console script from a
    directory that has nothing to do with any checkout.
    """
    env_dir = tmp_path / "cleanvenv"
    venv.create(env_dir, with_pip=True)
    bin_dir = env_dir / ("Scripts" if os.name == "nt" else "bin")
    python = bin_dir / ("python.exe" if os.name == "nt" else "python")

    install = subprocess.run(
        [str(python), "-m", "pip", "install", "--quiet", str(REPO_ROOT)],
        capture_output=True,
        text=True,
    )
    assert install.returncode == 0, install.stdout + install.stderr

    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    clean_env = {
        k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")
    }

    where = _run(
        [str(python), "-c", "import agent_foundry; print(agent_foundry.__file__)"],
        cwd=unrelated,
        env=clean_env,
    )
    assert where.returncode == 0, where.stderr
    # Prove the installed copy is under test, not the checkout.
    assert "site-packages" in where.stdout

    version = _run([str(python), "-m", "agent_foundry", "version"], cwd=unrelated, env=clean_env)
    assert version.returncode == 0, version.stdout + version.stderr
    assert "agent-foundry" in version.stdout

    doctor = _run([str(python), "-m", "agent_foundry", "doctor"], cwd=unrelated, env=clean_env)
    assert doctor.returncode == 0, doctor.stdout + doctor.stderr
    assert "[FAIL]" not in doctor.stdout
    assert "[skip]" in doctor.stdout

    scoped = _run(
        [str(python), "-m", "agent_foundry", "doctor", str(REPO_ROOT)],
        cwd=unrelated,
        env=clean_env,
    )
    assert scoped.returncode == 0, scoped.stdout + scoped.stderr
    assert "[FAIL]" not in scoped.stdout


_BROKEN_PACKAGE_DRIVER = """
import sys
import agent_foundry.cli as cli

# Simulate a broken installation without adding a test hook to shipping code:
# the self-check reports a failure, everything downstream is the real thing.
cli._package_self_check = lambda: [("package version", False, "simulated breakage")]
sys.exit(cli.main(["doctor", *sys.argv[1:]]))
"""


@pytest.mark.parametrize(
    ("argv_suffix", "cwd_kind"),
    [
        ([], "outside"),             # the [skip] path
        ([], "repo"),                # a discovered project
        (["<missing>"], "outside"),  # explicit path that is not a directory
        (["<tmp>"], "outside"),      # explicit directory lacking artifacts
    ],
)
def test_broken_installation_always_outranks_any_project_finding(
    tmp_path: Path, argv_suffix: list[str], cwd_kind: str
):
    """Exit 1 must win on every path.

    A project verdict produced by a broken installation was produced by code that
    cannot be trusted, so it must never be the code the caller sees. The earlier
    version returned 2 for an invalid explicit path before ever consulting the
    package result.
    """
    driver = tmp_path / "broken_driver.py"
    driver.write_text(_BROKEN_PACKAGE_DRIVER)

    resolved = [
        str(tmp_path / "definitely-not-here")
        if arg == "<missing>"
        else str(tmp_path)
        if arg == "<tmp>"
        else arg
        for arg in argv_suffix
    ]
    cwd = REPO_ROOT if cwd_kind == "repo" else tmp_path

    result = _run(
        [sys.executable, str(driver), *resolved], cwd=cwd, env=_src_env()
    )
    assert result.returncode == 1, (
        f"expected exit 1 for a broken package, got {result.returncode}\n"
        f"{result.stdout}{result.stderr}"
    )


def test_healthy_package_still_reports_project_failures_distinctly(tmp_path: Path):
    """The precedence rule must not swallow a real project finding."""
    result = _run(
        [sys.executable, "-m", "agent_foundry", "doctor", str(tmp_path)],
        cwd=tmp_path,
        env=_src_env(),
    )
    assert result.returncode == 2, result.stdout + result.stderr
