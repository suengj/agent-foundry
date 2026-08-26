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
    work_item_ids: tuple[str, ...] = Field(default_factory=tuple)


class WorkItemContract(VersionedContract):
    """Independently closable work contract per constitution §7."""

    id: str
    title: str
    work_class: WorkClass
    objective: str
    current_facts: tuple[str, ...]
    scope: tuple[str, ...]
    out_of_scope: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    dependencies: tuple[DependencySpec, ...] = Field(default_factory=tuple)
    authority_class: ExternalEffectClass
    consequence_class: ConsequenceClass
    required_evidence: tuple[str, ...]
    stop_conditions: tuple[str, ...]
    escalation_conditions: tuple[str, ...] = Field(default_factory=tuple)
    runtime_external_validation_requirement: str | None = None
    implementation_references: tuple[str, ...] = Field(default_factory=tuple)
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
    evidence_states: tuple[EvidenceState, ...] = Field(default_factory=tuple)


class WorkItemExecutionContext(FoundryModel):
    """Work Item contract with attachable execution runs.

    Attaching a run returns a new context and never edits the contract. The
    contract is authority-bearing — `scope` bounds what a compiled bundle may
    write — so its sequence fields are tuples: `frozen=True` alone stops
    rebinding an attribute but leaves a `list` field open to in-place edit, and
    a scope widened that way would be invisible to every later authority check.
    """

    contract: WorkItemContract
    runs: tuple[ExecutionRunRef, ...] = Field(default_factory=tuple)


class AdoptionGap(FoundryModel):
    """Adoption readiness gap input for decomposition."""

    id: str
    target: str
    action: AdoptionAction
    rationale: str
    scope: tuple[str, ...] = Field(default_factory=tuple)
    """Repository paths the change touches.

    `target` names a logical surface ("test-harness"), which is not a path and so
    intersects with nothing when compiled write authority is computed. Without this,
    an adoption Work Item compiled for a builder carried repository-write authority
    over an empty write scope: a bundle that validates and authorizes nothing.
    Empty stays legal — a change to a file that does not exist yet has no path to
    name — and the resulting bundle grants no write, which is the honest outcome.
    """
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
    scope: tuple[str, ...] = Field(default_factory=tuple)
    out_of_scope: tuple[str, ...] = Field(default_factory=tuple)
    acceptance_criteria: tuple[str, ...] = Field(default_factory=tuple)
    required_evidence: tuple[str, ...] = Field(default_factory=tuple)
    stop_conditions: tuple[str, ...] = Field(default_factory=tuple)
    escalation_conditions: tuple[str, ...] = Field(default_factory=tuple)
    depends_on: tuple[str, ...] = Field(default_factory=tuple)
    mechanical_steps: tuple[str, ...] = Field(default_factory=tuple)
    current_facts: tuple[str, ...] = Field(default_factory=tuple)


class DecompositionQualityFlag(StrEnum):
    """Quality warnings detected during decomposition."""

    CROSS_OUTCOME_IDENTITY_COLLISION = "cross-outcome-identity-collision"
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
    related_ids: tuple[str, ...] = Field(default_factory=tuple)


class WorkPlan(VersionedContract):
    """Full tracker-neutral work hierarchy produced by decomposition."""

    objective: WorkObjective
    outcomes: tuple[OutcomeCapability, ...] = Field(default_factory=tuple)
    packages: tuple[WorkPackage, ...] = Field(default_factory=tuple)
    work_items: tuple[WorkItemContract, ...] = Field(default_factory=tuple)
    quality_issues: tuple[DecompositionQualityIssue, ...] = Field(default_factory=tuple)


class DecompositionInput(FoundryModel):
    """Structured input for the decomposition engine."""

    objective: WorkObjective
    outcomes: tuple[OutcomeCapability, ...]
    capability_units: tuple[CapabilityUnit, ...] = Field(default_factory=tuple)
    adoption_gaps: tuple[AdoptionGap, ...] = Field(default_factory=tuple)


def default_schema_version() -> str:
    """Canonical schema version for newly generated work contracts."""
    return FOUNDRY_SCHEMA_VERSION
