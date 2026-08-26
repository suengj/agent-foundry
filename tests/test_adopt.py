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
from agent_foundry.adopt.authority import (
    NON_AUTHORITY_TARGETS,
    assert_change_set_respects_authority,
    authority_axis_for_target,
    change_widens_authority,
    is_classified_target,
    widens_autonomy,
    widens_external_effect,
)
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
    ProjectObservation,
    ReadinessFinding,
    TraversalLimits,
    TraversalStats,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "projects"
GREENFIELD = FIXTURES / "greenfield-minimal"
BROWNFIELD = FIXTURES / "brownfield-sample"
MISSING_INTAKE_MODE = FIXTURES / "brownfield-missing-intake-mode"
MALFORMED_INTAKE_MODE = FIXTURES / "brownfield-malformed-intake-mode"
FOUNDRY_SCRATCH_ONLY = FIXTURES / "brownfield-foundry-scratch-only"
SINGLE_FILE_PYTEST = FIXTURES / "brownfield-single-file-pytest-mentions"
TWO_FILE_TEST_MENTIONS = FIXTURES / "brownfield-two-file-test-mentions"
REPO_ROOT = Path(__file__).resolve().parents[1]

ALL_FIXTURES = [
    GREENFIELD,
    BROWNFIELD,
    MISSING_INTAKE_MODE,
    MALFORMED_INTAKE_MODE,
    FOUNDRY_SCRATCH_ONLY,
    SINGLE_FILE_PYTEST,
    TWO_FILE_TEST_MENTIONS,
]


def _change_item(
    target: str,
    *,
    authority_requirement: AuthorityRequirement = AuthorityRequirement.NONE,
    status: AdoptionChangeStatus = AdoptionChangeStatus.AUTO_APPLICABLE,
) -> AdoptionChangeItem:
    return AdoptionChangeItem(
        target=target,
        action=AdoptionAction.MIGRATE,
        evidence=AdoptionEvidence(
            summary=f"synthetic change for {target}",
            provenance=Provenance(kind=ProvenanceKind.INFERRED, confidence=0.5, source_ref=None),
        ),
        authority_requirement=authority_requirement,
        status=status,
    )


def _assert_guard(change: AdoptionChangeItem, **overrides: object) -> None:
    kwargs: dict[str, object] = {
        "current_autonomy": None,
        "proposed_autonomy": proposed_autonomy_for_change(change),
        "current_external_effect": None,
        "proposed_external_effect": proposed_external_effect_for_change(change),
    }
    kwargs.update(overrides)
    assert_change_set_respects_authority([change], **kwargs)  # type: ignore[arg-type]


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
    """Inference may propose HARDEN, but a HARDEN that writes files is not self-authorizing."""
    result = plan_adoption(inspect_project(GREENFIELD))
    harden = [
        change
        for change in result.change_set.changes
        if change.action == AdoptionAction.HARDEN and change.target == "test-harness"
    ]
    assert harden
    assert harden[0].authority_requirement == AuthorityRequirement.BOUNDED_POLICY
    assert harden[0].status == AdoptionChangeStatus.PROPOSED


@pytest.mark.parametrize("fixture", [GREENFIELD, BROWNFIELD], ids=["greenfield", "brownfield"])
def test_repository_writing_test_harness_is_never_auto_applicable(fixture: Path) -> None:
    """`test-harness` HARDEN creates or edits repository files in both intake modes.

    Labelling it authority_requirement=none + auto-applicable claimed it could be
    applied with no owner review, while its file-creating siblings
    (`foundry-project-declaration`, `agent-instruction-surface`) were bounded-policy.
    """
    result = plan_adoption(inspect_project(fixture))
    harden = [change for change in result.change_set.changes if change.target == "test-harness"]
    assert harden, f"expected a test-harness change for {fixture.name}"
    for change in harden:
        assert change.action == AdoptionAction.HARDEN
        assert change.authority_requirement != AuthorityRequirement.NONE
        assert change.status != AdoptionChangeStatus.AUTO_APPLICABLE


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


def test_guard_rejects_unrecognised_authority_bearing_target() -> None:
    """A new authority-bearing target must be rejected, not ignored.

    The guard used to compare `change.target` against two literal strings, so any
    target it had never heard of passed unexamined. It now fails closed.
    """
    change = _change_item("execution.write-scope")
    assert authority_axis_for_target(change.target) is None
    assert not is_classified_target(change.target)
    with pytest.raises(AssertionError) as exc_info:
        _assert_guard(change)
    assert "widens authority" in str(exc_info.value)
    assert "not a reviewed adoption target" in str(exc_info.value)


def test_guard_recognises_external_effect_target_under_either_spelling() -> None:
    """`impact.external-effect` had zero emit sites and never matched the classifier field."""
    for target in ("impact.external-effect", "impact.external_effect"):
        change = _change_item(target)
        assert proposed_external_effect_for_change(change) == ExternalEffectClass.REPOSITORY_WRITE
        with pytest.raises(AssertionError) as exc_info:
            _assert_guard(change, current_external_effect=ExternalEffectClass.READ_ONLY)
        assert "impact.external_effect" in str(exc_info.value)


def test_guard_admits_reviewed_non_authority_targets() -> None:
    """Fail-closed must not turn every ordinary retention change into a violation."""
    for target in sorted(NON_AUTHORITY_TARGETS):
        _assert_guard(_change_item(target))
    _assert_guard(_change_item("readiness:repository-legibility"))


def test_unknown_current_autonomy_ranks_lowest() -> None:
    """AF2 leaves autonomy unknown by design, so unknown must not read as 'not widening'."""
    assert widens_autonomy(None, Autonomy.CONTINUOUS_OPERATION) is True
    assert widens_autonomy(None, Autonomy.SUGGEST) is True
    assert widens_autonomy(None, None) is False
    assert widens_autonomy(Autonomy.CONTINUOUS_OPERATION, Autonomy.SUGGEST) is False


def test_unknown_current_external_effect_ranks_lowest() -> None:
    assert widens_external_effect(None, ExternalEffectClass.PUBLICATION) is True
    assert widens_external_effect(None, ExternalEffectClass.READ_ONLY) is True
    assert widens_external_effect(None, None) is False
    assert widens_external_effect(ExternalEffectClass.PUBLICATION, ExternalEffectClass.READ_ONLY) is False


def test_guard_rejects_autonomy_widening_from_unknown_baseline() -> None:
    """Both guards previously failed open together; only emit ordering hid it."""
    change = _change_item("execution.autonomy")
    with pytest.raises(AssertionError) as exc_info:
        _assert_guard(change, current_autonomy=None)
    assert "execution.autonomy" in str(exc_info.value)


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
    assert autonomy_changes[0].evidence.evidence_refs, (
        "the autonomy proposal must name the test/CI evidence it rests on"
    )


def _declared_autonomy_intake(
    base: Path = BROWNFIELD,
    autonomy: Autonomy = Autonomy.SUGGEST,
) -> ProjectIntake:
    """Intake for a project whose owner has declared `execution.autonomy`.

    `brownfield-sample/.foundry/project.yaml` really does declare
    `execution.autonomy: suggest`, but AF2's classifier extracts only
    `project.intake_mode` from that file and emits every other dimension as
    unknown. So no on-disk fixture can reach `_authority_proposal_changes`, and
    `manifest.execution.autonomy` is None for all seven of them — which is exactly
    why this property test was vacuous. The declared finding is attached here
    rather than by widening AF2's classifier, which is out of scope for SUE-337.
    """
    intake = inspect_project(base)
    declared = ClassificationFinding(
        dimension="execution.autonomy",
        value=autonomy.value,
        provenance=Provenance(kind=ProvenanceKind.DECLARED, source_ref=".foundry/project.yaml"),
        evidence_refs=[".foundry/project.yaml"],
    )
    return intake.model_copy(
        update={"classification_findings": [*intake.classification_findings, declared]}
    )


def _planner_inputs() -> list[tuple[str, ProjectIntake]]:
    """Every intake the adoption property tests run over."""
    inputs = [(path.name, inspect_project(path)) for path in ALL_FIXTURES]
    inputs.append(("declared-suggest-autonomy", _declared_autonomy_intake()))
    return inputs


def _widening_changes(result: object) -> list[AdoptionChangeItem]:
    """Changes the guard considers authority-widening for this plan's baseline."""
    return [
        change
        for change in result.change_set.changes  # type: ignore[attr-defined]
        if change_widens_authority(
            change,
            current_autonomy=result.manifest.execution.autonomy,  # type: ignore[attr-defined]
            proposed_autonomy=proposed_autonomy_for_change(change),
            current_external_effect=result.manifest.impact.external_effect,  # type: ignore[attr-defined]
            proposed_external_effect=proposed_external_effect_for_change(change),
        )
    ]


def test_planner_corpus_actually_produces_an_authority_widening_change() -> None:
    """Anti-vacuity guard for the property test below.

    All seven on-disk fixtures emit ZERO authority-widening changes, so a property
    that only inspects widening changes passed no matter how they were labelled.
    If this assertion ever fails, the property test has gone vacuous again.
    """
    widening = {
        name: [change.target for change in _widening_changes(plan_adoption(intake))]
        for name, intake in _planner_inputs()
    }
    covered = {name: targets for name, targets in widening.items() if targets}
    assert covered, (
        "no planner input produces an authority-widening change, so "
        "test_planned_changes_are_never_both_widening_and_auto_applicable asserts nothing. "
        f"targets per input: {widening}"
    )
    assert "execution.autonomy" in {
        target for targets in covered.values() for target in targets
    }, f"expected an execution.autonomy widening change, got {covered}"


def test_planned_changes_are_never_both_widening_and_auto_applicable() -> None:
    """End-to-end property over real `plan_adoption` output, not a hand-built change.

    `test_inference_cannot_silently_widen_authority` constructs the change itself and
    calls the guard directly, so it proves nothing about what the planner emits.

    The `examined` assertion is load-bearing: without it this test passed while every
    input produced zero widening changes.
    """
    offenders: list[tuple[str, str, str, str]] = []
    examined: list[tuple[str, str]] = []

    for name, intake in _planner_inputs():
        result = plan_adoption(intake)
        assert result.change_set.changes, f"no changes planned for {name}"
        for change in _widening_changes(result):
            examined.append((name, change.target))
            if (
                change.authority_requirement == AuthorityRequirement.NONE
                or change.status == AdoptionChangeStatus.AUTO_APPLICABLE
            ):
                offenders.append(
                    (
                        name,
                        change.target,
                        change.authority_requirement.value,
                        change.status.value,
                    )
                )

    assert examined, (
        "vacuous: no planner input produced an authority-widening change to check"
    )
    assert offenders == [], (
        f"authority-widening changes labelled as needing no authority or as "
        f"auto-applicable: {offenders}"
    )


ARTIFACT_PRODUCING_ACTIONS: frozenset[AdoptionAction] = frozenset(
    {
        AdoptionAction.MIGRATE,
        AdoptionAction.HARDEN,
        AdoptionAction.CONSOLIDATE,
        AdoptionAction.WRAP,
    }
)
"""Actions that can only be carried out by writing to the repository.

KEEP retains what is already there, DEFER defers, BLOCK blocks — none of those
touch a file, which is why they may legitimately be auto-applicable.
"""


def test_artifact_producing_changes_are_never_auto_applicable() -> None:
    """An adoption change that must write files may not claim it needs no authority.

    Derived from the change's ACTION rather than from the label under test, so it
    is not a restatement of what each `_change(...)` call site already says.
    AGENTS.md defaults external writes to preview -> explicit apply.
    """
    offenders: list[tuple[str, str, str, str, str]] = []
    examined: list[tuple[str, str]] = []

    for name, intake in _planner_inputs():
        for change in plan_adoption(intake).change_set.changes:
            if change.action not in ARTIFACT_PRODUCING_ACTIONS:
                continue
            examined.append((name, change.target))
            if (
                change.authority_requirement == AuthorityRequirement.NONE
                or change.status == AdoptionChangeStatus.AUTO_APPLICABLE
            ):
                offenders.append(
                    (
                        name,
                        change.target,
                        change.action.value,
                        change.authority_requirement.value,
                        change.status.value,
                    )
                )

    assert examined, "vacuous: no planner input produced an artifact-producing change"
    assert offenders == [], (
        f"changes that write repository files but are labelled as needing no "
        f"authority or as auto-applicable: {offenders}"
    )


def test_every_planned_target_is_classified_by_the_authority_guard() -> None:
    """A new `_change(...)` call site must be classified, not silently unreviewed."""
    unclassified: dict[str, list[str]] = {}
    seen: set[str] = set()

    for name, intake in _planner_inputs():
        targets = {change.target for change in plan_adoption(intake).change_set.changes}
        seen |= targets
        unknown = sorted(target for target in targets if not is_classified_target(target))
        if unknown:
            unclassified[name] = unknown

    assert seen, "no targets produced by any planner input"
    assert unclassified == {}, (
        f"targets unknown to the authority guard: {unclassified}. "
        "Add them to NON_AUTHORITY_TARGETS or to an AuthorityAxis."
    )


def test_adopt_is_deterministic() -> None:
    intake = inspect_project(BROWNFIELD)
    first = dump_json(plan_adoption(intake))
    second = dump_json(plan_adoption(intake))
    assert first == second


def test_adopt_deterministic_across_hash_seed_and_cwd() -> None:
    """Compare output ACROSS hash seeds and working directories, not within one pair.

    The parametrized form ran both subprocesses with the same env and cwd, so it
    only ever proved a run equals itself.
    """
    script = (
        "from agent_foundry.inspect import inspect_project; "
        "from agent_foundry.adopt import plan_adoption; "
        "from agent_foundry.models import dump_json; "
        f"intake = inspect_project({str(BROWNFIELD)!r}); "
        "print(dump_json(plan_adoption(intake)).decode('utf-8'), end='')"
    )
    outputs: dict[tuple[str, str], str] = {}
    for hash_seed in ("0", "1"):
        for cwd in (REPO_ROOT, FIXTURES):
            completed = subprocess.run(
                [sys.executable, "-c", script],
                cwd=cwd,
                env={**_subprocess_env(), "PYTHONHASHSEED": hash_seed},
                capture_output=True,
                text=True,
                check=True,
            )
            outputs[(hash_seed, str(cwd))] = completed.stdout

    assert len(outputs) == 4
    distinct = set(outputs.values())
    assert len(distinct) == 1, (
        "adopt output varied across PYTHONHASHSEED/cwd: "
        f"{sorted(key for key, value in outputs.items() if value != next(iter(distinct)))}"
    )
    assert distinct.pop().strip(), "expected non-empty adopt output"


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


def test_unknown_intake_mode_not_planned_as_greenfield() -> None:
    result = plan_adoption(inspect_project(MISSING_INTAKE_MODE))
    assert result.manifest.project.intake_mode is None
    assert result.change_set.intake_mode is None
    assert result.change_set.intake_mode != IntakeMode.GREENFIELD
    keep_targets = {
        change.target
        for change in result.change_set.changes
        if change.action == AdoptionAction.KEEP
    }
    assert "foundry-project-declaration" in keep_targets
    assert "package-metadata" in keep_targets
    assert "runtime-deploy" in keep_targets
    blocked = [change for change in result.change_set.changes if change.target == "intake-mode"]
    assert blocked
    assert blocked[0].action == AdoptionAction.BLOCK


def test_cli_adopt_missing_intake_mode_not_greenfield(tmp_path: Path) -> None:
    target = tmp_path / "project"
    shutil.copytree(MISSING_INTAKE_MODE, target)
    result = subprocess.run(
        [sys.executable, "-m", "agent_foundry", "adopt", str(target), "--format", "json"],
        cwd=REPO_ROOT,
        env=_subprocess_env(),
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    payload = result.stdout.decode("utf-8")
    assert '"intake_mode":null' in payload.replace(" ", "")
    assert '"intake_mode":"greenfield"' not in payload.replace(" ", "")
    assert '"target":"foundry-project-declaration"' in payload.replace(" ", "")
    assert '"action":"KEEP"' in payload.replace(" ", "")


def test_malformed_declared_intake_mode_surfaces_readiness_finding() -> None:
    result = plan_adoption(inspect_project(MALFORMED_INTAKE_MODE))
    invalid = [
        finding
        for finding in result.manifest.readiness_findings
        if finding.dimension == "declared-value-invalid"
    ]
    assert invalid
    assert "brown-field" in invalid[0].message
    assert ".foundry/project.yaml" in invalid[0].message
    assert result.manifest.project.intake_mode is None
    assert result.change_set.intake_mode is None


def test_observed_foundry_artifact_not_stamped_declared() -> None:
    result = plan_adoption(inspect_project(FOUNDRY_SCRATCH_ONLY))
    foundry_changes = [
        change
        for change in result.change_set.changes
        if change.target.startswith("foundry-")
    ]
    assert foundry_changes
    assert all(
        change.evidence.provenance.kind != ProvenanceKind.DECLARED for change in foundry_changes
    )
    assert foundry_changes[0].target == "foundry-artifact-surfaces"
    assert foundry_changes[0].evidence.provenance.kind == ProvenanceKind.OBSERVED
    assert ".foundry/scratch-notes.txt" in foundry_changes[0].evidence.evidence_refs


def test_change_set_never_fabricates_evidence_refs() -> None:
    intake = _minimal_intake(
        classification_findings=[
            ClassificationFinding(
                dimension="intake_mode",
                value=IntakeMode.BROWNFIELD.value,
                provenance=Provenance(kind=ProvenanceKind.INFERRED, confidence=0.7, source_ref="."),
            )
        ],
        observations=[
            ProjectObservation(
                subject="foundry-declaration",
                content="project.yaml present with owner-declared characteristics",
                provenance=Provenance(kind=ProvenanceKind.DECLARED, source_ref=None),
            ),
            ProjectObservation(
                subject="package-metadata",
                content="package/build metadata file present: pyproject.toml",
                provenance=Provenance(kind=ProvenanceKind.OBSERVED, source_ref="pyproject.toml"),
            ),
        ],
    )
    result = plan_adoption(intake)
    for change in result.change_set.changes:
        assert ".foundry/project.yaml" not in change.evidence.evidence_refs
    foundry_changes = [
        change
        for change in result.change_set.changes
        if change.target == "foundry-project-declaration"
    ]
    assert not foundry_changes


def test_change_evidence_carries_a_real_source_ref_or_none() -> None:
    """`source_ref` defaulted to '.' for every change, asserting root-level evidence.

    A change with no located source must say so with None rather than point at the
    repository root as if the root were the evidence.
    """
    result = plan_adoption(inspect_project(BROWNFIELD))
    located = {
        change.target: change.evidence.provenance.source_ref
        for change in result.change_set.changes
        if change.evidence.evidence_refs
    }
    assert located, "expected at least one change with located evidence"
    for target, source_ref in located.items():
        assert source_ref is not None, f"{target} has evidence refs but no source_ref"
        assert source_ref != ".", f"{target} still reports the fabricated '.' source_ref"


def test_observed_test_entrypoints_are_cited_by_the_harden_change() -> None:
    """The brownfield HARDEN change claimed 'existing test entrypoints' and cited none."""
    result = plan_adoption(inspect_project(BROWNFIELD))
    harden = [change for change in result.change_set.changes if change.target == "test-harness"]
    assert harden
    assert harden[0].evidence.evidence_refs, "HARDEN must cite the entrypoints it strengthens"


def test_every_fragmentation_finding_produces_a_change() -> None:
    """Only `fragmentation[0]` was used, so any further finding was silently dropped."""
    findings = [
        ClassificationFinding(
            dimension="agent-rule-fragmentation",
            value="multiple-instruction-surfaces",
            provenance=Provenance(
                kind=ProvenanceKind.OBSERVED, confidence=1.0, source_ref="AGENTS.md"
            ),
            evidence_refs=["AGENTS.md", "CLAUDE.md"],
        ),
        ClassificationFinding(
            dimension="agent-rule-fragmentation",
            value="conflicting-instruction-surfaces",
            provenance=Provenance(
                kind=ProvenanceKind.OBSERVED, confidence=0.8, source_ref="docs/rules.md"
            ),
            evidence_refs=["docs/rules.md"],
        ),
        ClassificationFinding(
            dimension="intake_mode",
            value=IntakeMode.BROWNFIELD.value,
            provenance=Provenance(kind=ProvenanceKind.INFERRED, confidence=0.7, source_ref="."),
        ),
    ]
    result = plan_adoption(_minimal_intake(classification_findings=findings))
    consolidations = [
        change
        for change in result.change_set.changes
        if change.target == "agent-instruction-surfaces"
    ]
    assert len(consolidations) == 2, (
        f"expected one change per fragmentation finding, got {len(consolidations)}"
    )
    cited = {ref for change in consolidations for ref in change.evidence.evidence_refs}
    assert cited == {"AGENTS.md", "CLAUDE.md", "docs/rules.md"}
    assert {change.evidence.provenance.source_ref for change in consolidations} == {
        "AGENTS.md",
        "docs/rules.md",
    }


def test_single_file_pytest_mentions_do_not_claim_runner_conflict() -> None:
    result = plan_adoption(inspect_project(SINGLE_FILE_PYTEST))
    conflict_claims = [
        change
        for change in result.change_set.changes
        if "conflicting test runner" in change.evidence.summary.lower()
        or change.target == "test-runner"
    ]
    assert not conflict_claims


def test_two_file_test_mentions_still_produce_reconciliation_change() -> None:
    result = plan_adoption(inspect_project(TWO_FILE_TEST_MENTIONS))
    reconcile = [
        change
        for change in result.change_set.changes
        if change.target == "instruction-surface-mentions"
    ]
    assert reconcile
    assert reconcile[0].action == AdoptionAction.CONSOLIDATE
    assert "reconciled" in reconcile[0].evidence.summary.lower()


def test_declared_source_ref_survives_empty_evidence_refs() -> None:
    """The ternary bound as (a or b) if refs else '.', discarding a set source_ref."""
    from agent_foundry.adopt.manifest import synthesize_manifest
    from agent_foundry.models import (
        ClassificationFinding, Provenance, ProvenanceKind, ProjectIntake,
        TraversalStats, TraversalLimits,
    )

    intake = ProjectIntake(
        schema_version="0.1",
        project_root=".",
        classification_findings=[
            ClassificationFinding(
                dimension="intake_mode",
                value="brown-field",
                provenance=Provenance(
                    kind=ProvenanceKind.DECLARED, source_ref=".foundry/project.yaml"
                ),
                evidence_refs=[],
            )
        ],
        traversal_stats=TraversalStats(
            entries_visited=0, entries_skipped=0, depth_limit_reached=False,
            entry_limit_reached=False,
            limits=TraversalLimits(max_depth=1, max_entries=1, max_file_bytes=1),
        ),
    )
    manifest = synthesize_manifest(intake)
    invalid = [
        f for f in manifest.readiness_findings
        if f.dimension == "declared-value-invalid"
    ]
    assert invalid, "expected a declared-value-invalid finding"
    assert ".foundry/project.yaml" in invalid[0].message
    assert invalid[0].provenance.source_ref == ".foundry/project.yaml"


def test_blocking_change_sorts_first_despite_zero_priority() -> None:
    """`item.priority or 99` sent priority=0 to the bottom, under auto-applicable items."""
    from agent_foundry.adopt import plan_adoption
    from agent_foundry.inspect import inspect_project

    fixture = FIXTURES / "brownfield-missing-intake-mode"
    changes = plan_adoption(inspect_project(str(fixture))).change_set.changes
    assert changes, "expected changes"
    assert changes[0].target == "intake-mode", (
        f"BLOCK should sort first, got {[c.target for c in changes]}"
    )
