"""Validation, reconciliation, explainability, and failure-classification contracts.

These are result types. Nothing here performs I/O or holds an adapter handle: a
reconciliation result is a description of disagreement plus proposals, and the type
system is where that read-only property is made structural rather than promised.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Self

from pydantic import Field, field_serializer, field_validator, model_validator

from agent_foundry.models.base import FoundryModel, serialize_datetime_utc
from agent_foundry.models.common import (
    EvidenceState,
    FailureCategory,
    Provenance,
    ProvenanceKind,
    ReconciliationDimension,
    StateAuthority,
    ValidationOutcome,
    WorkLifecycleState,
    ExecutionState,
)
from agent_foundry.models.integrations import IntegrationHealth
from agent_foundry.models.interaction import EvidenceBundle, ReviewDecision

# Severity ordering used to project many findings onto one outcome. BLOCKED outranks
# HUMAN_REQUIRED because a broken contract is a fact, while reserved authority is a
# decision still open; both outrank MISSING, which outranks PASS. NOT_REQUIRED is the
# floor so that an all-exempt report does not read as a pass it never earned.
_OUTCOME_SEVERITY: dict[str, int] = {
    ValidationOutcome.NOT_REQUIRED.value: 0,
    ValidationOutcome.PASS.value: 1,
    ValidationOutcome.MISSING.value: 2,
    ValidationOutcome.HUMAN_REQUIRED.value: 3,
    ValidationOutcome.BLOCKED.value: 4,
}

ACCEPTING_OUTCOMES: frozenset[ValidationOutcome] = frozenset(
    {ValidationOutcome.PASS, ValidationOutcome.NOT_REQUIRED}
)


def outcome_severity(outcome: ValidationOutcome) -> int:
    """Rank of an outcome for worst-wins aggregation."""
    return _OUTCOME_SEVERITY[outcome.value]


def worst_outcome(outcomes: list[ValidationOutcome]) -> ValidationOutcome:
    """Most severe outcome in a set.

    An empty set resolves to MISSING, not PASS: a report with no findings has checked
    nothing, and "nothing was checked" must never present as "everything passed".
    """
    if not outcomes:
        return ValidationOutcome.MISSING
    return max(outcomes, key=outcome_severity)


class ValidatorClaim(FoundryModel):
    """What one validator proves, and what it explicitly does not.

    `independently_derived` is False only where a property genuinely cannot be
    restated without the producing implementation; `cannot_prove` then has to say
    what the check is still worth.
    """

    validator_id: str
    proves: str
    cannot_prove: str
    independently_derived: bool
    checks_output_of: str | None = None


class ValidationFinding(FoundryModel):
    """One check applied to one subject."""

    validator_id: str
    outcome: ValidationOutcome
    subject: str
    message: str
    evidence_refs: list[str] = Field(default_factory=list)


class ValidationReport(FoundryModel):
    """Findings from one validator run over one subject."""

    subject_kind: str
    subject_id: str
    findings: list[ValidationFinding] = Field(default_factory=list)

    def outcome(self) -> ValidationOutcome:
        return worst_outcome([finding.outcome for finding in self.findings])

    def accepted(self) -> bool:
        """True only when every finding is PASS or a declared NOT_REQUIRED."""
        return bool(self.findings) and all(
            finding.outcome in ACCEPTING_OUTCOMES for finding in self.findings
        )

    def rejecting(self) -> list[ValidationFinding]:
        return [finding for finding in self.findings if finding.outcome not in ACCEPTING_OUTCOMES]


class TrackerProjection(FoundryModel):
    """Read-only projection of tracker-held work state.

    This is a snapshot handed to reconciliation, not a connection. There is no write
    path through this type, which is why reconciliation cannot mutate a tracker even
    by mistake.
    """

    work_item_id: str
    lifecycle_state: WorkLifecycleState | None = None
    external_ref: str | None = None
    declared_required_evidence_states: list[EvidenceState] = Field(default_factory=list)
    declared_not_required_evidence_states: list[EvidenceState] = Field(default_factory=list)
    observed_at: datetime | None = None
    source_ref: str | None = None

    @field_validator("observed_at", mode="before")
    @classmethod
    def _parse_observed_at(cls, value: Any) -> datetime | None:
        if value is None or isinstance(value, datetime):
            return value
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        raise TypeError(f"expected datetime or ISO-8601 string, got {type(value)!r}")

    @field_serializer("observed_at")
    def _serialize_observed_at(self, value: datetime | None) -> str | None:
        return None if value is None else serialize_datetime_utc(value)


class RepositoryEvidence(FoundryModel):
    """Implementation and review evidence held by the repository authority."""

    work_item_id: str
    base_revision: str | None = None
    candidate_revision: str | None = None
    integrated_revision: str | None = None
    evidence_bundle: EvidenceBundle | None = None
    review_decision: ReviewDecision | None = None
    execution_state: ExecutionState | None = None


class RuntimeReadback(FoundryModel):
    """Read-back of applied external state.

    `observed` defaults to False and is the only thing that makes the rest of this
    record mean anything. An unobserved runtime is not a healthy runtime, and the
    default value is chosen so that forgetting to set it fails toward MISSING.
    """

    work_item_id: str
    observed: bool = False
    applied_revision: str | None = None
    expected_revision: str | None = None
    integration_health: list[IntegrationHealth] = Field(default_factory=list)
    source_ref: str | None = None
    observed_at: datetime | None = None

    @field_validator("observed_at", mode="before")
    @classmethod
    def _parse_observed_at(cls, value: Any) -> datetime | None:
        if value is None or isinstance(value, datetime):
            return value
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        raise TypeError(f"expected datetime or ISO-8601 string, got {type(value)!r}")

    @field_serializer("observed_at")
    def _serialize_observed_at(self, value: datetime | None) -> str | None:
        return None if value is None else serialize_datetime_utc(value)


class StateProposal(FoundryModel):
    """A state update Foundry proposes to an authority.

    A proposal is inert by construction: it names a target and a value, and carries
    no capacity to deliver either. Applying one is a separate, authorized action
    outside this module.
    """

    authority: StateAuthority
    work_item_id: str
    field: str
    current_value: str | None = None
    proposed_value: str | None = None
    rationale: str
    requires_human: bool = True

    @model_validator(mode="after")
    def _external_authorities_require_human(self) -> Self:
        if self.authority != StateAuthority.FOUNDRY and not self.requires_human:
            raise ValueError(
                f"proposal against {self.authority.value} authority cannot be marked "
                "requires_human=False; external writes default to explicit apply"
            )
        return self


class ReconciliationFinding(FoundryModel):
    """Disagreement (or agreement) on one dimension across authorities."""

    dimension: ReconciliationDimension
    outcome: ValidationOutcome
    subject: str
    message: str
    authorities_consulted: list[StateAuthority] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class ReconciliationReport(FoundryModel):
    """Result of comparing tracker, repository, and runtime facts."""

    work_item_id: str
    findings: list[ReconciliationFinding] = Field(default_factory=list)
    proposals: list[StateProposal] = Field(default_factory=list)

    def outcome(self) -> ValidationOutcome:
        return worst_outcome([finding.outcome for finding in self.findings])

    def outcome_for(self, dimension: ReconciliationDimension) -> ValidationOutcome:
        return worst_outcome(
            [finding.outcome for finding in self.findings if finding.dimension == dimension]
        )


class FailureSignal(FoundryModel):
    """Structured record of one failed attempt.

    `message` is present for humans and is deliberately not consulted by
    classification. Categorising on narration is how a harness fault gets filed as a
    code defect and retried forever.
    """

    run_id: str
    attempt: int = Field(ge=1)
    denied_capabilities: list[str] = Field(default_factory=list)
    missing_context_refs: list[str] = Field(default_factory=list)
    violated_contract_ids: list[str] = Field(default_factory=list)
    failing_tool_ids: list[str] = Field(default_factory=list)
    harness_markers: list[str] = Field(default_factory=list)
    message: str | None = None


class FailureClassification(FoundryModel):
    """Category assigned to one signal, with the fields that supported it."""

    run_id: str
    attempt: int
    category: FailureCategory
    supporting_fields: list[str] = Field(default_factory=list)
    candidate_categories: list[FailureCategory] = Field(default_factory=list)
    rationale: str


class RepeatedFailureAssessment(FoundryModel):
    """Assessment across repeated attempts (docs/foundry/06 §10)."""

    category: FailureCategory
    occurrences: int = Field(ge=0)
    run_ids: list[str] = Field(default_factory=list)
    classifications: list[FailureClassification] = Field(default_factory=list)
    suspect_harness_or_contract: bool = False
    escalate: bool = False
    rationale: str


class DecisionTraceEntry(FoundryModel):
    """Why one component was selected or excluded."""

    component_kind: str
    component_id: str
    selected: bool
    causing_facts: list[str] = Field(default_factory=list)
    causing_policies: list[str] = Field(default_factory=list)
    provenance_kind: ProvenanceKind | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class AuthorityTightening(FoundryModel):
    """Effect of inferred facts on one authority axis.

    `declared_only` is the level supportable from declared/observed facts alone.
    `widened` is True when adding inferred facts raised it — inference may narrow
    authority, never grant it.
    """

    axis: str
    declared_only: str | None = None
    with_inferred: str | None = None
    widened: bool = False
    rationale: str


class LifecycleSeparation(FoundryModel):
    """The three lifecycles side by side, in three fields that stay three fields."""

    work_lifecycle_state: WorkLifecycleState | None = None
    execution_state: ExecutionState | None = None
    attained_evidence_states: list[EvidenceState] = Field(default_factory=list)
    not_required_evidence_states: list[EvidenceState] = Field(default_factory=list)


class DecisionTrace(FoundryModel):
    """Structured audit trail for a compiled run — evidence, not narration."""

    work_item_id: str
    run_id: str
    role_id: str
    entries: list[DecisionTraceEntry] = Field(default_factory=list)
    authority_tightening: list[AuthorityTightening] = Field(default_factory=list)
    lifecycle_separation: LifecycleSeparation = Field(default_factory=LifecycleSeparation)
    classification_provenance: list[Provenance] = Field(default_factory=list)
