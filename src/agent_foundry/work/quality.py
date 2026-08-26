"""Decomposition quality checks."""

from __future__ import annotations

import re
from collections import defaultdict

from agent_foundry.models.work import (
    CapabilityUnit,
    DecompositionQualityFlag,
    DecompositionQualityIssue,
    WorkItemContract,
)
from agent_foundry.work.grouping import (
    partial_key_without_acceptance_boundary,
    partial_key_without_discovery_mutation,
    partial_key_without_outcome,
)

_FILE_STEP_PATTERN = re.compile(
    r"\b(?:schemas?|tests?|testing|reviews?|refactors?|refactoring|lint(?:ing)?)\b",
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


def _looks_step_shaped(unit: CapabilityUnit) -> bool:
    blob = f"{unit.id} {unit.title} {' '.join(unit.mechanical_steps)}"
    return bool(_FILE_STEP_PATTERN.search(blob))


def check_capability_units_pre_grouping(
    units: list[CapabilityUnit],
) -> list[DecompositionQualityIssue]:
    """Warn when supplied units would merge across outcome or discovery/mutation boundaries."""
    issues: list[DecompositionQualityIssue] = []

    by_partial_outcome: dict[tuple[str, ...], list[CapabilityUnit]] = defaultdict(list)
    by_partial_discovery: dict[tuple[str, ...], list[CapabilityUnit]] = defaultdict(list)

    for unit in sorted(units, key=lambda u: u.id):
        by_partial_outcome[partial_key_without_outcome(unit)].append(unit)
        by_partial_discovery[partial_key_without_discovery_mutation(unit)].append(unit)

    for group_units in by_partial_outcome.values():
        outcomes = {unit.outcome_id for unit in group_units}
        if len(outcomes) > 1:
            issues.append(
                DecompositionQualityIssue(
                    flag=DecompositionQualityFlag.CROSS_OUTCOME_IDENTITY_COLLISION,
                    work_item_id=None,
                    message=(
                        "capability units span multiple outcomes on identical causal "
                        "dimensions ("
                        + ", ".join(sorted(outcomes))
                        + "); outcome_id is what keeps them separate work items"
                    ),
                    related_ids=sorted(unit.id for unit in group_units),
                )
            )

    for group_units in by_partial_discovery.values():
        has_discovery = any(unit.discovery_only for unit in group_units)
        has_mutation = any(unit.mutates_external for unit in group_units)
        if has_discovery and has_mutation:
            issues.append(
                DecompositionQualityIssue(
                    flag=DecompositionQualityFlag.MIXED_DISCOVERY_AND_MUTATION,
                    work_item_id=None,
                    message="capability units mix discovery and irreversible mutation on identical causal dimensions",
                    related_ids=sorted(unit.id for unit in group_units),
                )
            )

    return _sorted_issues(issues)


def check_grouped_units(
    units: list[CapabilityUnit],
    unit_id_to_work_item: dict[str, str],
) -> list[DecompositionQualityIssue]:
    """Flag file-shaped splits at group level."""
    issues: list[DecompositionQualityIssue] = []

    by_partial_boundary: dict[tuple[str, ...], list[CapabilityUnit]] = defaultdict(list)
    for unit in sorted(units, key=lambda u: u.id):
        by_partial_boundary[partial_key_without_acceptance_boundary(unit)].append(unit)

    for group_units in by_partial_boundary.values():
        if len(group_units) < 2:
            continue
        work_item_ids = {unit_id_to_work_item[unit.id] for unit in group_units}
        step_shaped = [unit for unit in group_units if _looks_step_shaped(unit)]
        if len(work_item_ids) > 1 and len(step_shaped) >= 2:
            issues.append(
                DecompositionQualityIssue(
                    flag=DecompositionQualityFlag.FILE_SHAPED_DECOMPOSITION,
                    work_item_id=None,
                    message="mechanical step-shaped units split across work items",
                    related_ids=sorted(unit.id for unit in step_shaped),
                )
            )

    for unit in sorted(units, key=lambda u: u.id):
        step_role_hits = sum(
            1 for step in unit.mechanical_steps if _ROLE_STEP_PATTERN.search(step)
        )
        if step_role_hits >= 2:
            issues.append(
                DecompositionQualityIssue(
                    flag=DecompositionQualityFlag.ROLE_SHAPED_DECOMPOSITION,
                    work_item_id=unit_id_to_work_item[unit.id],
                    message=f"capability unit {unit.id} is shaped by agent roles",
                    related_ids=[unit.id],
                )
            )

    return _sorted_issues(issues)


def check_work_items(work_items: list[WorkItemContract]) -> list[DecompositionQualityIssue]:
    """Flag unverifiable acceptance criteria."""
    issues: list[DecompositionQualityIssue] = []

    for item in sorted(work_items, key=lambda wi: wi.id):
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

    return _sorted_issues(issues)


def work_class_merge_issue(
    units: list[CapabilityUnit],
    *,
    work_item_id: str,
    chosen: str,
) -> DecompositionQualityIssue | None:
    """Record when merged units carried different work-class labels.

    `related_ids` names the units that disagreed, matching every other flag and
    letting a reader open them. It previously held the class names, which are
    already in the message and point at nothing.
    """
    classes = sorted({unit.work_class.value for unit in units})
    if len(classes) <= 1:
        return None
    return DecompositionQualityIssue(
        flag=DecompositionQualityFlag.MIXED_WORK_CLASS,
        work_item_id=work_item_id,
        message=(
            f"merged units carried multiple work classes ({', '.join(classes)}); "
            f"chose {chosen}"
        ),
        related_ids=sorted(unit.id for unit in units),
    )
