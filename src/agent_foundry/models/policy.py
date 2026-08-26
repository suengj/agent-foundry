"""Authority, permission, and budget policy profiles."""

from __future__ import annotations

from pydantic import Field

from agent_foundry.models.base import FoundryModel
from agent_foundry.models.common import (
    AuthorityRequirement,
    ConsequenceClass,
    ExternalEffectClass,
)


class PermissionProfile(FoundryModel):
    """Scoped permission boundary for external writes."""

    id: str
    version: str = "1.0.0"
    external_effect: ExternalEffectClass
    write_requires: AuthorityRequirement
    preview_required: bool = True
    apply_requires: AuthorityRequirement = AuthorityRequirement.EXPLICIT_AUTHORITY


class BudgetProfile(FoundryModel):
    """Resource budget boundary."""

    id: str
    version: str = "1.0.0"
    max_parallel_runs: int | None = None
    max_retry_budget: int | None = None
    token_budget: int | None = None


class PolicyPredicate(FoundryModel):
    """Composable when-clause for declarative toolkit policy — no named project types."""

    consequence: ConsequenceClass | None = None
    external_effect: ExternalEffectClass | None = None
    authority_class: ExternalEffectClass | None = None
    assurance: str | None = None


class PolicyRule(FoundryModel):
    """Declarative policy rule applied during toolkit resolution."""

    id: str
    version: str = "1.0.0"
    description: str
    when: PolicyPredicate = Field(default_factory=PolicyPredicate)
    require_skills: list[str] = Field(default_factory=list)
    require_workflows: list[str] = Field(default_factory=list)
    require_roles: list[str] = Field(default_factory=list)
    require_capabilities: list[str] = Field(default_factory=list)
    forbid_skills: list[str] = Field(default_factory=list)
    forbid_workflows: list[str] = Field(default_factory=list)
    forbid_roles: list[str] = Field(default_factory=list)
    forbid_capabilities: list[str] = Field(default_factory=list)
    forbid_permission_profiles: list[str] = Field(default_factory=list)
