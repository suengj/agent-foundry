"""Agent interaction, evidence, review, and execution receipt contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Self

from pydantic import Field, field_serializer, field_validator, model_validator

from agent_foundry.models.base import (
    FoundryModel,
    FoundryModelError,
    VersionedContract,
    serialize_datetime_utc,
)
from agent_foundry.models.common import (
    EvidenceClass,
    EvidenceResult,
    EvidenceState,
    ExecutionState,
    FailureCategory,
    FindingDisposition,
    MessageType,
    Provenance,
    ReviewOutcome,
    WorkLifecycleState,
)


class ReceiptContractError(FoundryModelError):
    """Raised when a receipt or finding contract is internally inconsistent."""


def _parse_optional_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise TypeError(f"expected datetime or ISO-8601 string, got {type(value)!r}")


class Handoff(FoundryModel):
    """Structured handoff between roles."""

    message_type: MessageType = MessageType.HANDOFF
    work_item_id: str
    run_id: str
    sender_role: str
    receiver_role: str
    summary: str
    evidence_refs: list[str] = Field(default_factory=list)
    known_risks: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)


class EvidenceItem(FoundryModel):
    """Single evidence artifact reference.

    `kind` stays a free-form label for human reading. `evidence_class` is the typed
    claim a required-evidence check consumes: an item that declares no class proves
    nothing in particular, and saying so is the point.
    """

    kind: str
    ref: str
    description: str | None = None
    evidence_class: EvidenceClass | None = None
    result: EvidenceResult | None = None
    proves_revision: str | None = None
    observed_at: datetime | None = None
    provenance: Provenance | None = None

    @field_validator("observed_at", mode="before")
    @classmethod
    def _parse_observed_at(cls, value: Any) -> datetime | None:
        return _parse_optional_datetime(value)

    @field_serializer("observed_at")
    def _serialize_observed_at(self, value: datetime | None) -> str | None:
        return None if value is None else serialize_datetime_utc(value)


class EvidenceIdentity(FoundryModel):
    """Revision identities an evidence bundle is about (docs/foundry/06 §5)."""

    base_revision: str | None = None
    candidate_revision: str | None = None
    integrated_revision: str | None = None


class RunFinding(FoundryModel):
    """Finding with an explicit disposition (docs/foundry/06 §9).

    Each disposition carries a different obligation, and the obligation is enforced
    here rather than left to a caller's discipline: a RESIDUAL without follow-up work
    and a HYPOTHESIS without a falsifiable prediction are how bounded weaknesses
    quietly become permanent.
    """

    id: str
    disposition: FindingDisposition
    summary: str
    evidence_refs: list[str] = Field(default_factory=list)
    follow_up_work_ref: str | None = None
    falsifiable_prediction: str | None = None
    evidence_condition: str | None = None
    escalation_reason: str | None = None
    failure_category: FailureCategory | None = None

    @model_validator(mode="after")
    def _disposition_obligations(self) -> Self:
        for message in disposition_obligation_violations(
            disposition=self.disposition,
            finding_id=self.id,
            evidence_refs=self.evidence_refs,
            follow_up_work_ref=self.follow_up_work_ref,
            falsifiable_prediction=self.falsifiable_prediction,
            evidence_condition=self.evidence_condition,
            escalation_reason=self.escalation_reason,
        ):
            raise ReceiptContractError(message)
        return self


def disposition_obligation_violations(
    *,
    disposition: FindingDisposition | str,
    finding_id: str,
    evidence_refs: list[str],
    follow_up_work_ref: str | None,
    falsifiable_prediction: str | None,
    evidence_condition: str | None,
    escalation_reason: str | None,
) -> list[str]:
    """Obligations a disposition owes, expressed over plain values.

    Kept as a free function over primitives so a validator can apply the same rule
    to a deserialized payload that never passed through `RunFinding.__init__`.
    """
    violations: list[str] = []
    value = disposition.value if isinstance(disposition, FindingDisposition) else str(disposition)
    if value == FindingDisposition.BLOCKER.value and not evidence_refs:
        violations.append(f"finding {finding_id!r}: BLOCKER requires at least one evidence_ref")
    if value == FindingDisposition.RESIDUAL.value and not follow_up_work_ref:
        violations.append(f"finding {finding_id!r}: RESIDUAL requires follow_up_work_ref")
    if value == FindingDisposition.HYPOTHESIS.value:
        if not falsifiable_prediction:
            violations.append(
                f"finding {finding_id!r}: HYPOTHESIS requires falsifiable_prediction"
            )
        if not evidence_condition:
            violations.append(f"finding {finding_id!r}: HYPOTHESIS requires evidence_condition")
    if value == FindingDisposition.HUMAN_REQUIRED.value and not escalation_reason:
        violations.append(f"finding {finding_id!r}: HUMAN_REQUIRED requires escalation_reason")
    return violations


class EvidenceBundle(VersionedContract):
    """Collected evidence for work verification (docs/foundry/06 §5).

    `not_required_classes` is declared, never inferred. An evidence class that is
    simply absent from both lists is unresolved, not exempt.
    """

    work_item_id: str
    run_id: str
    items: list[EvidenceItem] = Field(default_factory=list)
    identity: EvidenceIdentity | None = None
    not_required_classes: list[EvidenceClass] = Field(default_factory=list)
    unresolved: list[RunFinding] = Field(default_factory=list)
    provenance: list[Provenance] = Field(default_factory=list)


class ReviewDecision(FoundryModel):
    """Independent review outcome.

    `implementing_role_id` records who the review is independent *of*. A review by
    the role that produced the change is not an independent review, so the two ids
    may not be equal.
    """

    work_item_id: str
    run_id: str
    reviewer_role: str
    outcome: ReviewOutcome
    findings: list[str] = Field(default_factory=list)
    blocking: bool = False
    implementing_role_id: str | None = None
    reviewed_revision: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    decided_at: datetime | None = None

    @field_validator("decided_at", mode="before")
    @classmethod
    def _parse_decided_at(cls, value: Any) -> datetime | None:
        return _parse_optional_datetime(value)

    @field_serializer("decided_at")
    def _serialize_decided_at(self, value: datetime | None) -> str | None:
        return None if value is None else serialize_datetime_utc(value)

    @model_validator(mode="after")
    def _reviewer_is_independent(self) -> Self:
        if self.implementing_role_id is not None and self.implementing_role_id == self.reviewer_role:
            raise ReceiptContractError(
                f"review of {self.work_item_id!r} names {self.reviewer_role!r} as both "
                "reviewer and implementing role; that is not an independent review"
            )
        return self


class ArtifactIdentity(FoundryModel):
    """Exact identity of a configuration artifact a run consumed.

    `digest` binds the receipt to one specific artifact body; `version` names the
    pinned release. Both are recorded because they answer different questions.
    """

    kind: str
    ref: str
    digest: str | None = None
    version: str | None = None


class BudgetConsumption(FoundryModel):
    """Budget actually consumed against the profile the run was granted."""

    retries_used: int | None = Field(default=None, ge=0)
    parallel_runs_peak: int | None = Field(default=None, ge=0)
    tokens_used: int | None = Field(default=None, ge=0)
    max_retry_budget: int | None = Field(default=None, ge=0)
    max_parallel_runs: int | None = Field(default=None, ge=0)
    token_budget: int | None = Field(default=None, ge=0)


class ReceiptLimitation(FoundryModel):
    """Something this run did NOT establish, recorded explicitly.

    A limitation is the positive record of an absence. Without it, "no finding" and
    "never checked" are indistinguishable in the receipt.
    """

    subject: str
    reason: str
    evidence_class: EvidenceClass | None = None


class ExecutionReceipt(VersionedContract):
    """Receipt of an execution run (docs/foundry/06 §8).

    Three lifecycles are recorded in three fields and are never merged:
    `work_lifecycle_state` (tracker intent), `execution_state` (this run), and the
    evidence lists (what is proven). `evidence_state` is retained as a single-state
    projection for existing consumers; it is not the record, and a receipt that
    carries only that field is treated as incomplete by validation.
    """

    work_item_id: str
    run_id: str
    role_id: str
    work_lifecycle_state: WorkLifecycleState
    execution_state: ExecutionState
    evidence_state: EvidenceState
    started_at: datetime
    finished_at: datetime | None = None
    evidence_bundle_id: str | None = None

    attained_evidence_states: list[EvidenceState] = Field(default_factory=list)
    not_required_evidence_states: list[EvidenceState] = Field(default_factory=list)

    workflow_id: str | None = None
    base_revision: str | None = None
    candidate_revision: str | None = None
    integrated_revision: str | None = None

    artifact_identities: list[ArtifactIdentity] = Field(default_factory=list)
    adapter_versions: dict[str, str] = Field(default_factory=dict)
    permission_profile_id: str | None = None
    permission_profile_version: str | None = None
    budget_profile_id: str | None = None
    budget_profile_version: str | None = None

    review_decision: ReviewDecision | None = None
    runtime_verification_ref: str | None = None
    findings: list[RunFinding] = Field(default_factory=list)
    limitations: list[ReceiptLimitation] = Field(default_factory=list)
    budget: BudgetConsumption | None = None
    cleanup_state: str | None = None
    next_action: str | None = None

    @field_validator("started_at", "finished_at", mode="before")
    @classmethod
    def _parse_datetime(cls, value: Any) -> datetime | None:
        return _parse_optional_datetime(value)

    @field_serializer("started_at", "finished_at")
    def _serialize_datetime(self, value: datetime | None) -> str | None:
        return None if value is None else serialize_datetime_utc(value)

    @model_validator(mode="after")
    def _evidence_states_are_consistent(self) -> Self:
        for message in evidence_state_partition_violations(
            attained=[state.value for state in self.attained_evidence_states],
            not_required=[state.value for state in self.not_required_evidence_states],
        ):
            raise ReceiptContractError(f"receipt {self.run_id!r}: {message}")
        return self


def evidence_state_partition_violations(
    *,
    attained: list[str],
    not_required: list[str],
) -> list[str]:
    """Partition rules for the two evidence-state lists, over plain values.

    A state cannot be both attained and exempt, and `NOT_REQUIRED` is the marker for
    the exempt list rather than an attainment. Expressed over strings so a validator
    can apply it to a payload that bypassed model construction.
    """
    violations: list[str] = []
    overlap = sorted(set(attained) & set(not_required))
    if overlap:
        violations.append(
            f"evidence states {overlap} are declared both attained and not-required"
        )
    if EvidenceState.NOT_REQUIRED.value in attained:
        violations.append(
            "NOT_REQUIRED is an exemption, not an attained evidence state"
        )
    return violations
