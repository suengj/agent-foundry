"""Adoption planning tests — manifest synthesis, change sets, authority, determinism."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agent_foundry.adopt import plan_adoption
from agent_foundry.adopt.authority import assert_change_set_respects_authority
from agent_foundry.adopt.changes import proposed_autonomy_for_change, proposed_external_effect_for_change
from agent_foundry.inspect import inspect_project
from agent_foundry.models import (
    AdoptionAction,
    AdoptionChangeItem,
    AdoptionChangeStatus,
    AdoptionEvidence,
    AuthorityRequirement,
    Autonomy,
    ExternalEffectClass,
    IntakeMode,
    Provenance,
    ProvenanceKind,
    dump_json,
)
from agent_foundry.models.common import ConsequenceClass
from agent_foundry.models.project import (
    ClassificationFinding,
    ProjectIntake,
    ReadinessFinding,
    TraversalLimits,
    TraversalStats,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "projects"
GREENFIELD = FIXTURES / "greenfield-minimal"
BROWNFIELD = FIXTURES / "brownfield-sample"
REPO_ROOT = Path(__file__).resolve().parents[1]


def _subprocess_env() -> dict[str, str]:
    return {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}


def _tree_digest(root: Path) -> dict[str, str]:
    digests: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            digests[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


def _minimal_intake(**overrides: object) -> ProjectIntake:
    limits = TraversalLimits(max_depth=4, max_entries=100, max_file_bytes=65536, skipped_dir_names=[])
    stats = TraversalStats(
        entries_visited=1,
        entries_skipped=0,
        depth_limit_reached=False,
        entry_limit_reached=False,
        limits=limits,
    )
    base = {
        "schema_version": "0.1",
        "project_root": ".",
        "repository_revision": None,
        "observations": [],
        "classification_findings": [],
        "conventions": [],
        "readiness_findings": [],
        "traversal_stats": stats,
    }
    base.update(overrides)
    return ProjectIntake.model_validate(base)


def test_greenfield_produces_manifest_and_change_set() -> None:
    result = plan_adoption(inspect_project(GREENFIELD))
    assert result.manifest.project.intake_mode == IntakeMode.GREENFIELD
    assert result.change_set.intake_mode == IntakeMode.GREENFIELD
    assert result.change_set.changes
    targets = {change.target for change in result.change_set.changes}
    assert "foundry-project-declaration" in targets


def test_brownfield_produces_manifest_and_change_set() -> None:
    result = plan_adoption(inspect_project(BROWNFIELD))
    assert result.manifest.project.intake_mode == IntakeMode.BROWNFIELD
    assert result.change_set.intake_mode == IntakeMode.BROWNFIELD
    assert result.change_set.changes
    for change in result.change_set.changes:
        assert change.target
        assert change.action
        assert change.evidence.summary
        assert change.authority_requirement
        assert change.status


def test_unknown_manifest_fields_remain_explicit() -> None:
    result = plan_adoption(inspect_project(GREENFIELD))
    manifest = result.manifest
    assert manifest.project.name is None
    assert manifest.project.work_modes is None
    assert manifest.execution.autonomy is None
    assert manifest.state.temporal_mode is None
    assert manifest.impact.reversibility is None
    assert manifest.assurance.required == []


def test_brownfield_keeps_authoritative_foundry_declaration() -> None:
    result = plan_adoption(inspect_project(BROWNFIELD))
    foundry_changes = [
        change
        for change in result.change_set.changes
        if change.target == "foundry-project-declaration"
    ]
    assert foundry_changes
    assert foundry_changes[0].action == AdoptionAction.KEEP
    assert all(change.action != AdoptionAction.MIGRATE for change in foundry_changes)


def test_inference_can_tighten_controls() -> None:
    result = plan_adoption(inspect_project(GREENFIELD))
    harden = [
        change
        for change in result.change_set.changes
        if change.action == AdoptionAction.HARDEN and change.target == "test-harness"
    ]
    assert harden
    assert harden[0].authority_requirement == AuthorityRequirement.NONE
    assert harden[0].status == AdoptionChangeStatus.AUTO_APPLICABLE


def test_inference_cannot_silently_widen_authority() -> None:
    widening_change = AdoptionChangeItem(
        target="execution.autonomy",
        action=AdoptionAction.DEFER,
        evidence=AdoptionEvidence(
            summary="Propose bounded-external-write autonomy",
            provenance=Provenance(kind=ProvenanceKind.INFERRED, confidence=0.6, source_ref="."),
        ),
        authority_requirement=AuthorityRequirement.NONE,
        status=AdoptionChangeStatus.AUTO_APPLICABLE,
    )
    with pytest.raises(AssertionError) as exc_info:
        assert_change_set_respects_authority(
            [widening_change],
            current_autonomy=Autonomy.SUGGEST,
            proposed_autonomy=proposed_autonomy_for_change(widening_change),
            current_external_effect=ExternalEffectClass.READ_ONLY,
            proposed_external_effect=proposed_external_effect_for_change(widening_change),
        )
    message = str(exc_info.value)
    assert "widens authority" in message


def test_brownfield_autonomy_widening_requires_explicit_authority() -> None:
    intake = inspect_project(BROWNFIELD)
    finding = ClassificationFinding(
        dimension="execution.autonomy",
        value=Autonomy.SUGGEST.value,
        provenance=Provenance(kind=ProvenanceKind.DECLARED, source_ref=".foundry/project.yaml"),
        evidence_refs=[".foundry/project.yaml"],
    )
    intake_with_autonomy = intake.model_copy(
        update={"classification_findings": [*intake.classification_findings, finding]}
    )
    result = plan_adoption(intake_with_autonomy)
    assert result.manifest.execution.autonomy == Autonomy.SUGGEST
    autonomy_changes = [
        change for change in result.change_set.changes if change.target == "execution.autonomy"
    ]
    assert autonomy_changes
    assert autonomy_changes[0].authority_requirement == AuthorityRequirement.EXPLICIT_AUTHORITY
    assert autonomy_changes[0].status != AdoptionChangeStatus.AUTO_APPLICABLE


def test_adopt_is_deterministic() -> None:
    intake = inspect_project(BROWNFIELD)
    first = dump_json(plan_adoption(intake))
    second = dump_json(plan_adoption(intake))
    assert first == second


@pytest.mark.parametrize("hash_seed", ["0", "1"])
@pytest.mark.parametrize("cwd", [REPO_ROOT, FIXTURES])
def test_adopt_deterministic_across_hash_seed_and_cwd(hash_seed: str, cwd: Path) -> None:
    env = {**_subprocess_env(), "PYTHONHASHSEED": hash_seed}
    script = (
        "from agent_foundry.inspect import inspect_project; "
        "from agent_foundry.adopt import plan_adoption; "
        "from agent_foundry.models import dump_json; "
        f"intake = inspect_project({str(BROWNFIELD)!r}); "
        "print(dump_json(plan_adoption(intake)).decode('utf-8'), end='')"
    )
    first = subprocess.run(
        [sys.executable, "-c", script],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    second = subprocess.run(
        [sys.executable, "-c", script],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert first.stdout == second.stdout


def test_adopt_does_not_mutate_greenfield_fixture_tree(tmp_path: Path) -> None:
    target = tmp_path / "project"
    shutil.copytree(GREENFIELD, target)
    before = _tree_digest(target)
    plan_adoption(inspect_project(target))
    after = _tree_digest(target)
    assert before == after


def test_adopt_does_not_mutate_brownfield_fixture_tree(tmp_path: Path) -> None:
    target = tmp_path / "project"
    shutil.copytree(BROWNFIELD, target)
    before = _tree_digest(target)
    plan_adoption(inspect_project(target))
    after = _tree_digest(target)
    assert before == after


def test_observed_conventions_are_not_promoted_to_normative_manifest_fields() -> None:
    result = plan_adoption(inspect_project(BROWNFIELD))
    for observation in result.manifest.observations:
        assert observation.provenance.kind != ProvenanceKind.NORMATIVE
    assert result.manifest.execution.autonomy is None


def test_cli_adopt_json(tmp_path: Path) -> None:
    target = tmp_path / "project"
    shutil.copytree(GREENFIELD, target)
    result = subprocess.run(
        [sys.executable, "-m", "agent_foundry", "adopt", str(target), "--format", "json"],
        cwd=REPO_ROOT,
        env=_subprocess_env(),
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert b'"change_set"' in result.stdout
    assert b'"manifest"' in result.stdout


def test_cli_help_lists_adopt() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "agent_foundry", "--help"],
        cwd=REPO_ROOT,
        env=_subprocess_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "adopt" in result.stdout


def test_blocker_readiness_produces_block_change() -> None:
    intake = _minimal_intake(
        classification_findings=[
            ClassificationFinding(
                dimension="intake_mode",
                value=IntakeMode.BROWNFIELD.value,
                provenance=Provenance(kind=ProvenanceKind.INFERRED, confidence=0.7, source_ref="."),
            )
        ],
        readiness_findings=[
            ReadinessFinding(
                dimension="repository-legibility",
                severity=ConsequenceClass.CRITICAL,
                message="Repository structure could not be established",
                blocker=True,
                provenance=Provenance(kind=ProvenanceKind.INFERRED, confidence=0.5, source_ref="."),
            )
        ],
    )
    result = plan_adoption(intake)
    blocked = [change for change in result.change_set.changes if change.action == AdoptionAction.BLOCK]
    assert blocked
    assert blocked[0].status == AdoptionChangeStatus.BLOCKED
