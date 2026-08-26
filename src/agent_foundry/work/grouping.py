"""Causal grouping keys and deterministic Work Item identity."""

from __future__ import annotations

import hashlib
import json

from agent_foundry.models.work import CapabilityUnit

GroupKey = tuple[str, ...]


def capability_group_key(unit: CapabilityUnit) -> GroupKey:
    """Full causal identity for decomposition grouping."""
    return (
        unit.outcome_id,
        unit.acceptance_boundary_id,
        unit.authority_class.value,
        unit.consequence_class.value,
        unit.work_class.value,
        unit.rollback_boundary_id,
        unit.write_scope_id,
        "discovery" if unit.discovery_only else "implementation",
        "mutates-external" if unit.mutates_external else "no-external-mutation",
    )


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
