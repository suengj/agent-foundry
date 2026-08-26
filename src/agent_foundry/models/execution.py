"""Execution bundle — compiled agent run contract."""

from __future__ import annotations

from pydantic import Field

from agent_foundry.models.base import VersionedContract


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
