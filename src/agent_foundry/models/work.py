"""Work hierarchy and Work Item contract models."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from agent_foundry.models.base import FOUNDRY_SCHEMA_VERSION, FoundryModel, VersionedContract
from agent_foundry.models.common import (
    AdoptionAction,
    ConsequenceClass,
    DependencyRelation,
    EvidenceState,
    ExecutionState,
    ExternalEffectClass,
    Reversibility,
    WorkClass,
    WorkLifecycleState,
)


class DependencySpec(FoundryModel):
    """Dependency between work items."""

    relation: DependencyRelation
    target_id: str
    description: str | None = None


class WorkObjective(FoundryModel):
    """High-level objective driving work decomposition."""

    id: str
    title: str
    description: str


class OutcomeCapability(FoundryModel):
    """Measurable capability or outcome within an objective."""

    id: str
    objective_id: str
    title: str
    description: str


class WorkPackage(FoundryModel):
    """Bounded package of related work items."""

    id: str
    outcome_id: str
    title: str
    description: str
    work_item_ids: list[str] = Field(default_factory=list)


class WorkItemContract(VersionedContract):
    """Independently closable work contract per constitution §7."""

    id: str
    title: str
    work_class: WorkClass
    objective: str
    current_facts: list[str]
    scope: list[str]
    out_of_scope: list[str]
    acceptance_criteria: list[str]
    dependencies: list[DependencySpec] = Field(default_factory=list)
    authority_class: ExternalEffectClass
    consequence_class: ConsequenceClass
    required_evidence: list[str]
    stop_conditions: list[str]
    escalation_conditions: list[str] = Field(default_factory=list)
    runtime_external_validation_requirement: str | None = None
    implementation_references: list[str] = Field(default_factory=list)
    rollback_boundary_id: str | None = None
    write_scope_id: str | None = None


class WorkLifecycleSnapshot(FoundryModel):
    """Tracker-neutral work lifecycle state — distinct from execution and evidence."""

    work_item_id: str
    lifecycle_state: WorkLifecycleState


class ExecutionRunRef(FoundryModel):
    """Reserved extension point for one execution attempt against a Work Item."""

    id: str
    work_item_id: str
    execution_state: ExecutionState = ExecutionState.UNCLAIMED
    workspace_lease_id: str | None = None
    write_lease_id: str | None = None


class WorkspaceLeaseRef(FoundryModel):
    """Reserved extension point for isolated workspace ownership."""

    id: str
    work_item_id: str
    run_id: str | None = None


class WriteLeaseRef(FoundryModel):
    """Reserved extension point for scoped write authority during a run."""

    id: str
    work_item_id: str
    run_id: str | None = None
    write_scope_id: str


class EvidenceStateSnapshot(FoundryModel):
    """Evidence progression for a Work Item — distinct from lifecycle and execution."""

    work_item_id: str
    run_id: str | None = None
    evidence_states: list[EvidenceState] = Field(default_factory=list)


class WorkItemExecutionContext(FoundryModel):
    """Work Item contract with attachable execution runs.

    The contract object is not replaced when runs are attached, but list fields
    remain ordinarily mutable in Python unless callers treat them as read-only.
    """

    contract: WorkItemContract
    runs: list[ExecutionRunRef] = Field(default_factory=list)


class AdoptionGap(FoundryModel):
    """Adoption readiness gap input for decomposition."""

    id: str
    target: str
    action: AdoptionAction
    rationale: str
    suggested_work_class: WorkClass = WorkClass.ADOPTION
    authority_class: ExternalEffectClass = ExternalEffectClass.REPOSITORY_WRITE
    consequence_class: ConsequenceClass = ConsequenceClass.MEDIUM
    reversibility: Reversibility = Reversibility.VERSIONED
    blocker: bool = False


class CapabilityUnit(FoundryModel):
    """Atomic causal unit before decomposition grouping."""

    id: str
    outcome_id: str
    title: str
    description: str
    work_class: WorkClass
    acceptance_boundary_id: str
    authority_class: ExternalEffectClass
    consequence_class: ConsequenceClass
    rollback_boundary_id: str
    write_scope_id: str
    discovery_only: bool = False
    mutates_external: bool = False
    scope: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    required_evidence: list[str] = Field(default_factory=list)
    stop_conditions: list[str] = Field(default_factory=list)
    escalation_conditions: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    mechanical_steps: list[str] = Field(default_factory=list)
    current_facts: list[str] = Field(default_factory=list)


class DecompositionQualityFlag(StrEnum):
    """Quality warnings detected during decomposition."""

    MEGA_ITEM = "mega-item"
    FILE_SHAPED_DECOMPOSITION = "file-shaped-decomposition"
    ROLE_SHAPED_DECOMPOSITION = "role-shaped-decomposition"
    MIXED_DISCOVERY_AND_MUTATION = "mixed-discovery-and-mutation"
    MIXED_WORK_CLASS = "mixed-work-class"
    UNVERIFIABLE_ACCEPTANCE = "unverifiable-acceptance"


class DecompositionQualityIssue(FoundryModel):
    """Single quality issue tied to a work item or graph node."""

    flag: DecompositionQualityFlag
    work_item_id: str | None = None
    message: str
    related_ids: list[str] = Field(default_factory=list)


class WorkPlan(VersionedContract):
    """Full tracker-neutral work hierarchy produced by decomposition."""

    objective: WorkObjective
    outcomes: list[OutcomeCapability] = Field(default_factory=list)
    packages: list[WorkPackage] = Field(default_factory=list)
    work_items: list[WorkItemContract] = Field(default_factory=list)
    quality_issues: list[DecompositionQualityIssue] = Field(default_factory=list)


class DecompositionInput(FoundryModel):
    """Structured input for the decomposition engine."""

    objective: WorkObjective
    outcomes: list[OutcomeCapability]
    capability_units: list[CapabilityUnit] = Field(default_factory=list)
    adoption_gaps: list[AdoptionGap] = Field(default_factory=list)


def default_schema_version() -> str:
    """Canonical schema version for newly generated work contracts."""
    return FOUNDRY_SCHEMA_VERSION
