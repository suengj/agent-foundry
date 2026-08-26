"""Decomposition quality checks."""

from __future__ import annotations

import re

from agent_foundry.models.work import (
    CapabilityUnit,
    DecompositionQualityFlag,
    DecompositionQualityIssue,
    WorkItemContract,
)

_FILE_STEP_PATTERN = re.compile(
    r"\b(schema|test|review|refactor|lint)\b",
    re.IGNORECASE,
)
_ROLE_STEP_PATTERN = re.compile(
    r"\b(builder|reviewer|manager|implementer|tester)\b",
    re.IGNORECASE,
)
_UNVERIFIABLE_PATTERN = re.compile(
    r"\b(tbd|todo|as needed|somehow|maybe)\b",
    re.IGNORECASE,
)


def _sorted_issues(issues: list[DecompositionQualityIssue]) -> list[DecompositionQualityIssue]:
    return sorted(
        issues,
        key=lambda issue: (
            issue.flag.value,
            issue.work_item_id or "",
            issue.message,
        ),
    )


def check_capability_units(units: list[CapabilityUnit]) -> list[DecompositionQualityIssue]:
    """Flag file-shaped or role-shaped decomposition at the unit level."""
    issues: list[DecompositionQualityIssue] = []
    for unit in sorted(units, key=lambda u: u.id):
        steps = sorted(unit.mechanical_steps)
        if len(steps) >= 2:
            file_hits = sum(1 for step in steps if _FILE_STEP_PATTERN.search(step))
            if file_hits >= 2 and len({unit.acceptance_boundary_id}) == 1:
                issues.append(
                    DecompositionQualityIssue(
                        flag=DecompositionQualityFlag.FILE_SHAPED_DECOMPOSITION,
                        work_item_id=None,
                        message=(
                            f"capability unit {unit.id} splits mechanical steps "
                            "that share one acceptance boundary"
                        ),
                        related_ids=[unit.id],
                    )
                )
            role_hits = sum(1 for step in steps if _ROLE_STEP_PATTERN.search(step))
            if role_hits >= 2:
                issues.append(
                    DecompositionQualityIssue(
                        flag=DecompositionQualityFlag.ROLE_SHAPED_DECOMPOSITION,
                        work_item_id=None,
                        message=f"capability unit {unit.id} is shaped by agent roles",
                        related_ids=[unit.id],
                    )
                )
        if unit.discovery_only and unit.mutates_external:
            issues.append(
                DecompositionQualityIssue(
                    flag=DecompositionQualityFlag.MIXED_DISCOVERY_AND_MUTATION,
                    work_item_id=None,
                    message=f"capability unit {unit.id} mixes discovery and mutation",
                    related_ids=[unit.id],
                )
            )
    return _sorted_issues(issues)


def check_work_items(work_items: list[WorkItemContract]) -> list[DecompositionQualityIssue]:
    """Flag mega-items, unverifiable acceptance, and write-scope collisions."""
    issues: list[DecompositionQualityIssue] = []
    scope_map: dict[str, list[str]] = {}

    for item in sorted(work_items, key=lambda wi: wi.id):
        objective_markers = sorted(
            {
                marker
                for criterion in item.acceptance_criteria
                for marker in criterion.split(":")
                if marker.startswith("objective-")
            }
        )
        if len(objective_markers) > 1:
            issues.append(
                DecompositionQualityIssue(
                    flag=DecompositionQualityFlag.MEGA_ITEM,
                    work_item_id=item.id,
                    message="work item carries multiple independent objectives",
                    related_ids=objective_markers,
                )
            )

        for criterion in sorted(item.acceptance_criteria):
            if _UNVERIFIABLE_PATTERN.search(criterion):
                issues.append(
                    DecompositionQualityIssue(
                        flag=DecompositionQualityFlag.UNVERIFIABLE_ACCEPTANCE,
                        work_item_id=item.id,
                        message="acceptance criterion is not objectively verifiable",
                        related_ids=[criterion],
                    )
                )

        if item.write_scope_id:
            scope_map.setdefault(item.write_scope_id, []).append(item.id)

    for scope_id in sorted(scope_map):
        owners = sorted(scope_map[scope_id])
        if len(owners) > 1:
            issues.append(
                DecompositionQualityIssue(
                    flag=DecompositionQualityFlag.WRITE_SCOPE_COLLISION,
                    work_item_id=None,
                    message=f"multiple work items share write scope {scope_id}",
                    related_ids=owners,
                )
            )

    return _sorted_issues(issues)
