"""Reconciliation across tracker, repository, and runtime authorities.

Foundry reconciles; it does not mirror and it does not apply. Everything here is a
pure function from three read-only projections to a report of agreement,
disagreement, and *proposals*. There is no adapter, no client, no path that reaches
a tracker or a runtime, and nothing in this module opens a file or a socket. That is
a structural property, not a convention: the inputs are data classes and the output
is a `ReconciliationReport`, so there is nothing here that could write even if a
caller wanted it to.

The other rule is that no fact is invented. A dimension nobody supplied evidence for
resolves to `MISSING`. `NOT_REQUIRED` appears only where a requirement was declared
absent. Neither ever collapses into `PASS`.
"""

from __future__ import annotations

from agent_foundry.models.common import (
    EvidenceState,
    IntegrationHealthState,
    ReconciliationDimension,
    ReviewOutcome,
    StateAuthority,
    ValidationOutcome,
    WorkLifecycleState,
)
from agent_foundry.models.verification import (
    ReconciliationFinding,
    ReconciliationReport,
    RepositoryEvidence,
    RuntimeReadback,
    StateProposal,
    TrackerProjection,
)
from agent_foundry.models.work import WorkItemContract

# Evidence states that can only be established by reading back applied external
# state. If a work item requires one of these, an unobserved runtime is decisive.
RUNTIME_EVIDENCE_STATES: frozenset[EvidenceState] = frozenset(
    {
        EvidenceState.RUNTIME_APPLIED,
        EvidenceState.RUNTIME_VERIFIED,
        EvidenceState.SYSTEM_VERIFIED,
    }
)

_TRACKER = StateAuthority.TRACKER
_REPOSITORY = StateAuthority.REPOSITORY
_RUNTIME = StateAuthority.RUNTIME


def _finding(
    dimension: ReconciliationDimension,
    outcome: ValidationOutcome,
    subject: str,
    message: str,
    authorities: list[StateAuthority],
    evidence_refs: list[str] | None = None,
) -> ReconciliationFinding:
    return ReconciliationFinding(
        dimension=dimension,
        outcome=outcome,
        subject=subject,
        message=message,
        authorities_consulted=authorities,
        evidence_refs=sorted(evidence_refs or []),
    )


def _partition_declarations(
    tracker: TrackerProjection,
) -> tuple[list[EvidenceState], list[EvidenceState], list[str]]:
    """Split a tracker's two declarations into recognised states and unrecognised names.

    Both lists get the same treatment. A projection built with `model_construct`, or
    read from a tracker whose vocabulary has drifted, can carry a raw string where the
    field type promises an `EvidenceState`; reaching for `.value` on one raises rather
    than rejecting it, and a reconciliation that crashes has concluded nothing.
    """
    known = {state.value: state for state in EvidenceState}
    required: list[EvidenceState] = []
    exempt: list[EvidenceState] = []
    unrecognised: list[str] = []

    for values, bucket in (
        (tracker.declared_required_evidence_states, required),
        (tracker.declared_not_required_evidence_states, exempt),
    ):
        for value in values:
            resolved = known.get(getattr(value, "value", str(value)))
            if resolved is None:
                unrecognised.append(str(value))
            else:
                bucket.append(resolved)

    return required, exempt, sorted(set(unrecognised))


def reconcile_work_item(
    *,
    work_item: WorkItemContract,
    tracker: TrackerProjection,
    repository: RepositoryEvidence,
    runtime: RuntimeReadback | None = None,
) -> ReconciliationReport:
    """Compare declared intent with implementation and applied state.

    Returns findings plus state proposals. It never applies a proposal, and every
    proposal against an authority other than Foundry itself is marked as requiring
    explicit human apply.
    """
    findings: list[ReconciliationFinding] = []
    proposals: list[StateProposal] = []

    required, exempt, unrecognised_states = _partition_declarations(tracker)

    findings.extend(_identity_findings(work_item, tracker, repository))
    lifecycle_findings, lifecycle_proposals = _lifecycle_findings(
        work_item, tracker, repository, required, exempt
    )
    findings.extend(lifecycle_findings)
    proposals.extend(lifecycle_proposals)
    findings.extend(
        _evidence_findings(work_item, repository, required, exempt, unrecognised_states)
    )
    findings.extend(_runtime_findings(work_item, repository, runtime, required, exempt))
    findings.extend(_integration_findings(work_item, runtime))

    authority_findings, authority_proposals = _authority_findings(work_item, proposals)
    findings.extend(authority_findings)
    proposals.extend(authority_proposals)

    return ReconciliationReport(
        work_item_id=work_item.id,
        findings=findings,
        proposals=proposals,
    )


def _identity_findings(
    work_item: WorkItemContract,
    tracker: TrackerProjection,
    repository: RepositoryEvidence,
) -> list[ReconciliationFinding]:
    dimension = ReconciliationDimension.IDENTITY_LINKAGE
    findings: list[ReconciliationFinding] = []
    authorities = [_TRACKER, _REPOSITORY]

    if tracker.work_item_id != work_item.id or repository.work_item_id != work_item.id:
        findings.append(
            _finding(
                dimension,
                ValidationOutcome.BLOCKED,
                work_item.id,
                f"projections describe {tracker.work_item_id!r} (tracker) and "
                f"{repository.work_item_id!r} (repository), not {work_item.id!r}",
                authorities,
            )
        )
        return findings

    if tracker.external_ref is None:
        findings.append(
            _finding(
                dimension,
                ValidationOutcome.MISSING,
                work_item.id,
                "tracker projection carries no external reference; the Foundry work "
                "item is not linked to a tracker identity",
                authorities,
            )
        )

    if repository.candidate_revision is None and repository.integrated_revision is None:
        findings.append(
            _finding(
                dimension,
                ValidationOutcome.MISSING,
                work_item.id,
                "repository reports neither a candidate nor an integrated revision; "
                "there is no implementation identity to reconcile against",
                authorities,
            )
        )

    bundle = repository.evidence_bundle
    if bundle is not None and bundle.identity is not None:
        claimed = bundle.identity.candidate_revision
        if (
            claimed is not None
            and repository.candidate_revision is not None
            and claimed != repository.candidate_revision
        ):
            findings.append(
                _finding(
                    dimension,
                    ValidationOutcome.BLOCKED,
                    work_item.id,
                    f"evidence bundle claims candidate revision {claimed!r} while the "
                    f"repository reports {repository.candidate_revision!r}",
                    authorities,
                )
            )

    if not findings:
        findings.append(
            _finding(
                dimension,
                ValidationOutcome.PASS,
                work_item.id,
                "tracker identity and repository revision identity agree",
                authorities,
            )
        )
    return findings


def _attained_states(
    repository: RepositoryEvidence,
    required: list[EvidenceState],
) -> set[EvidenceState]:
    """Evidence states the repository authority positively supports.

    Derived only from what the repository actually reports. Nothing is credited on
    the strength of a tracker label.
    """
    attained: set[EvidenceState] = set()
    bundle = repository.evidence_bundle

    if repository.candidate_revision is not None:
        attained.add(EvidenceState.IMPLEMENTED)
    if repository.integrated_revision is not None:
        attained.add(EvidenceState.MERGED_INTEGRATED)

    if bundle is not None:
        from agent_foundry.models.common import EvidenceClass, EvidenceResult

        passing = {
            item.evidence_class
            for item in bundle.items
            if item.result == EvidenceResult.PASS and item.evidence_class is not None
        }
        if EvidenceClass.DETERMINISTIC_TEST in passing:
            attained.add(EvidenceState.VALIDATED)
        if EvidenceClass.INTEGRATION_PROOF in passing:
            attained.add(EvidenceState.SYSTEM_VERIFIED)
        if EvidenceClass.RUNTIME_READBACK in passing:
            attained.add(EvidenceState.RUNTIME_VERIFIED)
        if EvidenceClass.HUMAN_ACCEPTANCE in passing:
            attained.add(EvidenceState.USER_ACCEPTED)

    decision = repository.review_decision
    if decision is not None and decision.outcome == ReviewOutcome.APPROVED:
        attained.add(EvidenceState.REVIEWED)

    return attained & set(required) if required else attained


def _lifecycle_findings(
    work_item: WorkItemContract,
    tracker: TrackerProjection,
    repository: RepositoryEvidence,
    required: list[EvidenceState],
    exempt: list[EvidenceState],
) -> tuple[list[ReconciliationFinding], list[StateProposal]]:
    dimension = ReconciliationDimension.WORK_LIFECYCLE
    findings: list[ReconciliationFinding] = []
    proposals: list[StateProposal] = []
    authorities = [_TRACKER, _REPOSITORY]

    if tracker.lifecycle_state is None:
        findings.append(
            _finding(
                dimension,
                ValidationOutcome.MISSING,
                work_item.id,
                "tracker projection declares no lifecycle state",
                authorities,
            )
        )
        return findings, proposals

    attained = _attained_states(repository, required)
    unresolved = sorted(
        state.value for state in set(required) - attained - set(exempt)
    )

    if tracker.lifecycle_state == WorkLifecycleState.DONE and unresolved:
        findings.append(
            _finding(
                dimension,
                ValidationOutcome.BLOCKED,
                work_item.id,
                f"tracker reports done while evidence states {unresolved} are neither "
                "attained nor declared not-required",
                authorities,
            )
        )
        proposals.append(
            StateProposal(
                authority=_TRACKER,
                work_item_id=work_item.id,
                field="lifecycle_state",
                current_value=tracker.lifecycle_state.value,
                proposed_value=WorkLifecycleState.IN_REVIEW.value,
                rationale=(
                    "repository evidence does not support closure; reopening is a "
                    f"tracker decision. Unresolved: {unresolved}"
                ),
                requires_human=True,
            )
        )
    elif tracker.lifecycle_state != WorkLifecycleState.DONE and required and not unresolved:
        findings.append(
            _finding(
                dimension,
                ValidationOutcome.HUMAN_REQUIRED,
                work_item.id,
                f"every required evidence state is resolved while the tracker reports "
                f"{tracker.lifecycle_state.value}; closing the item is a tracker "
                "decision Foundry may propose but not make",
                authorities,
            )
        )
        proposals.append(
            StateProposal(
                authority=_TRACKER,
                work_item_id=work_item.id,
                field="lifecycle_state",
                current_value=tracker.lifecycle_state.value,
                proposed_value=WorkLifecycleState.DONE.value,
                rationale="every required evidence state is attained or declared exempt",
                requires_human=True,
            )
        )
    else:
        findings.append(
            _finding(
                dimension,
                ValidationOutcome.PASS,
                work_item.id,
                f"tracker lifecycle {tracker.lifecycle_state.value} is consistent with "
                "the evidence the repository supports",
                authorities,
            )
        )
    return findings, proposals


def _evidence_findings(
    work_item: WorkItemContract,
    repository: RepositoryEvidence,
    required: list[EvidenceState],
    exempt: list[EvidenceState],
    unrecognised: list[str] = [],
) -> list[ReconciliationFinding]:
    dimension = ReconciliationDimension.EVIDENCE_STATE
    authorities = [_REPOSITORY]

    unrecognised_findings = [
        _finding(
            dimension,
            ValidationOutcome.BLOCKED,
            state,
            f"{state!r} is declared as an evidence state but names none; a declaration "
            "that identifies no obligation can neither be required nor exempted",
            [_TRACKER],
        )
        for state in unrecognised
    ]

    if not required and not exempt:
        return unrecognised_findings + [
            _finding(
                dimension,
                ValidationOutcome.MISSING,
                work_item.id,
                "no authority declares which evidence states this work item requires; "
                "an unspecified requirement is unresolved, not satisfied",
                authorities,
            )
        ]

    attained = _attained_states(repository, required)
    findings: list[ReconciliationFinding] = list(unrecognised_findings)
    for state in sorted(set(required) | set(exempt), key=lambda item: item.value):
        if state in exempt:
            findings.append(
                _finding(
                    dimension,
                    ValidationOutcome.NOT_REQUIRED,
                    state.value,
                    "declared not required for this work item",
                    authorities,
                )
            )
        elif state in attained:
            findings.append(
                _finding(
                    dimension,
                    ValidationOutcome.PASS,
                    state.value,
                    "supported by repository evidence",
                    authorities,
                )
            )
        else:
            findings.append(
                _finding(
                    dimension,
                    ValidationOutcome.MISSING,
                    state.value,
                    "required but not supported by any repository evidence",
                    authorities,
                )
            )
    return findings


def _runtime_findings(
    work_item: WorkItemContract,
    repository: RepositoryEvidence,
    runtime: RuntimeReadback | None,
    required: list[EvidenceState],
    exempt: list[EvidenceState],
) -> list[ReconciliationFinding]:
    dimension = ReconciliationDimension.RUNTIME_STATE
    authorities = [_RUNTIME, _REPOSITORY]

    runtime_required = bool(set(required) & RUNTIME_EVIDENCE_STATES) or bool(
        work_item.runtime_external_validation_requirement
    )
    if not runtime_required:
        return [
            _finding(
                dimension,
                ValidationOutcome.NOT_REQUIRED,
                work_item.id,
                "the work item declares no runtime or external validation requirement "
                "and requires no runtime evidence state",
                authorities,
            )
        ]

    if runtime is None or not runtime.observed:
        return [
            _finding(
                dimension,
                ValidationOutcome.MISSING,
                work_item.id,
                "runtime state was not read back; an unobserved runtime is not an "
                "applied one",
                authorities,
            )
        ]

    expected = runtime.expected_revision or repository.integrated_revision
    if expected is None:
        return [
            _finding(
                dimension,
                ValidationOutcome.MISSING,
                work_item.id,
                "no integrated revision to compare the runtime against",
                authorities,
                evidence_refs=[runtime.source_ref] if runtime.source_ref else None,
            )
        ]
    if runtime.applied_revision is None:
        return [
            _finding(
                dimension,
                ValidationOutcome.MISSING,
                work_item.id,
                "runtime read-back reports no applied revision",
                authorities,
                evidence_refs=[runtime.source_ref] if runtime.source_ref else None,
            )
        ]
    if runtime.applied_revision != expected:
        return [
            _finding(
                dimension,
                ValidationOutcome.BLOCKED,
                work_item.id,
                f"runtime has {runtime.applied_revision!r} applied, but the expected "
                f"revision is {expected!r}",
                authorities,
                evidence_refs=[runtime.source_ref] if runtime.source_ref else None,
            )
        ]
    return [
        _finding(
            dimension,
            ValidationOutcome.PASS,
            work_item.id,
            f"runtime read-back confirms {expected!r} is applied",
            authorities,
            evidence_refs=[runtime.source_ref] if runtime.source_ref else None,
        )
    ]


def _integration_findings(
    work_item: WorkItemContract,
    runtime: RuntimeReadback | None,
) -> list[ReconciliationFinding]:
    dimension = ReconciliationDimension.INTEGRATION_STATE
    authorities = [_RUNTIME]

    if runtime is None or not runtime.observed:
        return [
            _finding(
                dimension,
                ValidationOutcome.MISSING,
                work_item.id,
                "no integration health was observed",
                authorities,
            )
        ]
    if not runtime.integration_health:
        return [
            _finding(
                dimension,
                ValidationOutcome.MISSING,
                work_item.id,
                "runtime read-back reports no integration health entries",
                authorities,
            )
        ]

    findings: list[ReconciliationFinding] = []
    for health in sorted(runtime.integration_health, key=lambda item: item.integration_id):
        if health.state == IntegrationHealthState.UNAVAILABLE:
            outcome = ValidationOutcome.BLOCKED
        elif health.state in {
            IntegrationHealthState.HEALTHY,
            IntegrationHealthState.DEGRADED,
            IntegrationHealthState.AUTHORIZED,
        }:
            outcome = ValidationOutcome.PASS
        else:
            outcome = ValidationOutcome.MISSING
        findings.append(
            _finding(
                dimension,
                outcome,
                health.integration_id,
                f"observed state {health.state.value}",
                authorities,
            )
        )
    return findings


def _authority_findings(
    work_item: WorkItemContract,
    proposals: list[StateProposal],
) -> tuple[list[ReconciliationFinding], list[StateProposal]]:
    dimension = ReconciliationDimension.AUTHORITY
    authorities = [StateAuthority.FOUNDRY]

    external = [
        proposal for proposal in proposals if proposal.authority != StateAuthority.FOUNDRY
    ]
    if not external:
        return (
            [
                _finding(
                    dimension,
                    ValidationOutcome.PASS,
                    work_item.id,
                    "reconciliation proposes no change to an external authority",
                    authorities,
                )
            ],
            [],
        )
    return (
        [
            _finding(
                dimension,
                ValidationOutcome.HUMAN_REQUIRED,
                work_item.id,
                f"{len(external)} proposal(s) target an external authority; Foundry "
                "proposes them and applies none",
                authorities,
            )
        ],
        [],
    )
