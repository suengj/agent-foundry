"""Authority, permission, and budget policy profiles."""

from __future__ import annotations

from agent_foundry.models.base import FoundryModel
from agent_foundry.models.common import AuthorityRequirement, ExternalEffectClass


class PermissionProfile(FoundryModel):
    """Scoped permission boundary for external writes."""

    id: str
    external_effect: ExternalEffectClass
    write_requires: AuthorityRequirement
    preview_required: bool = True
    apply_requires: AuthorityRequirement = AuthorityRequirement.EXPLICIT_AUTHORITY


class BudgetProfile(FoundryModel):
    """Resource budget boundary."""

    id: str
    max_parallel_runs: int | None = None
    max_retry_budget: int | None = None
    token_budget: int | None = None
