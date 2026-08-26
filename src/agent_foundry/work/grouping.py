"""Causal grouping keys and deterministic Work Item identity."""

from __future__ import annotations

import hashlib
import json

from agent_foundry.models.base import WorkDecompositionError
from agent_foundry.models.common import WorkClass
from agent_foundry.models.work import CapabilityUnit

GroupKey = tuple[str, ...]

# Most specific work-class label wins when causal dimensions merge unlike units.
_WORK_CLASS_PRECEDENCE: tuple[WorkClass, ...] = (
    WorkClass.CONTRACT_AMENDMENT,
    WorkClass.INCIDENT,
    WorkClass.DISCOVERY,
    WorkClass.ADOPTION,
    WorkClass.CAPABILITY,
    WorkClass.RESIDUAL_HARDENING,
    WorkClass.BASELINE,
)
_WORK_CLASS_RANK = {work_class: index for index, work_class in enumerate(_WORK_CLASS_PRECEDENCE)}


def unranked_work_classes() -> list[str]:
    """WorkClass members `_WORK_CLASS_PRECEDENCE` does not rank, sorted by value.

    Adding a member to `WorkClass` without extending the precedence tuple is a
    silent drift: nothing fails until two unlike units happen to merge, and the
    only failure is a bare `KeyError` from the rank lookup. `tests/
    test_work_vocabulary_exhaustiveness.py` fails on this list instead.
    """
    return sorted(
        work_class.value for work_class in WorkClass if work_class not in _WORK_CLASS_RANK
    )


def capability_group_key(unit: CapabilityUnit) -> GroupKey:
    """Full causal identity for decomposition grouping."""
    return (
        unit.outcome_id,
        unit.acceptance_boundary_id,
        unit.authority_class.value,
        unit.consequence_class.value,
        unit.rollback_boundary_id,
        unit.write_scope_id,
        "discovery" if unit.discovery_only else "implementation",
        "mutates-external" if unit.mutates_external else "no-external-mutation",
    )


def resolve_merged_work_class(units: list[CapabilityUnit]) -> WorkClass:
    """Choose a single work-class label for merged units."""
    classes = {unit.work_class for unit in units}
    if len(classes) == 1:
        return next(iter(classes))
    unranked = sorted(
        work_class.value for work_class in classes if work_class not in _WORK_CLASS_RANK
    )
    if unranked:
        raise WorkDecompositionError(
            "work class precedence is not exhaustive: "
            f"{', '.join(unranked)} not ranked by _WORK_CLASS_PRECEDENCE in "
            "agent_foundry.work.grouping; add each member in explicit precedence order"
        )
    # Ranks are unique per member, so no value tiebreak can ever be reached.
    return min(classes, key=lambda work_class: _WORK_CLASS_RANK[work_class])


def work_item_id_for_group_key(group_key: GroupKey) -> str:
    """Stable, order-independent Work Item id from the full group key."""
    payload = json.dumps(group_key, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"wi-{digest}"


def partial_key_without_acceptance_boundary(unit: CapabilityUnit) -> GroupKey:
    key = capability_group_key(unit)
    return (key[0],) + key[2:]


def partial_key_without_outcome(unit: CapabilityUnit) -> GroupKey:
    return capability_group_key(unit)[1:]


def partial_key_without_discovery_mutation(unit: CapabilityUnit) -> GroupKey:
    return capability_group_key(unit)[:-2]
