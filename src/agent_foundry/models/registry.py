"""Role, capability, skill, and workflow registry metadata contracts."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from agent_foundry.models.base import FoundryModel, VersionedContract
from agent_foundry.models.common import ExternalEffectClass, PrimaryWorkMode, WorkClass
from agent_foundry.models.policy import PolicyRule


class CapabilitySpec(VersionedContract):
    """Logical capability metadata."""

    id: str
    version: str
    description: str
    tags: list[str] = Field(default_factory=list)
    provides: list[str] = Field(default_factory=list)
    min_external_effect: ExternalEffectClass = Field(
        default=ExternalEffectClass.PUBLICATION,
        description=(
            "Axis: the class of state this capability can change outside the repository "
            "working tree. Read-only access to an external system is read-only; the "
            "non-read-only classes name where a change lands."
        ),
    )
    """Lowest external-effect ceiling under which this capability may be exercised.

    The axis is *effect on state outside this repository working tree*, not
    "does it touch an external system" and not "how expensive is it". A
    capability that only reads — however remote or privileged the thing it reads —
    is ``read-only``; a capability is classified above ``read-only`` only when
    exercising it can change state somewhere, and the class names where that
    change lands (repository working tree, shared service, stored data, running
    runtime, published artifact).

    Reading a work tracker is therefore ``read-only`` and writing one is
    ``shared-service-write``, exactly as verifying a runtime is ``read-only``
    while mutating it is ``runtime-mutation``.

    Resolution treats this as a fail-closed floor: a capability whose spec is
    absent from the registry, or whose value is omitted, is treated as
    ``publication`` (the maximum) so that missing metadata tightens rather than
    widens. Declare the value explicitly.
    """


class SkillTriggers(FoundryModel):
    """Compact trigger metadata for skill discovery without loading full Skill text."""

    artifact_types: list[str] = Field(default_factory=list)
    work_modes: list[PrimaryWorkMode] = Field(default_factory=list)
    work_classes: list[WorkClass] = Field(default_factory=list)


class SkillPermissions(FoundryModel):
    external_write: bool = False


class SkillRoleConstraint(FoundryModel):
    allowed: list[str] = Field(default_factory=list)


class SkillSpec(VersionedContract):
    """Skill metadata for toolkit resolution."""

    id: str
    version: str
    description: str
    provides: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)
    triggers: SkillTriggers = Field(default_factory=SkillTriggers)
    roles: SkillRoleConstraint = Field(default_factory=SkillRoleConstraint)
    permissions: SkillPermissions = Field(default_factory=SkillPermissions)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)


class WorkflowSpec(VersionedContract):
    """Workflow graph metadata."""

    id: str
    version: str
    description: str
    node_ids: list[str] = Field(default_factory=list)
    required_roles: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)


class RoleContract(VersionedContract):
    """Logical role contract — provider-neutral."""

    id: str
    version: str
    description: str
    allowed_capabilities: list[str] = Field(default_factory=list)
    write_scope: list[str] = Field(default_factory=list)


class ToolConnectorKind(StrEnum):
    TOOL = "tool"
    CONNECTOR = "connector"


class ToolConnectorSpec(VersionedContract):
    """Tool or connector metadata — no live SDK binding."""

    id: str
    version: str
    description: str
    kind: ToolConnectorKind
    capabilities: list[str] = Field(default_factory=list)
    transport: str | None = None


class ValidatorSpec(VersionedContract):
    """Validator metadata for evidence and contract checks."""

    id: str
    version: str
    description: str
    validates: list[str] = Field(default_factory=list)


class PermissionProfileRef(FoundryModel):
    """Registry reference to a permission profile id."""

    id: str
    version: str


class BudgetProfileRef(FoundryModel):
    """Registry reference to a budget profile id."""

    id: str
    version: str


class IntegrationRegistryEntry(FoundryModel):
    """Integration id pinned in the registry — declaration lives in integrations config."""

    id: str
    adapter_version: str


class CapabilityRegistry(VersionedContract):
    """Inspectable global capability catalog — small and version-pinned."""

    foundry_compat: str
    capabilities: list[CapabilitySpec] = Field(default_factory=list)
    skills: list[SkillSpec] = Field(default_factory=list)
    workflows: list[WorkflowSpec] = Field(default_factory=list)
    roles: list[RoleContract] = Field(default_factory=list)
    tools: list[ToolConnectorSpec] = Field(default_factory=list)
    connectors: list[ToolConnectorSpec] = Field(default_factory=list)
    validators: list[ValidatorSpec] = Field(default_factory=list)
    permission_profiles: list[PermissionProfileRef] = Field(default_factory=list)
    budget_profiles: list[BudgetProfileRef] = Field(default_factory=list)
    integrations: list[IntegrationRegistryEntry] = Field(default_factory=list)
    policy_rules: list[PolicyRule] = Field(default_factory=list)
