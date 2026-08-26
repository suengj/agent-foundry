"""Work hierarchy and Work Item contract models."""

from __future__ import annotations

from pydantic import Field

from agent_foundry.models.base import FoundryModel, VersionedContract
from agent_foundry.models.common import (
    ConsequenceClass,
    DependencyRelation,
    ExternalEffectClass,
    WorkClass,
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


class WorkPackage(FoundryModel):
    """Bounded package of related work items."""

    id: str
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
