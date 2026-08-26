"""Toolkit resolution, lock, and task-time toolkit contracts."""

from __future__ import annotations

from pydantic import Field

from agent_foundry.models.base import FoundryModel, VersionedContract


class ToolkitResolution(FoundryModel):
    """Result of resolving capabilities for a context — metadata only."""

    resolved_capabilities: list[str] = Field(default_factory=list)
    resolved_skills: list[str] = Field(default_factory=list)
    resolved_workflows: list[str] = Field(default_factory=list)
    integration_ids: list[str] = Field(default_factory=list)


class ToolkitLock(VersionedContract):
    """Pinned operational capability set."""

    project_name: str
    capability_ids: list[str] = Field(default_factory=list)
    skill_ids: list[str] = Field(default_factory=list)
    workflow_ids: list[str] = Field(default_factory=list)
    integration_ids: list[str] = Field(default_factory=list)


class TaskToolkit(VersionedContract):
    """Minimum capability subset for one Work Item."""

    work_item_id: str
    capability_ids: list[str] = Field(default_factory=list)
    skill_ids: list[str] = Field(default_factory=list)
    workflow_id: str | None = None
    integration_ids: list[str] = Field(default_factory=list)
