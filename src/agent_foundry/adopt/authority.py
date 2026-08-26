"""Authority widening detection for adoption change sets.

Two properties this module is required to hold:

1. **Structural recognition.** An authority-bearing target is recognised by the
   manifest field it moves, not by an incidental spelling used at one call site.
   `impact.external-effect` and `impact.external_effect` name the same field.
2. **Fail closed.** A target this module has not classified is treated as
   authority-widening. Adding a new `_change(...)` call site therefore forces a
   deliberate classification decision instead of silently escaping the guard.
"""

from __future__ import annotations

from enum import StrEnum

from agent_foundry.models.common import (
    AdoptionChangeStatus,
    AuthorityRequirement,
    Autonomy,
    ExternalEffectClass,
)
from agent_foundry.models.project import AdoptionChangeItem


class AuthorityAxis(StrEnum):
    """Manifest field whose value defines part of the project authority envelope."""

    AUTONOMY = "execution.autonomy"
    EXTERNAL_EFFECT = "impact.external_effect"


_AUTONOMY_ORDER: tuple[Autonomy, ...] = (
    Autonomy.SUGGEST,
    Autonomy.PREPARE,
    Autonomy.ISOLATED_EXECUTE,
    Autonomy.BOUNDED_EXTERNAL_WRITE,
    Autonomy.APPROVED_APPLY,
    Autonomy.CONTINUOUS_OPERATION,
)

_EXTERNAL_EFFECT_ORDER: tuple[ExternalEffectClass, ...] = (
    ExternalEffectClass.READ_ONLY,
    ExternalEffectClass.REPOSITORY_WRITE,
    ExternalEffectClass.SHARED_SERVICE_WRITE,
    ExternalEffectClass.DATA_MUTATION,
    ExternalEffectClass.RUNTIME_MUTATION,
    ExternalEffectClass.PUBLICATION,
)

UNKNOWN_AUTHORITY_RANK: int = -1
"""Rank of an undeclared current authority level.

AF2 leaves manifest fields unknown by design, so `None` is the ordinary case, not
an exceptional one. Ranking unknown below every declared level means an unknown
baseline can never make a proposal look non-widening.
"""


def _target_key(target: str) -> str:
    """Normalize a change target to the manifest field it names."""
    return target.strip().lower().replace("-", "_")


_AUTHORITY_AXIS_BY_TARGET: dict[str, AuthorityAxis] = {
    _target_key(axis.value): axis for axis in AuthorityAxis
}

NON_AUTHORITY_TARGETS: frozenset[str] = frozenset(
    {
        "agent-instruction-surface",
        "agent-instruction-surfaces",
        "foundry-artifact-surfaces",
        "foundry-project-declaration",
        "instruction-surface-mentions",
        "intake-mode",
        # Wrapping changes how an existing surface is reached, not what the project may
        # do: the autonomy level and external-effect class are untouched. It still
        # carries `explicit-authority` as a change, because deciding that agent access
        # runs through an adapter is an owner's call.
        "integration-surfaces",
        "package-metadata",
        "runtime-deploy",
        "test-harness",
    }
)
"""Adoption targets reviewed and found not to move the authority envelope.

Membership here is a claim that applying the change cannot raise the project's
autonomy or external-effect class. It is not a claim that the change is free of
side effects: a repository-writing target still carries its own
`authority_requirement`.
"""

NON_AUTHORITY_TARGET_PREFIXES: tuple[str, ...] = ("readiness:",)
"""Reviewed target families whose members are generated from a finding dimension."""

_NON_AUTHORITY_TARGET_KEYS: frozenset[str] = frozenset(
    _target_key(target) for target in NON_AUTHORITY_TARGETS
)
_NON_AUTHORITY_PREFIX_KEYS: tuple[str, ...] = tuple(
    _target_key(prefix) for prefix in NON_AUTHORITY_TARGET_PREFIXES
)


def authority_axis_for_target(target: str) -> AuthorityAxis | None:
    """Return the authority axis a target moves, or None when it moves none."""
    return _AUTHORITY_AXIS_BY_TARGET.get(_target_key(target))


def is_reviewed_non_authority_target(target: str) -> bool:
    """True when the target has been explicitly classified as authority-neutral."""
    key = _target_key(target)
    if key in _NON_AUTHORITY_TARGET_KEYS:
        return True
    return any(key.startswith(prefix) for prefix in _NON_AUTHORITY_PREFIX_KEYS)


def is_classified_target(target: str) -> bool:
    """True when the guard recognises the target at all."""
    return authority_axis_for_target(target) is not None or is_reviewed_non_authority_target(target)


def autonomy_rank(value: Autonomy | None) -> int | None:
    """Ordinal position of a declared autonomy level, or None when undeclared."""
    if value is None:
        return None
    return _AUTONOMY_ORDER.index(value)


def external_effect_rank(value: ExternalEffectClass | None) -> int | None:
    """Ordinal position of a declared external-effect class, or None when undeclared."""
    if value is None:
        return None
    return _EXTERNAL_EFFECT_ORDER.index(value)


def _current_rank(rank: int | None) -> int:
    return UNKNOWN_AUTHORITY_RANK if rank is None else rank


def widens_autonomy(current: Autonomy | None, proposed: Autonomy | None) -> bool:
    """True when moving from `current` to `proposed` raises autonomy.

    An unknown `current` ranks lowest, so any concrete proposal widens it.
    A `proposed` of None means the change proposes no autonomy move at all.
    """
    proposed_rank = autonomy_rank(proposed)
    if proposed_rank is None:
        return False
    return _current_rank(autonomy_rank(current)) < proposed_rank


def widens_external_effect(
    current: ExternalEffectClass | None,
    proposed: ExternalEffectClass | None,
) -> bool:
    """True when moving from `current` to `proposed` raises the external-effect class."""
    proposed_rank = external_effect_rank(proposed)
    if proposed_rank is None:
        return False
    return _current_rank(external_effect_rank(current)) < proposed_rank


def change_widens_authority(
    change: AdoptionChangeItem,
    *,
    current_autonomy: Autonomy | None,
    proposed_autonomy: Autonomy | None,
    current_external_effect: ExternalEffectClass | None,
    proposed_external_effect: ExternalEffectClass | None,
) -> bool:
    """True when the change may move the authority envelope outward.

    Unclassified targets return True. The guard cannot prove an unreviewed target
    is safe, so it refuses to assume it.
    """
    axis = authority_axis_for_target(change.target)
    if axis is AuthorityAxis.AUTONOMY:
        return widens_autonomy(current_autonomy, proposed_autonomy)
    if axis is AuthorityAxis.EXTERNAL_EFFECT:
        return widens_external_effect(current_external_effect, proposed_external_effect)
    return not is_reviewed_non_authority_target(change.target)


def _widening_reason(change: AdoptionChangeItem) -> str:
    axis = authority_axis_for_target(change.target)
    if axis is not None:
        return f"widens authority on axis {axis.value}"
    return (
        "widens authority: target is not a reviewed adoption target, so the guard "
        "fails closed rather than assume it is authority-neutral"
    )


def assert_change_set_respects_authority(
    changes: list[AdoptionChangeItem],
    *,
    current_autonomy: Autonomy | None,
    proposed_autonomy: Autonomy | None,
    current_external_effect: ExternalEffectClass | None,
    proposed_external_effect: ExternalEffectClass | None,
) -> None:
    """Raise AssertionError when a change would widen authority without explicit approval."""
    for change in changes:
        if not change_widens_authority(
            change,
            current_autonomy=current_autonomy,
            proposed_autonomy=proposed_autonomy,
            current_external_effect=current_external_effect,
            proposed_external_effect=proposed_external_effect,
        ):
            continue
        reason = _widening_reason(change)
        if change.authority_requirement == AuthorityRequirement.NONE:
            raise AssertionError(
                f"change {change.target!r} {reason} but authority_requirement is NONE"
            )
        if change.status == AdoptionChangeStatus.AUTO_APPLICABLE:
            raise AssertionError(
                f"change {change.target!r} {reason} but status is auto-applicable"
            )
