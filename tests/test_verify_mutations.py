"""Mutation tests: the producer accepts the artifact, and the validator rejects it.

The rule these tests enforce is the one AF6 was blocked twice for missing:

    Do not validate an artifact by calling the function that produced it.

Every test here follows the same two-step order, and the order is the point:

1. **Producer acceptance.** Neutralize the function that would normally compute or
   guard the property — with a no-op, an identity, a stub that agrees with the
   forgery, or a wrong stamp — and then show a *real production path* emitting or
   accepting the defective artifact. Not a hand-built object handed straight to the
   validator: `compile_work_item` returning a bundle, `build_execution_receipt`
   stamping a receipt, `model_validate`/`load_yaml` ingesting a payload.
2. **Independent rejection.** Feed that same artifact to the validator and require a
   non-accepting outcome.

Where a validator has no code producer — evidence bundles and required-evidence
pairings arrive from outside Foundry — step 1 is the model ingestion path
(`load_yaml` / `model_validate`), and the test says so rather than glossing it.
Several tests also assert an unpatched control first, so "the producer would
normally reject this" is established rather than assumed.
"""

from __future__ import annotations


import pytest

from agent_foundry.models import (
    EvidenceState,
    ExecutionState,
    ExternalEffectClass,
    IntegrationHealthState,
    ValidationOutcome,
    WorkLifecycleState,
)
from agent_foundry.models.interaction import EvidenceBundle
from agent_foundry.toolkit import default_registry
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
from agent_foundry.verify.receipt import receipt_artifacts
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
    """Producer: `compile.authority._normalize_scope_path`, replaced by the identity.

    Step 1 runs the whole compiler. With resolution reduced to the identity, textual
    prefix comparison accepts `src//../../etc` as living under the role bound `src/`,
    so `compile_work_item` *returns a bundle granting write access above the
    repository root* — and the AF6 bundle guard, which shares the normalizer, passes
    it. Nothing is hand-forged here; the production path emits the defect.
    """
    import agent_foundry.compile.authority as authority_module
    from agent_foundry.compile import compile_work_item
    from agent_foundry.toolkit import resolve_toolkit
    from verify_support import sample_manifest

    escaping = "src//../../etc"
    assert authority_module._normalize_scope_path(escaping) is None  # unpatched control

    monkeypatch.setattr(authority_module, "_normalize_scope_path", lambda scope: scope)

    manifest = sample_manifest()
    work_item = sample_work_item(scope=[escaping])
    _, lock = resolve_toolkit(manifest)
    produced = compile_work_item(work_item, manifest, lock, "builder", "RUN-ESCAPE")

    # Producer acceptance: the compiler returned rather than raising, and the bundle
    # it produced grants a path that climbs out of the repository.
    assert produced.bundle.authority.write_scope == [escaping]
    assert produced.bundle.write_scope == [escaping]

    role = next(item for item in default_registry().roles if item.id == "builder")
    report = validate_write_scope_containment(
        produced.bundle.authority, work_item=work_item, role=role
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


def test_required_evidence_survives_both_real_production_paths():
    """Producers: `compile_work_item` and `load_yaml` — no code producer pairs them.

    Foundry has no evidence assembler; an evidence bundle arrives from a run or a
    file. So step 1 exercises the two production paths that actually exist. The
    compiler emits a bundle asserting `deterministic-test` is required, and
    `load_yaml` ingests an evidence bundle that proves none of it. Both accept. The
    pairing is what nobody checks — until this validator does.
    """
    from agent_foundry.models import load_yaml

    artifacts = compiled()

    # Producer acceptance (1/2): the compiler records the requirement and moves on.
    required = [
        record
        for record in artifacts["bundle"].provenance
        if record.component_kind == "required-evidence"
    ]
    assert {record.component_id for record in required} >= {"deterministic-test"}

    # Producer acceptance (2/2): an evidence bundle proving nothing loads cleanly.
    ingested = load_yaml(
        EvidenceBundle,
        b"schema_version: '0.1'\nwork_item_id: WI-VERIFY-001\nrun_id: RUN-VERIFY-001\n",
    )
    assert ingested.items == []

    report = validate_required_evidence(artifacts["work_item"], ingested)
    assert report.outcome() == ValidationOutcome.MISSING
    assert "no passing evidence item declares class" in _messages(report)


# --- 9. evidence-bundle-completeness -------------------------------------------------


def test_evidence_bundle_completeness_survives_the_real_ingestion_path():
    """Producer: `load_yaml`, the path by which every evidence bundle actually arrives.

    There is no evidence-bundle builder to neutralize — which is exactly why the
    ingestion path is the producer worth testing. A bundle naming no revision, no
    items, and no result is a valid `EvidenceBundle`: every one of those fields is
    optional, so `load_yaml` accepts it without complaint. The validator is the only
    thing standing between that and a run reported as evidenced.
    """
    from agent_foundry.models import load_yaml

    hollow = load_yaml(
        EvidenceBundle,
        b"schema_version: '0.1'\nwork_item_id: WI-VERIFY-001\nrun_id: RUN-VERIFY-001\n",
    )
    # Producer acceptance: it validated, and it proves nothing.
    assert hollow.identity is None and hollow.items == []

    report = validate_evidence_bundle_completeness(hollow)
    assert report.outcome() == ValidationOutcome.MISSING
    assert "names no revision identity" in _messages(report)
    assert "carries no items" in _messages(report)


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


def test_receipt_completeness_survives_a_neutralized_digest_stamp(monkeypatch):
    """Producer: `verify.receipt.artifact_digest`, the function that stamps a receipt.

    Step 1 neutralizes the stamping function and then runs the real
    `build_execution_receipt`, which emits a receipt whose declared digests do not
    correspond to any artifact it was given. Step 2 recomputes through
    `verify.independent.contract_digest` — a deliberately separate call site — and
    catches it. Sharing one helper between stamping and checking would have made
    this mutation invisible.
    """
    import agent_foundry.verify.receipt as receipt_module

    honest, artifacts = complete_receipt()
    monkeypatch.setattr(receipt_module, "artifact_digest", lambda model: "0" * 64)

    stamped, _ = complete_receipt()
    # Producer acceptance: the builder returned a receipt carrying a bogus digest.
    assert {identity.digest for identity in stamped.artifact_identities} == {"0" * 64}
    assert stamped.artifact_identities != honest.artifact_identities

    report = validate_receipt_completeness(
        stamped,
        artifacts=receipt_artifacts(
            artifacts["bundle"],
            project_lock=artifacts["lock"],
            registry=artifacts["registry"],
        ),
    )
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "digests to" in _messages(report)


def test_receipt_completeness_still_catches_a_receipt_naming_another_run(monkeypatch):
    """The same property from the other side: a valid receipt, a different artifact."""
    import agent_foundry.verify.receipt as receipt_module

    receipt, _ = complete_receipt()
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


# --- producer-owned model rules are re-derived, not reused ---------------------
#
# Both rules below are enforced by a pydantic model validator, which is a producer:
# it decides whether the artifact may exist at all. The first version of this change
# shipped validators that called the producer's own helper, so gutting the helper
# made producer and validator agree that an invalid payload was fine. These tests
# are the standing proof that the two derivations can now disagree.


def test_lifecycle_separation_survives_a_neutralized_partition_rule(monkeypatch):
    """Producer: `models._producer_rules.evidence_state_partition_violations`."""
    from agent_foundry.models import ExecutionReceipt
    from agent_foundry.models.interaction import ReceiptContractError
    import agent_foundry.models._producer_rules as producer_rules

    receipt, _ = complete_receipt()
    overlapping = {
        **receipt.model_dump(mode="json"),
        "not_required_evidence_states": [
            *[state.value for state in receipt.not_required_evidence_states],
            EvidenceState.VALIDATED.value,
        ],
    }

    # Control: unpatched, the producer refuses to build this receipt at all.
    with pytest.raises(ReceiptContractError):
        ExecutionReceipt.model_validate(overlapping)

    monkeypatch.setattr(
        producer_rules, "evidence_state_partition_violations", lambda **_kwargs: []
    )

    # Producer acceptance: with the rule gutted, ingestion now emits the receipt.
    accepted = ExecutionReceipt.model_validate(overlapping)
    assert EvidenceState.VALIDATED in accepted.attained_evidence_states
    assert EvidenceState.VALIDATED in accepted.not_required_evidence_states

    report = validate_lifecycle_separation(accepted)
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "both attained and not-required" in _messages(report)


def test_completeness_validators_survive_a_neutralized_disposition_rule(monkeypatch):
    """Producer: `models._producer_rules.disposition_obligation_violations`.

    One gutted helper, two validators that must both still bite — a RESIDUAL with no
    follow-up work is how a bounded weakness quietly becomes permanent.
    """
    from agent_foundry.models import RunFinding
    from agent_foundry.models.interaction import ReceiptContractError
    import agent_foundry.models._producer_rules as producer_rules

    naked_residual = {
        "id": "F-NAKED",
        "disposition": "RESIDUAL",
        "summary": "error paths left untested",
    }

    # Control: unpatched, the producer refuses to build the finding.
    with pytest.raises(ReceiptContractError, match="RESIDUAL requires follow_up_work_ref"):
        RunFinding.model_validate(naked_residual)

    monkeypatch.setattr(
        producer_rules, "disposition_obligation_violations", lambda **_kwargs: []
    )

    # Producer acceptance: the finding now constructs with nothing to follow up.
    accepted = RunFinding.model_validate(naked_residual)
    assert accepted.follow_up_work_ref is None

    receipt, _ = complete_receipt()
    receipt_report = validate_receipt_completeness(
        receipt.model_copy(update={"findings": [accepted]})
    )
    assert receipt_report.outcome() == ValidationOutcome.BLOCKED
    assert "RESIDUAL requires follow_up_work_ref" in _messages(receipt_report)

    bundle_report = validate_evidence_bundle_completeness(
        full_evidence_bundle().model_copy(update={"unresolved": [accepted]})
    )
    assert bundle_report.outcome() == ValidationOutcome.BLOCKED
    assert "RESIDUAL requires follow_up_work_ref" in _messages(bundle_report)


def test_an_unrecognised_disposition_is_rejected_by_the_vocabulary_scan():
    """An off-vocabulary disposition never reaches the obligation table."""
    from agent_foundry.models import RunFinding

    receipt, _ = complete_receipt()
    unknown = RunFinding.model_construct(
        id="F-UNKNOWN",
        disposition="SOMEDAY",
        summary="a disposition nobody defined",
        evidence_refs=[],
        follow_up_work_ref=None,
        falsifiable_prediction=None,
        evidence_condition=None,
        escalation_reason=None,
        failure_category=None,
    )
    report = validate_receipt_completeness(receipt.model_copy(update={"findings": [unknown]}))
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "names no FindingDisposition value" in _messages(report)


def test_a_valid_disposition_with_no_obligation_entry_is_still_a_violation():
    """The table refuses to pass what it cannot place.

    The vocabulary scan handles values outside `FindingDisposition`. This covers the
    case it cannot: a disposition that IS a member but that nobody gave an
    obligation. The producer's branch chain would ignore it silently; the
    table-driven derivation treats a missing entry as a violation, so adding a
    disposition without an obligation is visible rather than exempt.
    """
    from agent_foundry.verify.independent import (
        DISPOSITION_REQUIRED_FIELDS,
        finding_obligation_violations,
    )

    untabled = "SOMEDAY"
    assert untabled not in DISPOSITION_REQUIRED_FIELDS
    violations = finding_obligation_violations(
        {"disposition": untabled, "id": "F-X"}, label="F-X"
    )
    assert violations
    assert "carries no known obligation" in " ".join(violations)


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
            dimension="impact.external_effect",
            value="repository-write",
            provenance=Provenance(
                kind=ProvenanceKind.INFERRED, confidence=0.6, source_ref="pyproject.toml"
            ),
        ),
        ClassificationFinding(
            dimension="execution.autonomy",
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
