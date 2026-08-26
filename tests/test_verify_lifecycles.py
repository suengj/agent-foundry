"""The three lifecycles stay three lifecycles.

Work lifecycle, execution lifecycle, and evidence state answer different questions
and must never be collapsed into one status field. These tests fail if they are.
"""

from __future__ import annotations

import pytest

from agent_foundry.models import (
    EvidenceState,
    ExecutionReceipt,
    ExecutionRunRef,
    ExecutionState,
    EvidenceStateSnapshot,
    ValidationOutcome,
    WorkLifecycleSnapshot,
    WorkLifecycleState,
)
from agent_foundry.models.interaction import ReceiptContractError
from agent_foundry.verify import build_decision_trace, validate_lifecycle_separation
from verify_support import complete_receipt


def _values(enum) -> set[str]:
    return {member.value for member in enum}


def test_the_three_state_vocabularies_are_pairwise_disjoint():
    """A shared value would let one field stand in for any of the three."""
    work = _values(WorkLifecycleState)
    execution = _values(ExecutionState)
    evidence = _values(EvidenceState)

    assert work & execution == set(), work & execution
    assert work & evidence == set(), work & evidence
    assert execution & evidence == set(), execution & evidence


def test_each_lifecycle_has_its_own_snapshot_type():
    """Three questions, three record types — not one status with three meanings."""
    assert "lifecycle_state" in WorkLifecycleSnapshot.model_fields
    assert "execution_state" in ExecutionRunRef.model_fields
    assert "evidence_states" in EvidenceStateSnapshot.model_fields

    assert "evidence_states" not in WorkLifecycleSnapshot.model_fields
    assert "lifecycle_state" not in ExecutionRunRef.model_fields
    assert "lifecycle_state" not in EvidenceStateSnapshot.model_fields


def test_the_receipt_carries_all_three_as_separate_fields():
    fields = ExecutionReceipt.model_fields
    for field in (
        "work_lifecycle_state",
        "execution_state",
        "attained_evidence_states",
        "not_required_evidence_states",
    ):
        assert field in fields, field

    receipt, _ = complete_receipt()
    assert receipt.work_lifecycle_state == WorkLifecycleState.IN_REVIEW
    assert receipt.execution_state == ExecutionState.STOPPED
    assert EvidenceState.VALIDATED in receipt.attained_evidence_states


def test_conflating_the_lifecycles_in_a_receipt_is_rejected():
    """The named test the contract asks for: conflation must fail."""
    receipt, _ = complete_receipt(lifecycle=WorkLifecycleState.DONE)
    conflated = receipt.model_copy(
        update={
            # One story told three times: the run is still going, the work is closed,
            # and no evidence state is recorded at all.
            "execution_state": ExecutionState.RUNNING,
            "attained_evidence_states": [],
            "not_required_evidence_states": [],
        }
    )
    report = validate_lifecycle_separation(
        conflated, required_evidence_states=[EvidenceState.VALIDATED]
    )
    assert report.outcome() == ValidationOutcome.BLOCKED
    messages = " | ".join(finding.message for finding in report.findings)
    assert "single collapsed state" in messages
    assert "cannot have closed the work" in messages


def _revalidated(receipt: ExecutionReceipt, **changes: object) -> ExecutionReceipt:
    """Re-run validation over an edited payload.

    `model_copy` deliberately skips validators, so a partition rule is only exercised
    by feeding the changed payload back through `model_validate` — which is also what
    happens to any receipt that arrives from a file.
    """
    payload = {**receipt.model_dump(mode="json"), **changes}
    return ExecutionReceipt.model_validate(payload)


def test_a_state_cannot_be_both_attained_and_exempt_at_construction():
    receipt, _ = complete_receipt()
    with pytest.raises(ReceiptContractError, match="both attained and not-required"):
        _revalidated(
            receipt,
            not_required_evidence_states=[
                *[state.value for state in receipt.not_required_evidence_states],
                EvidenceState.VALIDATED.value,
            ],
        )


def test_not_required_is_an_exemption_not_an_attainment():
    receipt, _ = complete_receipt()
    with pytest.raises(ReceiptContractError, match="not an attained evidence state"):
        _revalidated(
            receipt,
            attained_evidence_states=[
                *[state.value for state in receipt.attained_evidence_states],
                EvidenceState.NOT_REQUIRED.value,
            ],
        )


def test_the_decision_trace_keeps_the_three_lifecycles_addressable():
    receipt, artifacts = complete_receipt()
    trace = build_decision_trace(artifacts["bundle"], receipt=receipt)
    separation = trace.lifecycle_separation
    assert separation.work_lifecycle_state == WorkLifecycleState.IN_REVIEW
    assert separation.execution_state == ExecutionState.STOPPED
    assert EvidenceState.VALIDATED in separation.attained_evidence_states
    assert EvidenceState.RUNTIME_APPLIED in separation.not_required_evidence_states


def test_the_evidence_projection_is_not_the_record():
    """`evidence_state` is a single value; it cannot express the exempt set."""
    receipt, _ = complete_receipt()
    assert receipt.evidence_state == EvidenceState.VALIDATED
    # The projection says nothing about the three states that were never required.
    assert set(receipt.not_required_evidence_states) == {
        EvidenceState.RUNTIME_APPLIED,
        EvidenceState.RUNTIME_VERIFIED,
        EvidenceState.USER_ACCEPTED,
    }
    collapsed = receipt.model_copy(
        update={"attained_evidence_states": [], "not_required_evidence_states": []}
    )
    assert collapsed.evidence_state == EvidenceState.VALIDATED
    assert not validate_lifecycle_separation(collapsed).accepted()
