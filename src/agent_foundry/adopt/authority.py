"""Authority widening detection for adoption change sets."""

from __future__ import annotations

from agent_foundry.models.common import (
    AdoptionChangeStatus,
    AuthorityRequirement,
    Autonomy,
    ExternalEffectClass,
)
from agent_foundry.models.project import AdoptionChangeItem

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


def autonomy_rank(value: Autonomy | None) -> int | None:
    if value is None:
        return None
    return _AUTONOMY_ORDER.index(value)


def external_effect_rank(value: ExternalEffectClass | None) -> int | None:
    if value is None:
        return None
    return _EXTERNAL_EFFECT_ORDER.index(value)


def widens_autonomy(current: Autonomy | None, proposed: Autonomy | None) -> bool:
    current_rank = autonomy_rank(current)
    proposed_rank = autonomy_rank(proposed)
    if current_rank is None or proposed_rank is None:
        return False
    return proposed_rank > current_rank


def widens_external_effect(
    current: ExternalEffectClass | None,
    proposed: ExternalEffectClass | None,
) -> bool:
    current_rank = external_effect_rank(current)
    proposed_rank = external_effect_rank(proposed)
    if current_rank is None or proposed_rank is None:
        return False
    return proposed_rank > current_rank


def change_widens_authority(
    change: AdoptionChangeItem,
    *,
    current_autonomy: Autonomy | None,
    proposed_autonomy: Autonomy | None,
    current_external_effect: ExternalEffectClass | None,
    proposed_external_effect: ExternalEffectClass | None,
) -> bool:
    if change.target == "execution.autonomy" and widens_autonomy(current_autonomy, proposed_autonomy):
        return True
    if change.target == "impact.external-effect" and widens_external_effect(
        current_external_effect,
        proposed_external_effect,
    ):
        return True
    return False


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
        if change.authority_requirement == AuthorityRequirement.NONE:
            raise AssertionError(
                f"change {change.target!r} widens authority but authority_requirement is NONE"
            )
        if change.status == AdoptionChangeStatus.AUTO_APPLICABLE:
            raise AssertionError(
                f"change {change.target!r} widens authority but status is auto-applicable"
            )
