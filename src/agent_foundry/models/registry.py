"""Role, capability, skill, and workflow registry metadata contracts."""

from __future__ import annotations

from pydantic import Field

from agent_foundry.models.base import FoundryModel, VersionedContract


class CapabilitySpec(VersionedContract):
    """Logical capability metadata."""

    id: str
    version: str
    description: str
    tags: list[str] = Field(default_factory=list)


class SkillSpec(VersionedContract):
    """Skill metadata for toolkit resolution."""

    id: str
    version: str
    description: str
    required_capabilities: list[str] = Field(default_factory=list)


class WorkflowSpec(VersionedContract):
    """Workflow graph metadata."""

    id: str
    version: str
    description: str
    node_ids: list[str] = Field(default_factory=list)


class RoleContract(VersionedContract):
    """Logical role contract — provider-neutral."""

    id: str
    version: str
    description: str
    allowed_capabilities: list[str] = Field(default_factory=list)
    write_scope: list[str] = Field(default_factory=list)
