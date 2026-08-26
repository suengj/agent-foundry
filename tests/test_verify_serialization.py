"""Receipt, evidence, and validation-result serialization through the secret boundary.

Every model AF7 adds has to round-trip deterministically and has to refuse to carry
credential material out through `dump_json` / `dump_yaml`. A new contract that
serializes a leaked token is a new hole in the SUE-318 boundary, so each one is
tested rather than assumed to inherit the guard.
"""

from __future__ import annotations

import pytest

from agent_foundry.models import (
    AuthorityTightening,
    BudgetConsumption,
    DecisionTrace,
    DecisionTraceEntry,
    EmbeddedSecretError,
    EvidenceBundle,
    EvidenceClass,
    EvidenceIdentity,
    ExecutionReceipt,
    FailureCategory,
    FailureClassification,
    FailureSignal,
    FindingDisposition,
    LifecycleSeparation,
    RawSecretError,
    ReceiptLimitation,
    RepeatedFailureAssessment,
    ReviewDecision,
    ReviewOutcome,
    RunFinding,
    StateAuthority,
    StateProposal,
    dump_json,
    dump_yaml,
    load_json,
    load_yaml,
    parse_yaml,
    dump_yaml_raw,
)
from agent_foundry.models.interaction import ReceiptContractError
from agent_foundry.verify import (
    VALIDATOR_CLAIMS,
    reconcile_work_item,
    validate_execution_bundle_completeness,
)
from verify_support import (
    CANDIDATE_REVISION,
    approving_review,
    complete_receipt,
    full_evidence_bundle,
    repository,
    runtime,
    sample_work_item,
    tracker,
)

# A documented example credential shape, used only to prove the guard fires.
AWS_SAMPLE = "AKIAIOSFODNN7EXAMPLE"


def _roundtrip(model):
    as_yaml = dump_yaml(model)
    assert load_yaml(type(model), as_yaml) == model
    as_json = dump_json(model)
    assert load_json(type(model), as_json) == model
    assert dump_yaml_raw(parse_yaml(as_yaml)) == as_yaml
    return as_yaml, as_json


def _new_models():
    """One populated instance of every contract AF7 introduces or extends."""
    receipt, artifacts = complete_receipt()
    report = reconcile_work_item(
        work_item=sample_work_item(),
        tracker=tracker(),
        repository=repository(),
        runtime=runtime(),
    )
    return {
        "ExecutionReceipt": receipt,
        "EvidenceBundle": full_evidence_bundle(),
        "ReviewDecision": approving_review(),
        "EvidenceIdentity": EvidenceIdentity(candidate_revision=CANDIDATE_REVISION),
        "EvidenceItem": full_evidence_bundle().items[0],
        "ArtifactIdentity": receipt.artifact_identities[0],
        "BudgetConsumption": BudgetConsumption(retries_used=1, max_retry_budget=2),
        "ReceiptLimitation": ReceiptLimitation(
            subject="runtime", reason="not applicable", evidence_class=EvidenceClass.RUNTIME_READBACK
        ),
        "RunFinding": receipt.findings[0],
        "ValidationFinding": validate_execution_bundle_completeness(
            artifacts["bundle"]
        ).findings[0],
        "ValidationReport": validate_execution_bundle_completeness(artifacts["bundle"]),
        "ValidatorClaim": VALIDATOR_CLAIMS[0],
        "TrackerProjection": tracker(),
        "RepositoryEvidence": repository(),
        "RuntimeReadback": runtime(),
        "StateProposal": StateProposal(
            authority=StateAuthority.TRACKER,
            work_item_id="WI-VERIFY-001",
            field="lifecycle_state",
            current_value="in-review",
            proposed_value="done",
            rationale="all required evidence resolved",
        ),
        "ReconciliationFinding": report.findings[0],
        "ReconciliationReport": report,
        "FailureSignal": FailureSignal(
            run_id="RUN-1", attempt=1, harness_markers=["stale-bytecode"]
        ),
        "FailureClassification": FailureClassification(
            run_id="RUN-1", attempt=1, category=FailureCategory.HARNESS, rationale="marker"
        ),
        "RepeatedFailureAssessment": RepeatedFailureAssessment(
            category=FailureCategory.HARNESS, occurrences=2, rationale="repeated"
        ),
        "DecisionTraceEntry": DecisionTraceEntry(
            component_kind="skill", component_id="bounded-change", selected=True
        ),
        "AuthorityTightening": AuthorityTightening(
            axis="impact.external_effect", declared_only="read-only", rationale="unchanged"
        ),
        "LifecycleSeparation": LifecycleSeparation(),
        "DecisionTrace": DecisionTrace(
            work_item_id="WI-VERIFY-001", run_id="RUN-VERIFY-001", role_id="builder"
        ),
    }


NEW_MODELS = _new_models()


@pytest.mark.parametrize("name", sorted(NEW_MODELS))
def test_every_new_model_round_trips_deterministically(name):
    _roundtrip(NEW_MODELS[name])


# --- the secret boundary holds for every new model ---------------------------------

# Each entry names a free-text field on a new model that an agent could write into.
SECRET_INJECTION_SITES: list[tuple[str, str]] = [
    ("ExecutionReceipt", "next_action"),
    ("ExecutionReceipt", "cleanup_state"),
    ("ExecutionReceipt", "runtime_verification_ref"),
    ("EvidenceBundle", "run_id"),
    ("ReviewDecision", "reviewed_revision"),
    ("EvidenceIdentity", "candidate_revision"),
    ("EvidenceItem", "description"),
    ("ArtifactIdentity", "ref"),
    ("ReceiptLimitation", "reason"),
    ("RunFinding", "summary"),
    ("ValidationFinding", "message"),
    ("ValidatorClaim", "cannot_prove"),
    ("TrackerProjection", "external_ref"),
    ("RepositoryEvidence", "candidate_revision"),
    ("RuntimeReadback", "source_ref"),
    ("StateProposal", "rationale"),
    ("ReconciliationFinding", "message"),
    ("FailureSignal", "message"),
    ("FailureClassification", "rationale"),
    ("RepeatedFailureAssessment", "rationale"),
    ("DecisionTraceEntry", "component_id"),
    ("AuthorityTightening", "rationale"),
    ("DecisionTrace", "role_id"),
]


@pytest.mark.parametrize(("name", "field"), SECRET_INJECTION_SITES)
def test_dump_refuses_an_embedded_credential_in_every_new_model(name, field):
    model = NEW_MODELS[name]
    poisoned = model.model_copy(update={field: f"see {AWS_SAMPLE} for details"})
    with pytest.raises(EmbeddedSecretError):
        dump_json(poisoned)
    with pytest.raises(EmbeddedSecretError):
        dump_yaml(poisoned)


def test_a_credential_nested_deep_in_a_report_is_still_refused():
    report = NEW_MODELS["ReconciliationReport"]
    poisoned_finding = report.findings[0].model_copy(
        update={"evidence_refs": [f"token {AWS_SAMPLE}"]}
    )
    poisoned = report.model_copy(update={"findings": [poisoned_finding]})
    with pytest.raises(EmbeddedSecretError):
        dump_json(poisoned)


def test_a_credential_in_receipt_adapter_versions_is_refused():
    receipt = NEW_MODELS["ExecutionReceipt"]
    poisoned = receipt.model_copy(update={"adapter_versions": {"repository": AWS_SAMPLE}})
    with pytest.raises(EmbeddedSecretError):
        dump_yaml(poisoned)


def test_a_credential_shaped_key_in_adapter_versions_is_rejected_at_construction():
    receipt = NEW_MODELS["ExecutionReceipt"]
    payload = {**receipt.model_dump(mode="json"), "adapter_versions": {"token": "v1"}}
    with pytest.raises(RawSecretError):
        ExecutionReceipt.model_validate(payload)


# --- disposition obligations survive serialization -----------------------------------


@pytest.mark.parametrize(
    ("disposition", "companion", "fragment"),
    [
        (FindingDisposition.RESIDUAL, {}, "RESIDUAL requires follow_up_work_ref"),
        (FindingDisposition.BLOCKER, {}, "BLOCKER requires at least one evidence_ref"),
        (
            FindingDisposition.HYPOTHESIS,
            {"falsifiable_prediction": "p"},
            "HYPOTHESIS requires evidence_condition",
        ),
        (FindingDisposition.HUMAN_REQUIRED, {}, "HUMAN_REQUIRED requires escalation_reason"),
    ],
)
def test_a_finding_loaded_from_a_payload_still_owes_its_disposition(
    disposition, companion, fragment
):
    payload = {"id": "F-X", "disposition": disposition.value, "summary": "x", **companion}
    with pytest.raises(ReceiptContractError, match=fragment):
        RunFinding.model_validate(payload)


def test_a_review_decision_cannot_load_itself_as_its_own_reviewer():
    payload = {
        "work_item_id": "WI-1",
        "run_id": "RUN-1",
        "reviewer_role": "builder",
        "implementing_role_id": "builder",
        "outcome": ReviewOutcome.APPROVED.value,
    }
    with pytest.raises(ReceiptContractError, match="not an independent review"):
        ReviewDecision.model_validate(payload)


# --- fixture round-trip -------------------------------------------------------------


def test_the_checked_in_receipt_fixture_still_loads():
    """The pre-AF7 fixtures must keep loading; the new fields are additive."""
    from pathlib import Path

    fixtures = Path(__file__).resolve().parent / "fixtures" / "valid"
    receipt = load_yaml(ExecutionReceipt, (fixtures / "execution_receipt.yaml").read_bytes())
    assert receipt.attained_evidence_states == []
    bundle = load_yaml(EvidenceBundle, (fixtures / "evidence_bundle.yaml").read_bytes())
    assert bundle.identity is None
