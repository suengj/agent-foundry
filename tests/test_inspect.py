"""Inspection module tests — determinism, read-only, bounds, and brownfield semantics."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agent_foundry.inspect import inspect_project
from agent_foundry.models import ProvenanceKind, dump_json
from agent_foundry.models.common import IntakeMode

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "projects"
GREENFIELD = FIXTURES / "greenfield-minimal"
BROWNFIELD = FIXTURES / "brownfield-sample"
REPO_ROOT = Path(__file__).resolve().parents[1]


def _tree_digest(root: Path) -> dict[str, str]:
    digests: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            digests[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


def test_inspect_greenfield_fixture_is_deterministic() -> None:
    first = dump_json(inspect_project(GREENFIELD))
    second = dump_json(inspect_project(GREENFIELD))
    assert first == second
    assert first  # non-empty output


def test_inspect_brownfield_fixture_is_deterministic() -> None:
    first = dump_json(inspect_project(BROWNFIELD))
    second = dump_json(inspect_project(BROWNFIELD))
    assert first == second


def test_inspect_does_not_mutate_fixture_tree(tmp_path: Path) -> None:
    target = tmp_path / "project"
    shutil.copytree(GREENFIELD, target)
    before = _tree_digest(target)
    inspect_project(target)
    after = _tree_digest(target)
    assert before == after


def test_inspect_brownfield_detects_conflicting_agent_surfaces() -> None:
    intake = inspect_project(BROWNFIELD)
    agent_obs = [o for o in intake.observations if o.subject == "agent-instruction-surface"]
    assert len(agent_obs) >= 3

    fragmentation = [
        f for f in intake.readiness_findings if f.dimension == "fragmented-agent-rule-surfaces"
    ]
    assert fragmentation
    assert any("must not be treated as normative" in f.message for f in fragmentation)

    classification = [f for f in intake.classification_findings if f.dimension == "agent-rule-fragmentation"]
    assert classification
    assert classification[0].provenance.kind == ProvenanceKind.OBSERVED


def test_brownfield_observed_rules_are_not_promoted_to_normative() -> None:
    intake = inspect_project(BROWNFIELD)
    for observation in intake.observations:
        if observation.subject == "agent-instruction-surface":
            assert observation.provenance.kind != ProvenanceKind.NORMATIVE
    for finding in intake.classification_findings:
        assert finding.provenance.kind != ProvenanceKind.NORMATIVE
    for convention in intake.conventions:
        assert convention.provenance.kind != ProvenanceKind.NORMATIVE
    for finding in intake.readiness_findings:
        if finding.dimension == "fragmented-agent-rule-surfaces":
            assert finding.provenance.kind == ProvenanceKind.OBSERVED


def test_unknown_classification_dimensions_remain_explicit() -> None:
    intake = inspect_project(GREENFIELD)
    autonomy = [f for f in intake.classification_findings if f.dimension == "execution.autonomy"]
    assert autonomy
    assert autonomy[0].value is None
    assert autonomy[0].provenance.kind == ProvenanceKind.INFERRED


def test_greenfield_intake_mode_inferred() -> None:
    intake = inspect_project(GREENFIELD)
    modes = [f for f in intake.classification_findings if f.dimension == "intake_mode"]
    assert modes
    assert modes[0].value == IntakeMode.GREENFIELD.value


def test_brownfield_intake_mode_inferred_or_declared() -> None:
    intake = inspect_project(BROWNFIELD)
    modes = [f for f in intake.classification_findings if f.dimension == "intake_mode"]
    assert modes
    declared = [m for m in modes if m.provenance.kind == ProvenanceKind.DECLARED]
    inferred = [m for m in modes if m.provenance.kind == ProvenanceKind.INFERRED]
    assert declared or inferred


def test_traversal_bounds_enforced(tmp_path: Path) -> None:
    root = tmp_path / "deep"
    root.mkdir()
    current = root
    for idx in range(20):
        current = current / f"level-{idx:02d}"
        current.mkdir()
        (current / "file.txt").write_text("x", encoding="utf-8")

    intake = inspect_project(root, max_depth=3, max_entries=10)
    stats = intake.traversal_stats
    assert stats.entry_limit_reached or stats.depth_limit_reached
    assert stats.entries_visited <= 10


def test_output_uses_repo_relative_paths_only() -> None:
    intake = inspect_project(BROWNFIELD)
    assert intake.project_root == "."
    payload = dump_json(intake).decode("utf-8")
    assert str(BROWNFIELD) not in payload
    for observation in intake.observations:
        if observation.provenance.source_ref:
            assert not observation.provenance.source_ref.startswith("/")


def test_cli_inspect_json(tmp_path: Path) -> None:
    target = tmp_path / "project"
    shutil.copytree(GREENFIELD, target)
    result = subprocess.run(
        [sys.executable, "-m", "agent_foundry", "inspect", str(target), "--format", "json"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert b'"schema_version":"0.1"' in result.stdout or b'"schema_version": "0.1"' in result.stdout


def test_cli_help_lists_inspect() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "agent_foundry", "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "inspect" in result.stdout
