"""Work decomposition and graph validation errors."""

from __future__ import annotations

from agent_foundry.models.base import FoundryModelError


class WorkDecompositionError(FoundryModelError):
    """Base error for work decomposition failures."""


class DependencyGraphError(WorkDecompositionError):
    """Raised when the work-item dependency graph is invalid."""

    def __init__(self, message: str, *, node_ids: list[str] | None = None) -> None:
        self.node_ids = sorted(node_ids or [])
        detail = message
        if self.node_ids:
            detail = f"{message}: {', '.join(self.node_ids)}"
        super().__init__(detail)
