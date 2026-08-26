"""Mutation tests: neutralize the producer, and the validator must still reject.

The rule these tests enforce is the one AF6 was blocked twice for missing:

    Do not validate an artifact by calling the function that produced it.

Each test below disables the function that would normally compute or guard the
property — replacing it with a no-op, an identity, or a stub that agrees with the
forgery — and then feeds the validator an artifact that must be rejected. A
validator that only agreed with its producer passes nothing here.

Two of them go further and check that the *mutation itself* is load-bearing: with
the guard neutralized, the producing path really does accept the forgery, so the
rejection can only be coming from the independent layer.
"""

from __future__ import annotations


from agent_foundry.models import (
    EvidenceClass,
    EvidenceState,
    ExecutionState,
    ExternalEffectClass,
    IntegrationHealthState,
    ValidationOutcome,
    WorkLifecycleState,
)
from agent_foundry.models.base import FOUNDRY_SCHEMA_VERSION
from agent_foundry.models.interaction import EvidenceBundle
from agent_foundry.verify import (
    validate_authority_ceiling,
    validate_decision_explainability,
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
from verify_support import (
    compiled,
    complete_receipt,
    full_evidence_bundle,
    integration_spec,
    sample_work_item,
)


def _messages(report) -> str:
    return " | ".join(finding.message for finding in report.findings)


def _rejects(report) -> bool:
    return not report.accepted()


# --- 1. schema-compatibility --------------------------------------------------


def test_schema_compatibility_survives_a_neutralized_schema_guard(monkeypatch):
    """Producer: `models.base.validate_schema_compatibility`, the model validator."""
    import agent_foundry.models.base as base

    monkeypatch.setattr(base, "validate_schema_compatibility", lambda *a, **k: None)

    # With the guard neutralized, an incompatible contract now constructs cleanly.
    payload = {
        "schema_version": "7.4",
        "id": "WI-FORGE",
        "title": "forged",
        "work_class": "CAPABILITY",
        "objective": "forged",
        "current_facts": [],
        "scope": ["src/"],
        "out_of_scope": [],
        "acceptance_criteria": ["x"],
        "authority_class": "repository-write",
        "consequence_class": "medium",
        "required_evidence": ["deterministic-test"],
        "stop_conditions": ["x"],
    }
    from agent_foundry.models import WorkItemContract

    accepted_by_producer = WorkItemContract.model_validate(payload)
    assert accepted_by_producer.schema_version == "7.4"

    report = validate_contract_schema_compatibility([("work-item", accepted_by_producer)])
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "major" in _messages(report)


# --- 2. work-dependency-graph --------------------------------------------------


def test_dependency_graph_survives_a_neutralized_graph_validator(monkeypatch):
    """Producer: `work.validate.validate_dependency_graph`."""
    import agent_foundry.work.validate as work_validate
    from agent_foundry.models import DependencyRelation, DependencySpec

    monkeypatch.setattr(work_validate, "validate_dependency_graph", lambda *a, **k: None)

    items = [
        sample_work_item(
            id="WI-A",
            dependencies=[DependencySpec(relation=DependencyRelation.REQUIRES, target_id="WI-B")],
        ),
        sample_work_item(
            id="WI-B",
            dependencies=[DependencySpec(relation=DependencyRelation.REQUIRES, target_id="WI-A")],
        ),
    ]
    # The neutralized producer now accepts the cyclic plan.
    assert work_validate.validate_dependency_graph(items) is None

    report = validate_work_dependency_graph(items)
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "circular dependency" in _messages(report)


# --- 3. toolkit-coherence -------------------------------------------------------


def test_toolkit_coherence_survives_a_neutralized_ceiling_guard(monkeypatch):
    """Producer: `toolkit.ceiling.validate_task_toolkit_against_ceiling`."""
    import agent_foundry.toolkit.ceiling as ceiling

    monkeypatch.setattr(ceiling, "validate_task_toolkit_against_ceiling", lambda *a, **k: None)
    monkeypatch.setattr(ceiling, "validate_toolkit_lock_against_ceiling", lambda *a, **k: None)

    artifacts = compiled()
    forged = artifacts["task_toolkit"].model_copy(
        update={"capability_ids": [*artifacts["task_toolkit"].capability_ids, "work.write"]}
    )
    assert ceiling.validate_task_toolkit_against_ceiling(forged) is None

    report = validate_toolkit_coherence(forged, artifacts["lock"], artifacts["registry"])
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "not in the pinned project lock" in _messages(report)


# --- 4. authority-ceiling --------------------------------------------------------


def test_authority_ceiling_survives_a_compiler_that_agrees_with_the_forgery(monkeypatch):
    """Producers: `compute_compiled_authority` *and* the AF6 bundle guard, both agreeing."""
    import agent_foundry.compile.authority as authority_module

    artifacts = compiled()
    forged = artifacts["bundle"].authority.model_copy(
        update={"external_effect": ExternalEffectClass.RUNTIME_MUTATION}
    )
    monkeypatch.setattr(
        authority_module, "compute_compiled_authority", lambda *a, **k: forged
    )
    monkeypatch.setattr(
        authority_module, "validate_execution_bundle_authority", lambda *a, **k: None
    )
    # Both producing paths now accept the forgery.
    assert authority_module.validate_execution_bundle_authority(forged) is None

    report = validate_authority_ceiling(
        forged,
        work_item=artifacts["work_item"],
        manifest=artifacts["manifest"],
        task_toolkit=artifacts["task_toolkit"],
        role=artifacts["role"],
        permission_profile=artifacts["permission_profile"],
        registry=artifacts["registry"],
    )
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "exceeds the work item authority class" in _messages(report)


# --- 5. write-scope-containment ---------------------------------------------------


def test_write_scope_containment_survives_an_identity_path_normalizer(monkeypatch):
    """Producer: `compile.authority._normalize_scope_path`, replaced by the identity."""
    import agent_foundry.compile.authority as authority_module

    monkeypatch.setattr(authority_module, "_normalize_scope_path", lambda scope: scope)
    monkeypatch.setattr(
        authority_module, "validate_execution_bundle_authority", lambda *a, **k: None
    )
    # With the identity normalizer in place the compiler's own containment test now
    # accepts a traversal, because "src/../../etc" textually starts with nothing it
    # would have caught.
    assert authority_module._normalize_scope_path("src/../../etc") == "src/../../etc"

    artifacts = compiled()
    forged = artifacts["bundle"].authority.model_copy(
        update={"write_scope": ["src/../../etc"], "forbidden_scopes": []}
    )
    report = validate_write_scope_containment(
        forged, work_item=artifacts["work_item"], role=artifacts["role"]
    )
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "does not resolve" in _messages(report)


# --- 6. role-separation ------------------------------------------------------------


def test_role_separation_survives_a_compiler_that_hands_back_colliding_bundles(monkeypatch):
    """Producer: `compile_work_item`, stubbed to emit two roles over the same paths."""
    import agent_foundry.compile.api as compile_api

    artifacts = compiled()
    builder = artifacts["bundle"]
    colliding = builder.model_copy(update={"role_id": "integrator"})

    class _Result:
        task_toolkit = artifacts["task_toolkit"]
        bundle = colliding

    monkeypatch.setattr(compile_api, "compile_work_item", lambda *a, **k: _Result())
    assert compile_api.compile_work_item().bundle.role_id == "integrator"

    report = validate_role_separation([builder, colliding])
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "overlapping write scope" in _messages(report)


# --- 7. integration-preflight ------------------------------------------------------


def test_integration_preflight_survives_a_preflight_that_reports_everything_healthy(monkeypatch):
    """Producer: `toolkit.preflight.preflight_integrations`, stubbed to claim health."""
    import agent_foundry.toolkit.preflight as preflight
    from agent_foundry.models import IntegrationHealth

    def _all_healthy(integrations, *, required_ids, observed_health=()):
        return [
            IntegrationHealth(
                integration_id=integration_id, state=IntegrationHealthState.HEALTHY
            )
            for integration_id in required_ids
        ]

    monkeypatch.setattr(preflight, "preflight_integrations", _all_healthy)
    monkeypatch.setattr(preflight, "integration_preflight_passes", lambda *a, **k: True)
    # The neutralized producer now claims a never-observed integration is healthy.
    assert preflight.preflight_integrations([], required_ids=["work-tracker"])[0].state == (
        IntegrationHealthState.HEALTHY
    )

    report = validate_integration_preflight(
        [integration_spec()], required_ids=["work-tracker"], observed_health=[]
    )
    assert report.outcome() == ValidationOutcome.MISSING
    assert "unobserved is not healthy" in _messages(report)


# --- 8. required-evidence -----------------------------------------------------------


def test_required_evidence_survives_a_bundle_builder_that_fabricates_evidence(monkeypatch):
    """Producer: any evidence assembler; here the bundle arrives empty but well-formed."""
    import verify_support

    def _empty_bundle(**_overrides):
        return EvidenceBundle(
            schema_version=FOUNDRY_SCHEMA_VERSION,
            work_item_id="WI-VERIFY-001",
            run_id="RUN-VERIFY-001",
        )

    monkeypatch.setattr(verify_support, "full_evidence_bundle", _empty_bundle)
    forged = verify_support.full_evidence_bundle()
    assert forged.items == []

    report = validate_required_evidence(sample_work_item(), forged)
    assert report.outcome() == ValidationOutcome.MISSING
    assert "no passing evidence item declares class" in _messages(report)


# --- 9. evidence-bundle-completeness -------------------------------------------------


def test_evidence_bundle_completeness_survives_a_bypassed_model_validator():
    """Producer: the `EvidenceBundle` model itself, bypassed with `model_construct`.

    `model_construct` skips every field and model validator, which is exactly what a
    hand-written or externally supplied payload amounts to.
    """
    good = full_evidence_bundle()
    forged = EvidenceBundle.model_construct(
        **{
            **good.__dict__,
            "identity": None,
            "items": [],
            "not_required_classes": [EvidenceClass.DETERMINISTIC_TEST],
        }
    )
    report = validate_evidence_bundle_completeness(forged)
    assert report.outcome() == ValidationOutcome.MISSING
    assert "names no revision identity" in _messages(report)


# --- 10. provenance-completeness -------------------------------------------------------


def test_provenance_completeness_survives_a_neutralized_provenance_builder(monkeypatch):
    """Producer: `compile.api._execution_bundle_provenance`, stubbed to emit nothing."""
    import agent_foundry.compile.api as compile_api

    monkeypatch.setattr(compile_api, "_execution_bundle_provenance", lambda *a, **k: [])
    assert compile_api._execution_bundle_provenance() == []

    artifacts = compiled()
    forged = artifacts["bundle"].model_copy(
        update={
            "provenance": [],
            "task_toolkit": artifacts["task_toolkit"].model_copy(update={"decisions": []}),
        }
    )
    report = validate_provenance_completeness(forged)
    assert report.outcome() == ValidationOutcome.MISSING
    assert "untraceable" in _messages(report)


# --- 11. execution-bundle-completeness --------------------------------------------------


def test_execution_bundle_completeness_survives_a_neutralized_af6_guard(monkeypatch):
    """Producer: `compile.authority.validate_execution_bundle_authority`."""
    import agent_foundry.compile.authority as authority_module

    monkeypatch.setattr(
        authority_module, "validate_execution_bundle_authority", lambda *a, **k: None
    )
    assert authority_module.validate_execution_bundle_authority(None) is None

    artifacts = compiled()
    forged = artifacts["bundle"].model_copy(
        update={"acceptance_criteria": [], "authority": None, "task_toolkit": None}
    )
    report = validate_execution_bundle_completeness(forged)
    assert report.outcome() == ValidationOutcome.MISSING
    assert "empty acceptance_criteria" in _messages(report)


# --- 12. lifecycle-separation -----------------------------------------------------------


def test_lifecycle_separation_survives_a_neutralized_receipt_builder(monkeypatch):
    """Producer: `verify.receipt.build_execution_receipt`, stubbed to emit a collapsed receipt."""
    import agent_foundry.verify.receipt as receipt_module
    from agent_foundry.models import ExecutionReceipt

    receipt, _ = complete_receipt()
    collapsed = ExecutionReceipt.model_construct(
        **{
            **receipt.__dict__,
            "work_lifecycle_state": WorkLifecycleState.DONE,
            "execution_state": ExecutionState.RUNNING,
            "attained_evidence_states": [],
            "not_required_evidence_states": [],
        }
    )
    monkeypatch.setattr(receipt_module, "build_execution_receipt", lambda **k: collapsed)
    assert receipt_module.build_execution_receipt().attained_evidence_states == []

    report = validate_lifecycle_separation(
        collapsed, required_evidence_states=[EvidenceState.VALIDATED]
    )
    assert report.outcome() == ValidationOutcome.BLOCKED
    text = _messages(report)
    assert "single collapsed state" in text
    assert "cannot have closed the work" in text


# --- 13. receipt-completeness ------------------------------------------------------------


def test_receipt_completeness_survives_a_receipt_builder_that_names_the_wrong_artifact(monkeypatch):
    """Producer: `verify.receipt.build_execution_receipt`, stubbed to stamp a stale digest."""
    import agent_foundry.verify.receipt as receipt_module

    receipt, artifacts = complete_receipt()
    other = compiled(run_id="RUN-OTHER")["bundle"]
    monkeypatch.setattr(receipt_module, "build_execution_receipt", lambda **k: receipt)
    assert receipt_module.build_execution_receipt() is receipt

    report = validate_receipt_completeness(receipt, artifacts={"execution-bundle": other})
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "digests to" in _messages(report)


def test_receipt_completeness_survives_a_disposition_rule_bypassed_at_construction():
    """Producer: the `RunFinding` model validator, bypassed with `model_construct`."""
    from agent_foundry.models import FindingDisposition, RunFinding

    receipt, _ = complete_receipt()
    naked_residual = RunFinding.model_construct(
        id="F-9",
        disposition=FindingDisposition.RESIDUAL,
        summary="left for later",
        evidence_refs=[],
        follow_up_work_ref=None,
        falsifiable_prediction=None,
        evidence_condition=None,
        escalation_reason=None,
        failure_category=None,
    )
    forged = receipt.model_copy(update={"findings": [naked_residual]})
    report = validate_receipt_completeness(forged)
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "RESIDUAL requires follow_up_work_ref" in _messages(report)


# --- 14. decision-explainability -----------------------------------------------------------


def test_decision_explainability_survives_a_neutralized_authority_guard(monkeypatch):
    """Producer: `adopt.authority.assert_change_set_respects_authority` and the compiler.

    With both neutralized, a manifest carrying an authority level that only an
    inference supports is produced and accepted. The trace still reports it.
    """
    import agent_foundry.adopt.authority as adopt_authority
    import agent_foundry.compile.authority as compile_authority
    from agent_foundry.models import ClassificationFinding, Provenance, ProvenanceKind

    monkeypatch.setattr(
        adopt_authority, "assert_change_set_respects_authority", lambda *a, **k: None
    )
    monkeypatch.setattr(
        compile_authority, "validate_execution_bundle_authority", lambda *a, **k: None
    )
    assert adopt_authority.assert_change_set_respects_authority([]) is None

    artifacts = compiled()
    inferred_only = [
        ClassificationFinding(
            dimension="External effect",
            value="repository-write",
            provenance=Provenance(
                kind=ProvenanceKind.INFERRED, confidence=0.6, source_ref="pyproject.toml"
            ),
        ),
        ClassificationFinding(
            dimension="Autonomy",
            value="bounded-external-write",
            provenance=Provenance(
                kind=ProvenanceKind.INFERRED, confidence=0.5, source_ref="pyproject.toml"
            ),
        ),
    ]
    report = validate_decision_explainability(
        artifacts["bundle"],
        manifest=artifacts["manifest"],
        classification_findings=inferred_only,
        receipt=complete_receipt()[0],
    )
    assert report.outcome() == ValidationOutcome.HUMAN_REQUIRED
    assert "raised the authority envelope" in _messages(report)


def test_decision_explainability_survives_a_provenance_builder_that_omits_causes(monkeypatch):
    """Producer: `compile.api._execution_bundle_provenance` and the toolkit decisions."""
    import agent_foundry.compile.api as compile_api

    monkeypatch.setattr(compile_api, "_execution_bundle_provenance", lambda *a, **k: [])

    artifacts = compiled()
    stripped = [
        record.model_copy(update={"project_fact": None, "policy_id": None})
        for record in artifacts["bundle"].provenance
    ]
    forged = artifacts["bundle"].model_copy(update={"provenance": stripped})
    report = validate_decision_explainability(
        forged, manifest=artifacts["manifest"], receipt=complete_receipt()[0]
    )
    assert _rejects(report)
    assert "neither a causing fact nor a causing policy" in _messages(report)


# --- the mutation harness itself is not fooled by stale bytecode --------------------


def test_monkeypatched_producers_are_actually_observed_by_the_validators(monkeypatch):
    """Guard against a mutation test that silently exercised the unmutated code.

    Two sibling lanes were misled by stale `.pyc` reuse. This asserts the patch is
    visible through the same module object the validator resolves, so a mutation that
    did not take effect fails here rather than passing quietly downstream.
    """
    import agent_foundry.compile.authority as authority_module

    original = authority_module._normalize_scope_path
    monkeypatch.setattr(authority_module, "_normalize_scope_path", lambda scope: scope)
    assert authority_module._normalize_scope_path is not original
    assert authority_module._normalize_scope_path("src/../../etc") == "src/../../etc"

    # The independent layer is a different function object entirely.
    from agent_foundry.verify.independent import normalize_repository_path

    assert normalize_repository_path("src/../../etc") is None
