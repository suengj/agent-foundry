"""Reconciliation across genuinely divergent tracker, repository, and runtime states.

Each fixture below puts the three authorities into real disagreement and asserts
what reconciliation is allowed to conclude — and, just as importantly, what it is
not. The last section proves the whole path is read-only by executing it inside a
sandbox where every write, subprocess, and socket call raises.
"""

from __future__ import annotations

import builtins
import os
import pathlib
import socket
import subprocess

import pytest

from agent_foundry.models import (
    EvidenceClass,
    EvidenceItem,
    EvidenceResult,
    EvidenceState,
    IntegrationHealthState,
    ReconciliationDimension,
    ReviewOutcome,
    StateAuthority,
    ValidationOutcome,
    WorkLifecycleState,
)
from agent_foundry.verify import reconcile_work_item
from verify_support import (
    CANDIDATE_REVISION,
    approving_review,
    full_evidence_bundle,
    health,
    repository,
    runtime,
    sample_work_item,
    tracker,
)


def _messages(report) -> str:
    return " | ".join(finding.message for finding in report.findings)


# --- divergent fixtures -------------------------------------------------------


def test_tracker_says_done_while_the_repository_has_not_integrated():
    """Tracker: DONE. Repository: a candidate, no integration. Runtime: unobserved."""
    report = reconcile_work_item(
        work_item=sample_work_item(),
        tracker=tracker(lifecycle_state=WorkLifecycleState.DONE),
        repository=repository(integrated_revision=None),
        runtime=None,
    )

    assert report.outcome_for(ReconciliationDimension.WORK_LIFECYCLE) == ValidationOutcome.BLOCKED
    assert "reports done while evidence states" in _messages(report)

    merged = [
        finding
        for finding in report.findings
        if finding.dimension == ReconciliationDimension.EVIDENCE_STATE
        and finding.subject == EvidenceState.MERGED_INTEGRATED.value
    ]
    assert [finding.outcome for finding in merged] == [ValidationOutcome.MISSING]

    proposals = [p for p in report.proposals if p.field == "lifecycle_state"]
    assert len(proposals) == 1
    assert proposals[0].authority == StateAuthority.TRACKER
    assert proposals[0].proposed_value == WorkLifecycleState.IN_REVIEW.value
    assert proposals[0].requires_human is True


def test_repository_is_complete_while_the_runtime_still_serves_an_older_revision():
    """Tracker: IN_PROGRESS. Repository: integrated and reviewed. Runtime: stale."""
    report = reconcile_work_item(
        work_item=sample_work_item(
            runtime_external_validation_requirement="deployed revision must match",
        ),
        tracker=tracker(
            lifecycle_state=WorkLifecycleState.IN_PROGRESS,
            declared_not_required_evidence_states=[
                EvidenceState.USER_ACCEPTED,
                EvidenceState.SYSTEM_VERIFIED,
                EvidenceState.RUNTIME_APPLIED,
                EvidenceState.RUNTIME_VERIFIED,
            ],
        ),
        repository=repository(),
        runtime=runtime(applied_revision="rev-old-0000"),
    )

    assert report.outcome_for(ReconciliationDimension.RUNTIME_STATE) == ValidationOutcome.BLOCKED
    assert "but the expected revision is" in _messages(report)
    # Repository evidence is complete, so reconciliation may propose closing — and
    # marks it as a decision only the tracker authority can make.
    assert report.outcome_for(ReconciliationDimension.WORK_LIFECYCLE) == (
        ValidationOutcome.HUMAN_REQUIRED
    )
    closing = [p for p in report.proposals if p.proposed_value == WorkLifecycleState.DONE.value]
    assert len(closing) == 1
    assert closing[0].requires_human is True


def test_an_unobserved_runtime_is_missing_not_healthy():
    report = reconcile_work_item(
        work_item=sample_work_item(
            runtime_external_validation_requirement="deployed revision must match",
        ),
        tracker=tracker(),
        repository=repository(),
        runtime=None,
    )
    runtime_findings = [
        finding
        for finding in report.findings
        if finding.dimension == ReconciliationDimension.RUNTIME_STATE
    ]
    assert [finding.outcome for finding in runtime_findings] == [ValidationOutcome.MISSING]
    assert "an unobserved runtime is not an applied one" in _messages(report)


def test_a_runtime_record_marked_unobserved_does_not_count_as_evidence():
    """`observed=False` with a revision filled in is still not an observation."""
    report = reconcile_work_item(
        work_item=sample_work_item(
            runtime_external_validation_requirement="deployed revision must match",
        ),
        tracker=tracker(),
        repository=repository(),
        runtime=runtime(observed=False),
    )
    assert report.outcome_for(ReconciliationDimension.RUNTIME_STATE) == ValidationOutcome.MISSING


def test_runtime_is_not_required_when_the_work_item_declares_no_requirement():
    report = reconcile_work_item(
        work_item=sample_work_item(),
        tracker=tracker(),
        repository=repository(),
        runtime=None,
    )
    runtime_findings = [
        finding
        for finding in report.findings
        if finding.dimension == ReconciliationDimension.RUNTIME_STATE
    ]
    assert [finding.outcome for finding in runtime_findings] == [ValidationOutcome.NOT_REQUIRED]


def test_a_fully_agreeing_set_of_authorities_reconciles_clean():
    report = reconcile_work_item(
        work_item=sample_work_item(),
        tracker=tracker(lifecycle_state=WorkLifecycleState.DONE),
        repository=repository(),
        runtime=runtime(),
    )
    assert report.outcome_for(ReconciliationDimension.WORK_LIFECYCLE) == ValidationOutcome.PASS
    assert report.outcome_for(ReconciliationDimension.IDENTITY_LINKAGE) == ValidationOutcome.PASS
    assert report.proposals == []


def test_evidence_bundle_disagreeing_with_the_repository_revision_is_blocked():
    diverging = repository(
        evidence_bundle=full_evidence_bundle(
            identity={"candidate_revision": "rev-somewhere-else"}
        )
    )
    report = reconcile_work_item(
        work_item=sample_work_item(),
        tracker=tracker(),
        repository=diverging,
        runtime=None,
    )
    assert report.outcome_for(ReconciliationDimension.IDENTITY_LINKAGE) == ValidationOutcome.BLOCKED
    assert "while the repository reports" in _messages(report)


def test_an_unlinked_tracker_identity_is_missing():
    report = reconcile_work_item(
        work_item=sample_work_item(),
        tracker=tracker(external_ref=None),
        repository=repository(),
        runtime=None,
    )
    assert report.outcome_for(ReconciliationDimension.IDENTITY_LINKAGE) == ValidationOutcome.MISSING
    assert "not linked to a tracker identity" in _messages(report)


def test_an_undeclared_evidence_requirement_is_unresolved_not_satisfied():
    report = reconcile_work_item(
        work_item=sample_work_item(),
        tracker=tracker(
            declared_required_evidence_states=[],
            declared_not_required_evidence_states=[],
        ),
        repository=repository(),
        runtime=None,
    )
    assert report.outcome_for(ReconciliationDimension.EVIDENCE_STATE) == ValidationOutcome.MISSING
    assert "an unspecified requirement is unresolved, not satisfied" in _messages(report)


def test_a_rejected_review_does_not_attain_the_reviewed_state():
    rejected = repository(
        review_decision=approving_review(outcome=ReviewOutcome.CHANGES_REQUESTED, blocking=True)
    )
    report = reconcile_work_item(
        work_item=sample_work_item(),
        tracker=tracker(lifecycle_state=WorkLifecycleState.DONE),
        repository=rejected,
        runtime=None,
    )
    reviewed = [
        finding
        for finding in report.findings
        if finding.dimension == ReconciliationDimension.EVIDENCE_STATE
        and finding.subject == EvidenceState.REVIEWED.value
    ]
    assert [finding.outcome for finding in reviewed] == [ValidationOutcome.MISSING]


def test_failing_test_evidence_does_not_attain_the_validated_state():
    failing = repository(
        evidence_bundle=full_evidence_bundle(
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
    )
    report = reconcile_work_item(
        work_item=sample_work_item(),
        tracker=tracker(),
        repository=failing,
        runtime=None,
    )
    validated = [
        finding
        for finding in report.findings
        if finding.dimension == ReconciliationDimension.EVIDENCE_STATE
        and finding.subject == EvidenceState.VALIDATED.value
    ]
    assert [finding.outcome for finding in validated] == [ValidationOutcome.MISSING]


def test_an_unavailable_integration_blocks_and_an_unobserved_one_is_missing():
    blocked = reconcile_work_item(
        work_item=sample_work_item(),
        tracker=tracker(),
        repository=repository(),
        runtime=runtime(
            integration_health=[health("work-tracker", IntegrationHealthState.UNAVAILABLE)]
        ),
    )
    assert blocked.outcome_for(ReconciliationDimension.INTEGRATION_STATE) == (
        ValidationOutcome.BLOCKED
    )

    unobserved = reconcile_work_item(
        work_item=sample_work_item(),
        tracker=tracker(),
        repository=repository(),
        runtime=None,
    )
    assert unobserved.outcome_for(ReconciliationDimension.INTEGRATION_STATE) == (
        ValidationOutcome.MISSING
    )


def test_projections_describing_a_different_work_item_are_blocked_not_reconciled():
    report = reconcile_work_item(
        work_item=sample_work_item(),
        tracker=tracker(work_item_id="WI-SOMETHING-ELSE"),
        repository=repository(),
        runtime=None,
    )
    assert report.outcome_for(ReconciliationDimension.IDENTITY_LINKAGE) == ValidationOutcome.BLOCKED


# --- proposals are inert ---------------------------------------------------------


def test_every_external_proposal_requires_explicit_human_apply():
    report = reconcile_work_item(
        work_item=sample_work_item(),
        tracker=tracker(lifecycle_state=WorkLifecycleState.DONE),
        repository=repository(integrated_revision=None),
        runtime=None,
    )
    assert report.proposals
    for proposal in report.proposals:
        assert proposal.authority != StateAuthority.FOUNDRY
        assert proposal.requires_human is True


def test_a_proposal_against_an_external_authority_cannot_be_marked_auto_appliable():
    from agent_foundry.models import StateProposal

    with pytest.raises(Exception):
        StateProposal(
            authority=StateAuthority.TRACKER,
            work_item_id="WI-1",
            field="lifecycle_state",
            proposed_value="done",
            rationale="looks done to me",
            requires_human=False,
        )


def test_state_proposal_exposes_no_way_to_apply_itself():
    from agent_foundry.models import StateProposal

    callables = [
        name
        for name in dir(StateProposal)
        if not name.startswith("_") and callable(getattr(StateProposal, name, None))
    ]
    forbidden = {"apply", "commit", "push", "write", "send", "sync", "save"}
    assert forbidden.isdisjoint(callables), callables


def test_authority_dimension_escalates_when_external_proposals_exist():
    report = reconcile_work_item(
        work_item=sample_work_item(),
        tracker=tracker(lifecycle_state=WorkLifecycleState.DONE),
        repository=repository(integrated_revision=None),
        runtime=None,
    )
    assert report.outcome_for(ReconciliationDimension.AUTHORITY) == ValidationOutcome.HUMAN_REQUIRED
    assert "applies none" in _messages(report)


# --- no external state mutation on the default path -------------------------------


class ExternalMutationAttempted(AssertionError):
    """Raised the moment reconciliation reaches for the outside world."""


@pytest.fixture
def no_external_effects(monkeypatch):
    """Make every write, subprocess launch, and socket call fail loudly.

    This is stronger than reading the source for suspicious imports: any call that
    could reach a file, a process, or a network — from anywhere in the call graph,
    including a dependency — raises instead of succeeding.
    """
    real_open = builtins.open

    def guarded_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            raise ExternalMutationAttempted(f"open({file!r}, mode={mode!r})")
        return real_open(file, mode, *args, **kwargs)

    def refuse(name):
        def _refuse(*args, **kwargs):
            raise ExternalMutationAttempted(name)

        return _refuse

    monkeypatch.setattr(builtins, "open", guarded_open)
    for module, attribute in (
        (pathlib.Path, "write_text"),
        (pathlib.Path, "write_bytes"),
        (pathlib.Path, "mkdir"),
        (pathlib.Path, "unlink"),
        (pathlib.Path, "rename"),
        (pathlib.Path, "replace"),
        (pathlib.Path, "touch"),
        (os, "remove"),
        (os, "rename"),
        (os, "replace"),
        (os, "makedirs"),
        (os, "system"),
        (subprocess, "run"),
        (subprocess, "Popen"),
        (subprocess, "check_output"),
        (subprocess, "check_call"),
        (socket, "socket"),
        (socket, "create_connection"),
    ):
        monkeypatch.setattr(module, attribute, refuse(f"{module}.{attribute}"))
    yield


def test_reconciliation_performs_no_external_state_mutation(no_external_effects):
    """The default path touches no file, no process, and no socket."""
    report = reconcile_work_item(
        work_item=sample_work_item(
            runtime_external_validation_requirement="deployed revision must match",
        ),
        tracker=tracker(lifecycle_state=WorkLifecycleState.DONE),
        repository=repository(integrated_revision=None),
        runtime=runtime(applied_revision="rev-old-0000"),
    )
    assert report.findings
    assert report.proposals


def test_the_no_external_effects_sandbox_actually_bites(tmp_path, no_external_effects):
    """Guard the guard: the fixture must fail a real write, or it proves nothing."""
    probe = tmp_path / "probe.txt"
    with pytest.raises(ExternalMutationAttempted):
        probe.write_text("x")
    with pytest.raises(ExternalMutationAttempted):
        open(probe, "w")
    with pytest.raises(ExternalMutationAttempted):
        subprocess.run(["true"])
    with pytest.raises(ExternalMutationAttempted):
        socket.socket()


def test_validators_perform_no_external_state_mutation(no_external_effects):
    """The validation path is read-only for the same reason and by the same proof."""
    from agent_foundry.verify import (
        validate_evidence_bundle_completeness,
        validate_required_evidence,
        validate_work_dependency_graph,
    )

    work_item = sample_work_item()
    bundle = full_evidence_bundle()
    assert validate_required_evidence(work_item, bundle).findings
    assert validate_evidence_bundle_completeness(bundle).findings
    assert validate_work_dependency_graph([work_item]).findings
