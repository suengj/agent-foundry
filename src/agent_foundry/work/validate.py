"""Dependency graph validation for work items."""

from __future__ import annotations

from collections import defaultdict, deque

from agent_foundry.models.base import DependencyGraphError
from agent_foundry.models.common import DependencyRelation
from agent_foundry.models.work import WorkItemContract

_FORWARD_RELATIONS = frozenset(
    {
        DependencyRelation.REQUIRES,
        DependencyRelation.APPLIES_AFTER,
        DependencyRelation.DISCOVERED_BY,
        DependencyRelation.VALIDATES,
        DependencyRelation.SUPERSEDES,
    }
)


def _build_dependency_graph(
    work_items: list[WorkItemContract],
) -> tuple[dict[str, list[str]], set[str]]:
    """Return adjacency list (item -> prerequisites) and known ids."""
    known_ids = {item.id for item in work_items}
    graph: dict[str, list[str]] = defaultdict(list)

    for item in sorted(work_items, key=lambda wi: wi.id):
        for dep in sorted(item.dependencies, key=lambda d: (d.relation.value, d.target_id)):
            if dep.relation in _FORWARD_RELATIONS:
                graph[item.id].append(dep.target_id)
            elif dep.relation == DependencyRelation.BLOCKS:
                graph[dep.target_id].append(item.id)

    for item_id in sorted(known_ids):
        graph[item_id] = sorted(set(graph[item_id]))
    return graph, known_ids


def validate_dependency_graph(work_items: list[WorkItemContract]) -> None:
    """Reject cycles and dangling dependency references."""
    by_id = {item.id: item for item in work_items}
    if len(by_id) != len(work_items):
        duplicate_ids = sorted(
            item_id
            for item_id in {item.id for item in work_items}
            if sum(1 for item in work_items if item.id == item_id) > 1
        )
        raise DependencyGraphError(
            "duplicate work item id",
            node_ids=duplicate_ids,
        )

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

    graph, known_ids = _build_dependency_graph(work_items)

    indegree: dict[str, int] = {node: len(graph[node]) for node in sorted(known_ids)}
    dependents: dict[str, list[str]] = defaultdict(list)
    for node in sorted(known_ids):
        for prerequisite in graph[node]:
            dependents[prerequisite].append(node)

    queue: deque[str] = deque(node for node in sorted(known_ids) if indegree[node] == 0)
    visited = 0
    while queue:
        node = queue.popleft()
        visited += 1
        for dependent in sorted(dependents[node]):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                queue.append(dependent)

    if visited != len(known_ids):
        cycle_path = _find_cycle_path(graph, known_ids)
        raise DependencyGraphError(
            "circular dependency",
            node_ids=cycle_path,
            cycle_path=cycle_path,
        )


def _find_cycle_path(graph: dict[str, list[str]], known_ids: set[str]) -> list[str]:
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []
    cycle: list[str] = []

    def dfs(node: str) -> bool:
        if node in visiting:
            start = stack.index(node)
            cycle.extend(stack[start:] + [node])
            return True
        if node in visited:
            return False
        visiting.add(node)
        stack.append(node)
        for neighbor in graph[node]:
            if dfs(neighbor):
                return True
        stack.pop()
        visiting.remove(node)
        visited.add(node)
        return False

    for node in sorted(known_ids):
        if node not in visited and dfs(node):
            return cycle
    return sorted(known_ids)
