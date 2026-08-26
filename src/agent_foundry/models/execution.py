"""Execution bundle — compiled agent run contract."""

from __future__ import annotations

from pydantic import Field

from agent_foundry.models.base import FoundryModel, VersionedContract
from agent_foundry.models.common import ExternalEffectClass
from agent_foundry.models.toolkit import ResolutionSource, TaskToolkit


class SkillSummary(FoundryModel):
    """Compact skill metadata for agent-facing projection — not full Skill text."""

    skill_id: str
    description: str
    relevance: str


class BundleProvenanceRecord(FoundryModel):
    """Provenance for a compile-time selection or exclusion."""

    component_kind: str
    component_id: str
    selected: bool
    rationale: str
    source: ResolutionSource
    project_fact: str | None = None
    policy_id: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class CompiledAuthority(FoundryModel):
    """Authority surface after intersection of work item, role, toolkit, and policy."""

    external_effect: ExternalEffectClass
    write_scope: list[str] = Field(default_factory=list)
    forbidden_scopes: list[str] = Field(default_factory=list)


class ExecutionBundle(VersionedContract):
    """Role-specific execution contract compiled from Work Item + toolkit."""

    work_item_id: str
    run_id: str
    role_id: str
    objective: str
    scope: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    allowed_capabilities: list[str] = Field(default_factory=list)
    write_scope: list[str] = Field(default_factory=list)
    required_evidence: list[str] = Field(default_factory=list)
    integration_ids: list[str] = Field(default_factory=list)
    project_name: str | None = None
    authority: CompiledAuthority | None = None
    forbidden_capabilities: list[str] = Field(default_factory=list)
    context_refs: list[str] = Field(default_factory=list)
    selected_conventions: list[str] = Field(default_factory=list)
    selected_observations: list[str] = Field(default_factory=list)
    policy_ids: list[str] = Field(default_factory=list)
    task_toolkit: TaskToolkit | None = None
    budget_profile_id: str | None = None
    max_retry_budget: int | None = None
    max_parallel_runs: int | None = None
    validator_ids: list[str] = Field(default_factory=list)
    stop_conditions: list[str] = Field(default_factory=list)
    escalation_conditions: list[str] = Field(default_factory=list)
    skill_summaries: list[SkillSummary] = Field(default_factory=list)
    interaction_outputs: list[str] = Field(default_factory=list)
    provenance: list[BundleProvenanceRecord] = Field(default_factory=list)
