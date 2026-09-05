"""Toolkit resolution, lock, and task-time toolkit contracts."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from agent_foundry.models.base import FoundryModel, FoundryModelError, VersionedContract
from agent_foundry.models.common import ExternalEffectClass
from agent_foundry.models.integrations import IntegrationHealth


class ToolkitResolutionError(FoundryModelError):
    """Raised when toolkit resolution fails closed."""


class PolicyViolationError(ToolkitResolutionError):
    """Raised when a forbidden capability or permission escalation is detected."""


class ResolutionAction(StrEnum):
    INCLUDE = "include"
    EXCLUDE = "exclude"


class ResolutionSource(StrEnum):
    PROJECT_FACT = "project-fact"
    POLICY = "policy"
    REGISTRY = "registry"
    WORK_ITEM = "work-item"
    COMPATIBILITY = "compatibility"


class ResolutionDecision(FoundryModel):
    """Explainable include/exclude decision tied to a project fact or policy."""

    action: ResolutionAction
    component_kind: str
    component_id: str
    rationale: str
    source: ResolutionSource
    project_fact: str | None = None
    policy_id: str | None = None


class ToolkitResolution(FoundryModel):
    """Result of resolving capabilities for a context — metadata only."""

    resolved_capabilities: list[str] = Field(default_factory=list)
    resolved_skills: list[str] = Field(default_factory=list)
    resolved_workflows: list[str] = Field(default_factory=list)
    integration_ids: list[str] = Field(default_factory=list)
    role_ids: list[str] = Field(default_factory=list)
    validator_ids: list[str] = Field(default_factory=list)
    permission_profile_ids: list[str] = Field(default_factory=list)
    budget_profile_ids: list[str] = Field(default_factory=list)
    decisions: list[ResolutionDecision] = Field(default_factory=list)
    integration_health: list[IntegrationHealth] = Field(default_factory=list)


class ToolkitLock(VersionedContract):
    """Pinned operational capability set."""

    project_name: str
    foundry_compat: str = ">=0.2,<0.3"
    capability_ids: list[str] = Field(default_factory=list)
    skill_ids: list[str] = Field(default_factory=list)
    workflow_ids: list[str] = Field(default_factory=list)
    integration_ids: list[str] = Field(default_factory=list)
    role_ids: list[str] = Field(default_factory=list)
    validator_ids: list[str] = Field(default_factory=list)
    permission_profile_ids: list[str] = Field(default_factory=list)
    budget_profile_ids: list[str] = Field(default_factory=list)
    skill_versions: dict[str, str] = Field(default_factory=dict)
    workflow_versions: dict[str, str] = Field(default_factory=dict)
    validator_versions: dict[str, str] = Field(default_factory=dict)
    integration_adapter_versions: dict[str, str] = Field(default_factory=dict)
    permission_profile_version: str | None = None
    declared_external_effect: ExternalEffectClass | None = None
    permission_external_effect: ExternalEffectClass | None = None
    budget_profile_version: str | None = None
    decisions: list[ResolutionDecision] = Field(default_factory=list)


class TaskToolkit(VersionedContract):
    """Minimum capability subset for one Work Item."""

    work_item_id: str
    capability_ids: list[str] = Field(default_factory=list)
    skill_ids: list[str] = Field(default_factory=list)
    workflow_id: str | None = None
    integration_ids: list[str] = Field(default_factory=list)
    role_ids: list[str] = Field(default_factory=list)
    validator_ids: list[str] = Field(default_factory=list)
    permission_profile_ids: list[str] = Field(default_factory=list)
    budget_profile_ids: list[str] = Field(default_factory=list)
    decisions: list[ResolutionDecision] = Field(default_factory=list)
