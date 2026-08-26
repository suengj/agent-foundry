"""Rework regression tests for AF2 review blockers and required residuals."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agent_foundry.inspect import inspect_project
from agent_foundry.inspect.traversal import GIT_METADATA_MAX_BYTES
from agent_foundry.models import ProvenanceKind, dump_json
from agent_foundry.models.common import IntakeMode

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "projects"
GREENFIELD = FIXTURES / "greenfield-minimal"
BROWNFIELD = FIXTURES / "brownfield-sample"
REPO_ROOT = Path(__file__).resolve().parents[1]


def _subprocess_env() -> dict[str, str]:
    return {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}


def _tree_digest(root: Path) -> dict[str, str]:
    """Content plus the metadata a read-only pass must not disturb (notably mtime)."""
    digests: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            stat = path.lstat()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            digests[rel] = f"{digest} mode={stat.st_mode:o} mtime_ns={stat.st_mtime_ns}"
    return digests


# --- BLOCKERS ---


def test_b1_symlink_loop_does_not_crash(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "selfref").symlink_to("selfref")
    intake = inspect_project(repo)
    assert intake.traversal_stats.entries_skipped >= 1


def test_b2_escaping_directory_symlink_does_not_crash(tmp_path: Path) -> None:
    outside = tmp_path / "outside" / "rules"
    outside.mkdir(parents=True)
    (outside / "leak.mdc").write_text("rule", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".cursor").mkdir()
    (repo / ".cursor" / "rules").symlink_to(outside)
    intake = inspect_project(repo)
    outside_refs = [
        o for o in intake.observations if o.provenance.source_ref and "outside" in o.provenance.source_ref
    ]
    assert outside_refs == []


def test_b3_escaping_file_symlink_not_observed(tmp_path: Path) -> None:
    outside = tmp_path / "outside.md"
    outside.write_text("run pytest for tests", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").symlink_to(outside)
    intake = inspect_project(repo)
    agent_obs = [o for o in intake.observations if o.subject == "agent-instruction-surface"]
    assert agent_obs == []
    test_runner = [c for c in intake.conventions if c.subject == "test-runner"]
    assert test_runner == []
    structure = [o for o in intake.observations if o.subject == "repository-structure"]
    visited_line = next(o for o in structure if "visited" in o.content)
    assert "0 files" in visited_line.content


def test_b4_makefile_target_not_substring_matched(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "Makefile").write_text(
        "lint:\n\truff check .\n# see docs: pytest: is intentionally absent\n",
        encoding="utf-8",
    )
    intake = inspect_project(repo)
    false_test = [
        o
        for o in intake.observations
        if o.subject == "test-entrypoint" and "declares 'test' target" in o.content
    ]
    assert false_test == []
    lint_obs = [o for o in intake.observations if o.subject == "lint-entrypoint"]
    assert any("declares 'lint' target" in o.content for o in lint_obs)


def test_b5_multi_surface_mentions_recorded_without_stance() -> None:
    intake = inspect_project(BROWNFIELD)
    mentions = [c for c in intake.conventions if c.subject == "test-runner"]
    assert len(mentions) >= 2
    for mention in mentions:
        assert mention.provenance.kind == ProvenanceKind.INFERRED
        assert mention.confidence <= 0.5
        assert "prescribe" not in mention.pattern.lower()
        assert "reject" not in mention.pattern.lower()
    disagreement = [c for c in intake.conventions if c.subject == "test-runner-disagreement"]
    assert disagreement == []
    unreconciled = [
        f for f in intake.readiness_findings if f.dimension == "unreconciled-subject-mentions"
    ]
    assert unreconciled
    assert "not been reconciled" in unreconciled[0].message.lower()


# --- RESIDUALS ---


def test_r1_max_file_bytes_enforced(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("run pytest for all tests\n" * 5, encoding="utf-8")
    intake = inspect_project(repo, max_file_bytes=5)
    assert intake.traversal_stats.limits.max_file_bytes == 5
    test_runner = [c for c in intake.conventions if c.subject == "test-runner"]
    assert test_runner == []


def test_r3_source_ref_points_to_existing_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    tests_dir = repo / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "conftest.py").write_text("# pytest config\n", encoding="utf-8")
    intake = inspect_project(repo)
    for observation in intake.observations:
        ref = observation.provenance.source_ref
        if ref and ref not in {".", ".git/HEAD"}:
            assert (repo / ref).is_file(), f"missing source_ref {ref!r}"


def test_r7_brownfield_env_example_tracked() -> None:
    env_example = BROWNFIELD / "env.example"
    assert env_example.is_file()
    archive = subprocess.run(
        ["git", "archive", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
    )
    listing = subprocess.run(
        ["tar", "-t"],
        input=archive.stdout,
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")
    assert "tests/fixtures/projects/brownfield-sample/env.example" in listing
    intake = inspect_project(BROWNFIELD)
    integration = [o for o in intake.observations if o.subject == "integration-config"]
    assert integration


def test_r8_cli_inspect_json_hermetic(tmp_path: Path) -> None:
    target = tmp_path / "project"
    shutil.copytree(GREENFIELD, target)
    result = subprocess.run(
        [sys.executable, "-m", "agent_foundry", "inspect", str(target), "--format", "json"],
        cwd=tmp_path,
        env=_subprocess_env(),
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert b"schema_version" in result.stdout
    assert b"inspect" not in result.stderr


def test_r8_cli_help_lists_inspect_hermetic() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "agent_foundry", "--help"],
        cwd=tmp_path if (tmp_path := Path("/")) else REPO_ROOT,
        env=_subprocess_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "inspect" in result.stdout


# --- Regression guards ---


def test_read_only_brownfield_fixture(tmp_path: Path) -> None:
    target = tmp_path / "project"
    shutil.copytree(BROWNFIELD, target)
    before = _tree_digest(target)
    inspect_project(target)
    after = _tree_digest(target)
    assert before == after


@pytest.mark.parametrize("seed", ["0", "42"])
@pytest.mark.parametrize("cwd", [REPO_ROOT, Path("/tmp")])
def test_determinism_across_seed_and_cwd(seed: str, cwd: Path) -> None:
    env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(REPO_ROOT / "src")}
    first = subprocess.run(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; "
            "from agent_foundry.inspect import inspect_project; "
            "from agent_foundry.models import dump_json; "
            f"p = Path({str(GREENFIELD)!r}); "
            "print(dump_json(inspect_project(p)).decode())",
        ],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    second = subprocess.run(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; "
            "from agent_foundry.inspect import inspect_project; "
            "from agent_foundry.models import dump_json; "
            f"p = Path({str(GREENFIELD)!r}); "
            "print(dump_json(inspect_project(p)).decode())",
        ],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert first == second


def test_r10_declared_intake_mode_from_foundry_project_yaml() -> None:
    intake = inspect_project(BROWNFIELD)
    declared = [
        f
        for f in intake.classification_findings
        if f.dimension == "intake_mode" and f.provenance.kind == ProvenanceKind.DECLARED
    ]
    assert declared
    assert declared[0].value == IntakeMode.BROWNFIELD.value


def test_git_head_ref_with_overlong_name_does_not_raise(tmp_path: Path) -> None:
    """A repo-controlled ref name can exceed the OS name limit; stat() must not escape."""
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "pyproject.toml").write_text('[project]\nname="x"\nversion="0.1"\n')
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/" + "a" * 1000 + "\n")
    assert inspect_project(str(repo)).repository_revision is None


def test_oversized_git_head_is_not_read_into_memory(tmp_path: Path) -> None:
    """git metadata is bounded like every other read; a huge HEAD must not be slurped."""
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "pyproject.toml").write_text('[project]\nname="x"\nversion="0.1"\n')
    (repo / ".git" / "HEAD").write_text("a" * (GIT_METADATA_MAX_BYTES + 1))
    assert inspect_project(str(repo)).repository_revision is None
