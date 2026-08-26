"""Dependency graph validation for work items."""

from __future__ import annotations

from collections import defaultdict

from agent_foundry.models.common import DependencyRelation
from agent_foundry.models.work import WorkItemContract
from agent_foundry.models.base import DependencyGraphError

_EDGE_RELATIONS = frozenset(
    {
        DependencyRelation.REQUIRES,
        DependencyRelation.APPLIES_AFTER,
        DependencyRelation.DISCOVERED_BY,
        DependencyRelation.VALIDATES,
    }
)


def _successors(item: WorkItemContract) -> list[str]:
    targets: list[str] = []
    for dep in item.dependencies:
        if dep.relation in _EDGE_RELATIONS:
            targets.append(dep.target_id)
        elif dep.relation == DependencyRelation.BLOCKS:
            targets.append(dep.target_id)
    return sorted(targets)


def validate_dependency_graph(work_items: list[WorkItemContract]) -> None:
    """Reject cycles and dangling dependency references."""
    by_id = {item.id: item for item in work_items}
    known_ids = set(by_id)

    dangling: list[str] = []
    for item in sorted(work_items, key=lambda wi: wi.id):
        for dep in sorted(item.dependencies, key=lambda d: (d.relation.value, d.target_id)):
            if dep.target_id not in known_ids:
                dangling.append(f"{item.id}->{dep.target_id}")

    if dangling:
        nodes = sorted({part for edge in dangling for part in edge.split("->")})
        raise DependencyGraphError(
            "dangling dependency reference",
            node_ids=nodes,
        )

    graph: dict[str, list[str]] = defaultdict(list)
    for item_id in sorted(known_ids):
        graph[item_id] = _successors(by_id[item_id])

    visited: set[str] = set()
    stack: set[str] = set()
    cycle_nodes: list[str] = []

    def visit(node: str, path: list[str]) -> None:
        if node in stack:
            start = path.index(node)
            cycle_nodes.extend(path[start:] + [node])
            return
        if node in visited:
            return
        visited.add(node)
        stack.add(node)
        for neighbor in graph[node]:
            visit(neighbor, path + [node])
        stack.remove(node)

    for node in sorted(known_ids):
        visit(node, [])

    if cycle_nodes:
        unique_cycle = sorted(set(cycle_nodes))
        raise DependencyGraphError("circular dependency", node_ids=unique_cycle)
