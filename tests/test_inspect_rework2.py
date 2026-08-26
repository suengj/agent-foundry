"""Second rework regression tests — N1, B5 architectural change, B4 residue."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agent_foundry.inspect import inspect_project
from agent_foundry.models import ProvenanceKind, dump_json

REPO_ROOT = Path(__file__).resolve().parents[1]
BROWNFIELD = REPO_ROOT / "tests" / "fixtures" / "projects" / "brownfield-sample"
GREENFIELD = REPO_ROOT / "tests" / "fixtures" / "projects" / "greenfield-minimal"

PYTEST_PHRASINGS = [
    "We do not use pytest.",
    "Do NOT use pytest in this repo.",
    "Never use pytest here.",
    "pytest is banned in this repository.",
    "Avoid pytest; use unittest.",
    "We no longer use pytest.",
    "Don't use pytest.",
    "Run tests with pytest before committing.",
    "This repository standardizes on unittest, not pytest.",
]

STANCE_CLAIM_MARKERS = ("prescribe", "reject", "without negation", "disagree on pytest")


def _subprocess_env() -> dict[str, str]:
    return {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}


def _tree_snapshot(root: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_file():
            data = path.read_bytes()
            snapshot[f"file:{rel}"] = hashlib.sha256(data).hexdigest()
        elif path.is_dir():
            mode = path.stat().st_mode
            snapshot[f"dir:{rel}"] = f"{mode:o}"
    return snapshot


def test_n1_git_head_ref_escape_does_not_leak_outside_content(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    secret = tmp_path / "secret.txt"
    secret.write_text("SENSITIVE-OUT-OF-ROOT-LINE\n", encoding="utf-8")
    repo.mkdir()
    git_dir = repo / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: ../../secret.txt\n", encoding="utf-8")
    intake = inspect_project(repo)
    assert intake.repository_revision is None
    payload = dump_json(intake).decode("utf-8")
    assert "SENSITIVE-OUT-OF-ROOT-LINE" not in payload


def test_n1_git_dir_symlink_outside_root_is_refused(tmp_path: Path) -> None:
    outside_git = tmp_path / "outside-git"
    outside_git.mkdir()
    (outside_git / "HEAD").write_text(
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n", encoding="utf-8"
    )
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").symlink_to(outside_git)
    intake = inspect_project(repo)
    assert intake.repository_revision is None


def test_b4_makefile_assignment_not_target(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "Makefile").write_text("test := pytest -q\n", encoding="utf-8")
    intake = inspect_project(repo)
    test_obs = [o for o in intake.observations if o.subject == "test-entrypoint"]
    assert test_obs == []


def test_b4_makefile_tab_indented_recipe_not_target(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "Makefile").write_text("all:\n\tci: skipped\n", encoding="utf-8")
    intake = inspect_project(repo)
    ci_obs = [o for o in intake.observations if o.subject == "ci-entrypoint"]
    assert ci_obs == []


@pytest.mark.parametrize("phrase", PYTEST_PHRASINGS)
def test_b5_no_prescribe_reject_claim_for_any_phrasing(tmp_path: Path, phrase: str) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text(phrase + "\n", encoding="utf-8")
    intake = inspect_project(repo)
    for convention in intake.conventions:
        if convention.subject == "test-runner":
            lowered = (convention.pattern + convention.evidence).lower()
            assert not any(marker in lowered for marker in STANCE_CLAIM_MARKERS)
            assert convention.provenance.kind == ProvenanceKind.INFERRED
            assert convention.confidence <= 0.5
    if "pytest" in phrase.lower():
        mentions = [c for c in intake.conventions if c.subject == "test-runner"]
        assert mentions
        assert phrase.strip() in mentions[0].evidence or phrase in mentions[0].evidence


def test_b5_multi_surface_unreconciled_subject_finding(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("Run tests with pytest before committing.\n", encoding="utf-8")
    (repo / "CLAUDE.md").write_text("We do not use pytest.\n", encoding="utf-8")
    intake = inspect_project(repo)
    disagreement = [c for c in intake.conventions if c.subject == "test-runner-disagreement"]
    assert disagreement == []
    unreconciled = [
        f for f in intake.readiness_findings if f.dimension == "unreconciled-subject-mentions"
    ]
    assert unreconciled
    assert "test-runner" in unreconciled[0].message
    assert "not been reconciled" in unreconciled[0].message.lower()


def test_b5_uniform_reject_still_records_mentions(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("Never use pytest here.\n", encoding="utf-8")
    (repo / "CLAUDE.md").write_text("Do NOT use pytest in this repo.\n", encoding="utf-8")
    intake = inspect_project(repo)
    mentions = [c for c in intake.conventions if c.subject == "test-runner"]
    assert len(mentions) == 2
    for mention in mentions:
        assert mention.provenance.kind == ProvenanceKind.INFERRED


def test_r4_oversized_file_emits_skip_observation(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("x" * 100, encoding="utf-8")
    intake = inspect_project(repo, max_file_bytes=50)
    skipped = [o for o in intake.observations if o.subject == "file-read-skipped"]
    assert any("AGENTS.md" in o.content for o in skipped)


def test_r6_classification_unknown_uses_reason_field(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    intake = inspect_project(repo)
    unknown = [
        f
        for f in intake.classification_findings
        if f.dimension == "execution.autonomy" and f.value is None
    ]
    assert unknown
    assert unknown[0].reason is not None
    assert not any(ref.startswith("reason:") for ref in unknown[0].evidence_refs)


def test_read_only_after_rework2_changes(tmp_path: Path) -> None:
    target = tmp_path / "project"
    shutil.copytree(BROWNFIELD, target)
    before = _tree_snapshot(target)
    inspect_project(target)
    after = _tree_snapshot(target)
    assert before == after


@pytest.mark.parametrize("seed", ["0", "42"])
def test_determinism_after_rework2_changes(seed: str) -> None:
    env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(REPO_ROOT / "src")}
    cmd = [
        sys.executable,
        "-c",
        "from pathlib import Path; "
        "from agent_foundry.inspect import inspect_project; "
        "from agent_foundry.models import dump_json; "
        f"p = Path({str(GREENFIELD)!r}); "
        "print(dump_json(inspect_project(p)).decode())",
    ]
    first = subprocess.run(cmd, cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=True).stdout
    second = subprocess.run(cmd, cwd="/tmp", env=env, capture_output=True, text=True, check=True).stdout
    assert first == second
