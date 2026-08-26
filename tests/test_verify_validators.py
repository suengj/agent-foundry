"""Pass and fail cases for every AF7 validator.

Each validator is exercised twice at minimum: once against an artifact that should
be accepted, and once against one that should not. The mutation tests that prove a
validator does not merely echo its producer live in `test_verify_mutations.py`.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from agent_foundry.models import (
    DependencyRelation,
    DependencySpec,
    EvidenceClass,
    EvidenceItem,
    EvidenceResult,
    EvidenceState,
    ExternalEffectClass,
    ExecutionState,
    IntegrationHealthState,
    Provenance,
    ProvenanceKind,
    ValidationOutcome,
    WorkLifecycleState,
)
from agent_foundry.models.base import FOUNDRY_SCHEMA_VERSION
from agent_foundry.models.interaction import EvidenceBundle
from agent_foundry.verify import (
    validate_authority_ceiling,
    validate_evidence_bundle_completeness,
    validate_execution_bundle_completeness,
    validate_integration_preflight,
    validate_lifecycle_separation,
    validate_provenance_completeness,
    validate_receipt_completeness,
    validate_required_evidence,
    validate_role_separation,
    validate_contract_schema_compatibility,
    validate_toolkit_coherence,
    validate_work_dependency_graph,
    validate_write_scope_containment,
)
from agent_foundry.verify.receipt import receipt_artifacts
from verify_support import (
    CANDIDATE_REVISION,
    FINISHED_AT,
    approving_review,
    compiled,
    complete_receipt,
    full_evidence_bundle,
    health,
    integration_spec,
    sample_work_item,
)


def _outcomes(report) -> set[ValidationOutcome]:
    return {finding.outcome for finding in report.findings}


def _messages(report) -> str:
    return " | ".join(finding.message for finding in report.findings)


# --- schema / version compatibility ------------------------------------------


def test_schema_compatibility_accepts_current_contracts():
    artifacts = compiled()
    report = validate_contract_schema_compatibility(
        [
            ("work-item", artifacts["work_item"]),
            ("execution-bundle", artifacts["bundle"]),
            ("toolkit-lock", artifacts["lock"]),
            ("registry", artifacts["registry"]),
        ]
    )
    assert report.accepted()


def test_schema_compatibility_rejects_a_newer_minor():
    artifacts = compiled()
    forged = artifacts["work_item"].model_construct(
        **{**artifacts["work_item"].__dict__, "schema_version": "0.9"}
    )
    report = validate_contract_schema_compatibility([("work-item", forged)])
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "newer than supported" in _messages(report)


def test_schema_compatibility_rejects_a_major_mismatch_and_a_bad_compat_clause():
    artifacts = compiled()
    forged_major = artifacts["work_item"].model_construct(
        **{**artifacts["work_item"].__dict__, "schema_version": "9.0"}
    )
    assert validate_contract_schema_compatibility([("work-item", forged_major)]).outcome() == (
        ValidationOutcome.BLOCKED
    )

    lock = artifacts["lock"]
    forged_compat = lock.model_construct(**{**lock.__dict__, "foundry_compat": ">=99.0"})
    report = validate_contract_schema_compatibility([("lock", forged_compat)])
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "excludes running version" in _messages(report)


def test_schema_compatibility_reports_missing_rather_than_passing_on_no_input():
    report = validate_contract_schema_compatibility([])
    assert report.outcome() == ValidationOutcome.MISSING
    assert not report.accepted()


# --- work dependency graph ----------------------------------------------------


def _item(item_id: str, *deps: tuple[DependencyRelation, str]):
    return sample_work_item(
        id=item_id,
        dependencies=[
            DependencySpec(relation=relation, target_id=target) for relation, target in deps
        ],
    )


def test_dependency_graph_accepts_an_acyclic_plan():
    items = [
        _item("WI-1"),
        _item("WI-2", (DependencyRelation.REQUIRES, "WI-1")),
        _item("WI-3", (DependencyRelation.APPLIES_AFTER, "WI-2")),
    ]
    assert validate_work_dependency_graph(items).accepted()


def test_dependency_graph_rejects_a_cycle():
    items = [
        _item("WI-1", (DependencyRelation.REQUIRES, "WI-2")),
        _item("WI-2", (DependencyRelation.REQUIRES, "WI-1")),
    ]
    report = validate_work_dependency_graph(items)
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "circular dependency" in _messages(report)


def test_dependency_graph_rejects_a_cycle_formed_through_blocks():
    items = [
        _item("WI-1", (DependencyRelation.BLOCKS, "WI-2")),
        _item("WI-2", (DependencyRelation.REQUIRES, "WI-1")),
        _item("WI-3", (DependencyRelation.REQUIRES, "WI-2")),
    ]
    # WI-1 blocks WI-2 means WI-2 depends on WI-1; WI-2 also requires WI-1. No cycle.
    assert validate_work_dependency_graph(items).accepted()

    contradicting = [
        _item("WI-1", (DependencyRelation.BLOCKS, "WI-2")),
        _item("WI-2", (DependencyRelation.BLOCKS, "WI-1")),
    ]
    report = validate_work_dependency_graph(contradicting)
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "block the other" in _messages(report)


def test_dependency_graph_rejects_dangling_duplicate_and_self_references():
    dangling = validate_work_dependency_graph([_item("WI-1", (DependencyRelation.REQUIRES, "WI-X"))])
    assert dangling.outcome() == ValidationOutcome.BLOCKED
    assert "not in this plan" in _messages(dangling)

    duplicates = validate_work_dependency_graph([_item("WI-1"), _item("WI-1")])
    assert duplicates.outcome() == ValidationOutcome.BLOCKED
    assert "appears 2 times" in _messages(duplicates)

    self_ref = validate_work_dependency_graph([_item("WI-1", (DependencyRelation.REQUIRES, "WI-1"))])
    assert self_ref.outcome() == ValidationOutcome.BLOCKED
    assert "on itself" in _messages(self_ref)


def test_dependency_graph_on_an_empty_plan_is_missing_not_pass():
    report = validate_work_dependency_graph([])
    assert report.outcome() == ValidationOutcome.MISSING


# --- toolkit coherence --------------------------------------------------------


def test_toolkit_coherence_accepts_a_resolved_task_toolkit():
    artifacts = compiled()
    report = validate_toolkit_coherence(
        artifacts["task_toolkit"], artifacts["lock"], artifacts["registry"]
    )
    assert report.accepted(), _messages(report)


def test_toolkit_coherence_rejects_a_capability_outside_the_lock():
    artifacts = compiled()
    task = artifacts["task_toolkit"]
    forged = task.model_copy(update={"capability_ids": [*task.capability_ids, "runtime.verify"]})
    report = validate_toolkit_coherence(forged, artifacts["lock"], artifacts["registry"])
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "not in the pinned project lock" in _messages(report)


def test_toolkit_coherence_rejects_an_unpinned_selection_and_an_orphan_pin():
    artifacts = compiled()
    lock = artifacts["lock"]
    unpinned = lock.model_copy(update={"skill_versions": {}})
    report = validate_toolkit_coherence(artifacts["task_toolkit"], unpinned, artifacts["registry"])
    assert ValidationOutcome.MISSING in _outcomes(report)
    assert "without pinning a version" in _messages(report)

    orphan = lock.model_copy(
        update={"skill_versions": {**lock.skill_versions, "not-selected": "1.0.0"}}
    )
    orphan_report = validate_toolkit_coherence(
        artifacts["task_toolkit"], orphan, artifacts["registry"]
    )
    assert orphan_report.outcome() == ValidationOutcome.BLOCKED
    assert "which it does not select" in _messages(orphan_report)


def test_toolkit_coherence_rejects_a_skill_whose_capability_is_absent():
    artifacts = compiled()
    task = artifacts["task_toolkit"]
    stripped = task.model_copy(
        update={"capability_ids": [c for c in task.capability_ids if c != "repository.read"]}
    )
    report = validate_toolkit_coherence(stripped, artifacts["lock"], artifacts["registry"])
    assert not report.accepted()
    assert "requires capability" in _messages(report)


# --- authority ceiling --------------------------------------------------------


def _ceiling_report(artifacts, authority):
    return validate_authority_ceiling(
        authority,
        work_item=artifacts["work_item"],
        manifest=artifacts["manifest"],
        task_toolkit=artifacts["task_toolkit"],
        role=artifacts["role"],
        permission_profile=artifacts["permission_profile"],
        registry=artifacts["registry"],
    )


def test_authority_ceiling_accepts_a_compiled_authority():
    artifacts = compiled()
    report = _ceiling_report(artifacts, artifacts["bundle"].authority)
    assert report.accepted(), _messages(report)


def test_authority_ceiling_rejects_authority_above_the_work_item_class():
    artifacts = compiled()
    forged = artifacts["bundle"].authority.model_copy(
        update={"external_effect": ExternalEffectClass.PUBLICATION}
    )
    report = _ceiling_report(artifacts, forged)
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "exceeds the work item authority class" in _messages(report)


def test_authority_ceiling_rejects_read_only_authority_carrying_write_scope():
    artifacts = compiled()
    forged = artifacts["bundle"].authority.model_copy(
        update={"external_effect": ExternalEffectClass.READ_ONLY, "write_scope": ["src"]}
    )
    report = _ceiling_report(artifacts, forged)
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "read-only authority carries write scope" in _messages(report)


def test_authority_ceiling_treats_an_absent_permission_profile_as_unproven():
    artifacts = compiled()
    report = validate_authority_ceiling(
        artifacts["bundle"].authority,
        work_item=artifacts["work_item"],
        manifest=artifacts["manifest"],
        task_toolkit=artifacts["task_toolkit"],
        role=artifacts["role"],
        permission_profile=None,
        registry=artifacts["registry"],
    )
    assert report.outcome() == ValidationOutcome.MISSING
    assert not report.accepted()


def test_authority_ceiling_treats_an_undeclared_manifest_effect_as_read_only():
    artifacts = compiled()
    manifest = artifacts["manifest"].model_copy(
        update={"impact": artifacts["manifest"].impact.model_copy(update={"external_effect": None})}
    )
    report = validate_authority_ceiling(
        artifacts["bundle"].authority,
        work_item=artifacts["work_item"],
        manifest=manifest,
        task_toolkit=artifacts["task_toolkit"],
        role=artifacts["role"],
        permission_profile=artifacts["permission_profile"],
        registry=artifacts["registry"],
    )
    assert not report.accepted()
    assert "declares no external effect" in _messages(report)


# --- write scope containment ---------------------------------------------------


def test_write_scope_containment_accepts_a_compiled_scope():
    artifacts = compiled()
    report = validate_write_scope_containment(
        artifacts["bundle"].authority,
        work_item=artifacts["work_item"],
        role=artifacts["role"],
    )
    assert report.accepted(), _messages(report)


@pytest.mark.parametrize(
    ("scope", "expected_fragment"),
    [
        (["src/../../etc"], "does not resolve"),
        (["/etc/passwd"], "does not resolve"),
        (["C:/repo/src"], "does not resolve"),
        (["docs"], "not inside the work item scope"),
    ],
)
def test_write_scope_containment_rejects_escaping_bounds(scope, expected_fragment):
    artifacts = compiled()
    forged = artifacts["bundle"].authority.model_copy(
        update={"write_scope": scope, "forbidden_scopes": []}
    )
    report = validate_write_scope_containment(
        forged, work_item=artifacts["work_item"], role=artifacts["role"]
    )
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert expected_fragment in _messages(report)


def test_write_scope_containment_rejects_a_path_both_granted_and_forbidden():
    artifacts = compiled()
    forged = artifacts["bundle"].authority.model_copy(
        update={"write_scope": ["src"], "forbidden_scopes": ["src/"]}
    )
    report = validate_write_scope_containment(
        forged, work_item=artifacts["work_item"], role=artifacts["role"]
    )
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "both granted and forbidden" in _messages(report)


def test_write_scope_containment_without_a_role_is_missing_not_pass():
    artifacts = compiled()
    report = validate_write_scope_containment(
        artifacts["bundle"].authority, work_item=artifacts["work_item"], role=None
    )
    assert report.outcome() == ValidationOutcome.MISSING


# --- role separation ------------------------------------------------------------


def test_role_separation_accepts_disjoint_roles():
    builder = compiled("builder")["bundle"]
    # A reviewer bundle for the same run: same work, no write authority of its own.
    reviewer = builder.model_copy(
        update={
            "role_id": "reviewer",
            "write_scope": [],
            "authority": builder.authority.model_copy(
                update={"write_scope": [], "forbidden_scopes": []}
            ),
        }
    )
    report = validate_role_separation([builder, reviewer], review_decisions=[approving_review()])
    assert report.accepted(), _messages(report)


def test_role_separation_rejects_overlapping_write_scope():
    builder = compiled("builder")["bundle"]
    other = builder.model_copy(update={"role_id": "integrator"})
    report = validate_role_separation([builder, other])
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "overlapping write scope" in _messages(report)


def test_role_separation_rejects_a_review_only_role_holding_write_authority():
    builder = compiled("builder")["bundle"]
    forged = builder.model_copy(update={"role_id": "reviewer"})
    report = validate_role_separation([forged])
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "review-only role" in _messages(report)


def test_role_separation_rejects_a_self_review():
    builder = compiled("builder")["bundle"]
    self_review = approving_review().model_construct(
        **{
            **approving_review().__dict__,
            "reviewer_role": "builder",
            "implementing_role_id": "builder",
        }
    )
    report = validate_role_separation([builder], review_decisions=[self_review])
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "reviewed its own implementation" in _messages(report)


def test_role_separation_reports_missing_when_independence_is_unstated():
    builder = compiled("builder")["bundle"]
    anonymous = approving_review().model_copy(update={"implementing_role_id": None})
    report = validate_role_separation([builder], review_decisions=[anonymous])
    assert ValidationOutcome.MISSING in _outcomes(report)
    assert "independence is unproven" in _messages(report)


# --- integration preflight -------------------------------------------------------


def test_integration_preflight_accepts_an_authorized_observation():
    spec = integration_spec()
    report = validate_integration_preflight(
        [spec],
        required_ids=["work-tracker"],
        observed_health=[health("work-tracker", IntegrationHealthState.AUTHORIZED)],
    )
    assert report.accepted(), _messages(report)


def test_integration_preflight_treats_an_unobserved_integration_as_missing():
    report = validate_integration_preflight(
        [integration_spec()], required_ids=["work-tracker"], observed_health=[]
    )
    assert report.outcome() == ValidationOutcome.MISSING
    assert "unobserved is not healthy" in _messages(report)


def test_integration_preflight_requires_auth_evidence_not_just_configuration():
    report = validate_integration_preflight(
        [integration_spec()],
        required_ids=["work-tracker"],
        observed_health=[health("work-tracker", IntegrationHealthState.CONFIGURED)],
    )
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "not positive evidence of authentication" in _messages(report)


def test_integration_preflight_rejects_an_auth_requiring_spec_without_an_auth_block():
    report = validate_integration_preflight(
        [integration_spec(with_auth=False)],
        required_ids=["work-tracker"],
        observed_health=[health("work-tracker", IntegrationHealthState.AUTHORIZED)],
    )
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "declares no auth block" in _messages(report)


def test_integration_preflight_rejects_an_undeclared_integration():
    report = validate_integration_preflight([], required_ids=["work-tracker"])
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "is not declared" in _messages(report)


def test_integration_preflight_flags_a_stale_observation():
    report = validate_integration_preflight(
        [integration_spec()],
        required_ids=["work-tracker"],
        observed_health=[health("work-tracker", IntegrationHealthState.AUTHORIZED)],
        now=FINISHED_AT + timedelta(hours=6),
        max_observation_age=timedelta(minutes=30),
    )
    assert ValidationOutcome.MISSING in _outcomes(report)
    assert "stale reading is not a current one" in _messages(report)


def test_integration_preflight_returns_not_required_only_when_nothing_is_required():
    report = validate_integration_preflight([], required_ids=[])
    assert report.outcome() == ValidationOutcome.NOT_REQUIRED
    assert report.accepted()


def test_integration_preflight_flags_an_observation_without_a_timestamp():
    report = validate_integration_preflight(
        [integration_spec()],
        required_ids=["work-tracker"],
        observed_health=[
            health("work-tracker", IntegrationHealthState.AUTHORIZED, checked_at=None)
        ],
    )
    assert ValidationOutcome.MISSING in _outcomes(report)
    assert "freshness cannot be established" in _messages(report)


# --- required evidence classes ----------------------------------------------------


def test_required_evidence_accepts_typed_passing_evidence():
    work_item = sample_work_item()
    report = validate_required_evidence(work_item, full_evidence_bundle())
    assert report.accepted(), _messages(report)


def test_required_evidence_is_missing_without_a_bundle():
    report = validate_required_evidence(sample_work_item(), None)
    assert report.outcome() == ValidationOutcome.MISSING
    assert not report.accepted()


def test_required_evidence_does_not_accept_untyped_evidence():
    bundle = full_evidence_bundle(
        items=[
            EvidenceItem(kind="test-report", ref="artifacts/pytest.log"),
            EvidenceItem(kind="diff", ref="artifacts/change.diff"),
        ]
    )
    report = validate_required_evidence(sample_work_item(), bundle)
    assert report.outcome() == ValidationOutcome.MISSING
    assert "no passing evidence item declares class" in _messages(report)


def test_required_evidence_does_not_accept_a_failing_result():
    bundle = full_evidence_bundle(
        items=[
            EvidenceItem(
                kind="test-report",
                ref="artifacts/pytest.log",
                evidence_class=EvidenceClass.DETERMINISTIC_TEST,
                result=EvidenceResult.FAIL,
                proves_revision=CANDIDATE_REVISION,
            )
        ]
    )
    report = validate_required_evidence(sample_work_item(), bundle)
    assert report.outcome() == ValidationOutcome.MISSING


def test_required_evidence_rejects_a_requirement_the_bundle_also_declares_exempt():
    bundle = full_evidence_bundle(not_required_classes=[EvidenceClass.DETERMINISTIC_TEST])
    report = validate_required_evidence(sample_work_item(), bundle)
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "both required" in _messages(report)


def test_required_evidence_treats_an_unrecognised_requirement_as_missing():
    work_item = sample_work_item(required_evidence=["vibes"])
    report = validate_required_evidence(work_item, full_evidence_bundle())
    assert report.outcome() == ValidationOutcome.MISSING
    assert "does not name a known evidence class" in _messages(report)


def test_required_evidence_reports_missing_when_the_work_item_declares_none():
    work_item = sample_work_item(required_evidence=[])
    report = validate_required_evidence(work_item, full_evidence_bundle())
    assert report.outcome() == ValidationOutcome.MISSING
    assert "is unspecified" in _messages(report)


def test_required_evidence_needs_the_evidence_to_name_a_revision():
    bundle = full_evidence_bundle(
        items=[
            EvidenceItem(
                kind="test-report",
                ref="artifacts/pytest.log",
                evidence_class=EvidenceClass.DETERMINISTIC_TEST,
                result=EvidenceResult.PASS,
            ),
            EvidenceItem(
                kind="diff",
                ref="artifacts/change.diff",
                evidence_class=EvidenceClass.REPOSITORY_REVISION,
                result=EvidenceResult.PASS,
                proves_revision=CANDIDATE_REVISION,
            ),
        ]
    )
    report = validate_required_evidence(sample_work_item(), bundle)
    assert ValidationOutcome.MISSING in _outcomes(report)
    assert "names no revision it proves" in _messages(report)


# --- evidence bundle completeness ---------------------------------------------------


def test_evidence_bundle_completeness_accepts_a_full_bundle():
    assert validate_evidence_bundle_completeness(full_evidence_bundle()).accepted()


def test_evidence_bundle_completeness_rejects_a_bundle_without_identity_or_items():
    empty = EvidenceBundle(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        work_item_id="WI-VERIFY-001",
        run_id="RUN-VERIFY-001",
    )
    report = validate_evidence_bundle_completeness(empty)
    assert report.outcome() == ValidationOutcome.MISSING
    assert "names no revision identity" in _messages(report)
    assert "carries no items" in _messages(report)


def test_evidence_bundle_completeness_rejects_a_class_both_exempt_and_evidenced():
    bundle = full_evidence_bundle()
    forged = bundle.model_construct(
        **{**bundle.__dict__, "not_required_classes": [EvidenceClass.DETERMINISTIC_TEST]}
    )
    report = validate_evidence_bundle_completeness(forged)
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "declared not-required but also has passing evidence" in _messages(report)


# --- provenance completeness -----------------------------------------------------


def test_provenance_completeness_accepts_a_compiled_bundle():
    report = validate_provenance_completeness(compiled()["bundle"])
    assert report.accepted(), _messages(report)


def test_provenance_completeness_rejects_an_inferred_envelope_without_confidence():
    from agent_foundry.models import ProjectObservation

    observation = ProjectObservation(
        subject="test-harness",
        content="pytest entrypoint inferred",
        provenance=Provenance(kind=ProvenanceKind.INFERRED, source_ref="pyproject.toml"),
    )
    report = validate_provenance_completeness(observation)
    assert report.outcome() == ValidationOutcome.MISSING
    assert "carries no confidence" in _messages(report)


def test_provenance_completeness_rejects_a_selection_record_without_a_cause():
    artifacts = compiled()
    bundle = artifacts["bundle"]
    stripped = [
        record.model_copy(update={"project_fact": None, "policy_id": None})
        for record in bundle.provenance[:1]
    ]
    forged = bundle.model_copy(update={"provenance": stripped})
    report = validate_provenance_completeness(forged)
    assert report.outcome() == ValidationOutcome.MISSING
    assert "cites neither a project fact nor a policy id" in _messages(report)


def test_provenance_completeness_reports_missing_on_a_payload_with_no_provenance():
    """Stripping the bundle's own list is not enough — the nested toolkit still explains itself."""
    artifacts = compiled()
    bundle = artifacts["bundle"]
    stripped_toolkit = bundle.task_toolkit.model_copy(update={"decisions": []})
    partially_stripped = bundle.model_copy(update={"provenance": []})
    assert validate_provenance_completeness(partially_stripped).accepted()

    forged = bundle.model_copy(update={"provenance": [], "task_toolkit": stripped_toolkit})
    report = validate_provenance_completeness(forged)
    assert report.outcome() == ValidationOutcome.MISSING
    assert "untraceable" in _messages(report)


# --- execution bundle completeness -------------------------------------------------


def test_execution_bundle_completeness_accepts_a_compiled_bundle():
    report = validate_execution_bundle_completeness(compiled()["bundle"])
    assert report.accepted(), _messages(report)


@pytest.mark.parametrize(
    ("update", "fragment"),
    [
        ({"acceptance_criteria": []}, "empty acceptance_criteria"),
        ({"stop_conditions": []}, "empty stop_conditions"),
        ({"required_evidence": []}, "empty required_evidence"),
        ({"authority": None}, "no compiled authority block"),
        ({"task_toolkit": None}, "no task toolkit"),
        ({"provenance": []}, "carries no provenance"),
    ],
)
def test_execution_bundle_completeness_rejects_a_hollow_bundle(update, fragment):
    forged = compiled()["bundle"].model_copy(update=update)
    report = validate_execution_bundle_completeness(forged)
    assert not report.accepted()
    assert fragment in _messages(report)


def test_execution_bundle_completeness_rejects_capabilities_outside_the_toolkit():
    bundle = compiled()["bundle"]
    forged = bundle.model_copy(
        update={"allowed_capabilities": [*bundle.allowed_capabilities, "runtime.verify"]}
    )
    report = validate_execution_bundle_completeness(forged)
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "not in the task toolkit" in _messages(report)


def test_execution_bundle_completeness_rejects_a_capability_both_allowed_and_forbidden():
    bundle = compiled()["bundle"]
    shared = bundle.allowed_capabilities[0]
    forged = bundle.model_copy(update={"forbidden_capabilities": [shared]})
    report = validate_execution_bundle_completeness(forged)
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "both allowed and forbidden" in _messages(report)


def test_execution_bundle_completeness_rejects_a_write_scope_disagreeing_with_authority():
    bundle = compiled()["bundle"]
    forged = bundle.model_copy(update={"write_scope": ["docs"]})
    report = validate_execution_bundle_completeness(forged)
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "disagrees with compiled authority" in _messages(report)


# --- lifecycle separation ------------------------------------------------------------


def test_lifecycle_separation_accepts_a_consistent_receipt():
    receipt, _ = complete_receipt()
    report = validate_lifecycle_separation(
        receipt,
        required_evidence_states=[EvidenceState.IMPLEMENTED, EvidenceState.VALIDATED],
    )
    assert report.accepted(), _messages(report)


def test_lifecycle_separation_rejects_done_without_the_required_evidence():
    receipt, _ = complete_receipt(lifecycle=WorkLifecycleState.DONE)
    report = validate_lifecycle_separation(
        receipt,
        required_evidence_states=[
            EvidenceState.IMPLEMENTED,
            EvidenceState.VALIDATED,
            EvidenceState.MERGED_INTEGRATED,
        ],
    )
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "neither attained nor declared not-required" in _messages(report)


def test_lifecycle_separation_rejects_done_while_the_run_is_still_in_flight():
    receipt, _ = complete_receipt(lifecycle=WorkLifecycleState.DONE)
    forged = receipt.model_copy(update={"execution_state": ExecutionState.RUNNING})
    report = validate_lifecycle_separation(forged)
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "cannot have closed the work" in _messages(report)


def test_lifecycle_separation_rejects_a_receipt_that_collapses_evidence_into_one_field():
    receipt, _ = complete_receipt()
    collapsed = receipt.model_copy(
        update={"attained_evidence_states": [], "not_required_evidence_states": []}
    )
    report = validate_lifecycle_separation(collapsed)
    assert report.outcome() == ValidationOutcome.MISSING
    assert "single collapsed state" in _messages(report)


def test_lifecycle_separation_rejects_a_state_both_attained_and_exempt():
    receipt, _ = complete_receipt()
    forged = receipt.model_construct(
        **{
            **receipt.__dict__,
            "not_required_evidence_states": [
                *receipt.not_required_evidence_states,
                EvidenceState.VALIDATED,
            ],
        }
    )
    report = validate_lifecycle_separation(forged)
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "both attained and not-required" in _messages(report)


def test_lifecycle_separation_does_not_second_guess_an_open_lifecycle():
    """Whether an open item should now close is reconciliation's question, not this one.

    All required evidence is resolved and the tracker still says in-review. That is
    not a conflation of the three lifecycles, so this validator has nothing to say
    about it; `reconcile_work_item` is what proposes the transition.
    """
    receipt, _ = complete_receipt()
    report = validate_lifecycle_separation(
        receipt, required_evidence_states=[EvidenceState.IMPLEMENTED]
    )
    assert report.accepted(), _messages(report)


# --- receipt completeness -------------------------------------------------------------


def test_receipt_completeness_accepts_a_full_receipt():
    receipt, artifacts = complete_receipt()
    report = validate_receipt_completeness(
        receipt,
        artifacts=receipt_artifacts(
            artifacts["bundle"],
            project_lock=artifacts["lock"],
            registry=artifacts["registry"],
        ),
    )
    assert report.accepted(), _messages(report)


def test_receipt_completeness_rejects_a_digest_that_names_a_different_artifact():
    receipt, artifacts = complete_receipt()
    other = compiled(run_id="RUN-VERIFY-OTHER")["bundle"]
    report = validate_receipt_completeness(
        receipt, artifacts={"execution-bundle": other}
    )
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "digests to" in _messages(report)


def test_receipt_completeness_requires_identities_findings_and_limitations():
    receipt, _ = complete_receipt()
    hollow = receipt.model_copy(
        update={
            "artifact_identities": [],
            "findings": [],
            "limitations": [],
            "permission_profile_id": None,
            "budget_profile_id": None,
            "base_revision": None,
            "candidate_revision": None,
        }
    )
    report = validate_receipt_completeness(hollow)
    assert report.outcome() == ValidationOutcome.MISSING
    text = _messages(report)
    assert "no configuration artifact identities" in text
    assert "neither findings nor limitations" in text
    assert "neither a base nor a candidate revision" in text


def test_receipt_completeness_rejects_budget_overrun():
    receipt, _ = complete_receipt()
    from agent_foundry.models import BudgetConsumption

    forged = receipt.model_copy(
        update={"budget": BudgetConsumption(retries_used=9, max_retry_budget=2)}
    )
    report = validate_receipt_completeness(forged)
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "exceeds max_retry_budget" in _messages(report)
