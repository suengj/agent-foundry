"""Regression guard: work-model lookup tables must match their enum exactly.

Same drift class as `tests/test_docs_vocabulary_consistency.py`, one layer in.
Decomposition maps enum members to behaviour through hand-maintained tables. A
member added to `WorkClass` or `ExternalEffectClass` without extending the
matching table does not fail at import, or in most of the suite; it fails as a
bare `KeyError` from inside decomposition the first time an input happens to
reach the lookup. These tests name the offending member instead.

"Exhaustive" here means reciprocal, not one-way. A table can drift three ways
and each has its own named test, because a set difference in one direction is
blind to the other two:

- a member the table does not rank        -> the merge raises
- an entry that is not a member at all    -> ranks nothing, shifts every entry
                                             after it, and can mask the real
                                             member it was meant to be
- a member listed twice                   -> silently demoted to its lowest
                                             listed position

The middle and last cases leave the first test passing, so completeness in one
direction is not evidence of a correct table.
"""

from __future__ import annotations

import pytest

from agent_foundry.models.common import ExternalEffectClass, WorkClass
from agent_foundry.work.decompose import (
    external_validation_requirement,
    unmapped_external_effect_classes,
)
from agent_foundry.work.grouping import (
    _WORK_CLASS_PRECEDENCE,
    duplicated_precedence_entries,
    precedence_rank_is_lossless,
    unknown_precedence_entries,
    unranked_work_classes,
)


def test_work_class_precedence_ranks_every_work_class() -> None:
    unranked = unranked_work_classes()
    if unranked:
        pytest.fail(
            "WorkClass member(s) not ranked by _WORK_CLASS_PRECEDENCE in "
            f"agent_foundry.work.grouping: {unranked}. Merging unlike capability "
            "units into one work item ranks work classes to pick the label; an "
            "unranked member makes that merge fail. Add each member to the "
            "precedence tuple in explicit most-specific-first order."
        )


def test_work_class_precedence_holds_no_entry_that_is_not_a_work_class() -> None:
    """The reverse direction. `WorkClass - table` cannot see `table - WorkClass`."""
    unknown = unknown_precedence_entries()
    if unknown:
        pytest.fail(
            "_WORK_CLASS_PRECEDENCE entry/entries that are not WorkClass members "
            f"(agent_foundry.work.grouping): {unknown}. A renamed, removed, or "
            "mistyped member leaves an entry that ranks nothing, shifts the rank "
            "of every member after it, and goes on masking the member it was "
            "meant to be. Remove it, or replace it with the real member."
        )


def test_work_class_precedence_lists_no_member_twice() -> None:
    """Caught by neither completeness direction: the member is present, and real."""
    duplicated = duplicated_precedence_entries()
    if duplicated:
        pytest.fail(
            "WorkClass member(s) listed more than once in _WORK_CLASS_PRECEDENCE "
            f"(agent_foundry.work.grouping): {duplicated}. Only the last position "
            "survives into _WORK_CLASS_RANK, so a duplicate silently demotes the "
            "member and changes which label a merged Work Item carries. List each "
            "member exactly once."
        )


def test_every_work_class_precedence_entry_survives_into_the_rank_table() -> None:
    """One assertion over both ways the tuple can lose an entry building the dict.

    `enumerate` lets a repeated member overwrite its own rank, and because
    `WorkClass` is a `StrEnum` a bare string entry can collide with a real
    member's key. Either way the dict ends up shorter than the tuple.
    """
    assert precedence_rank_is_lossless(), (
        f"_WORK_CLASS_PRECEDENCE has {len(_WORK_CLASS_PRECEDENCE)} entries but "
        "_WORK_CLASS_RANK ranks fewer: an entry was lost to a duplicate or to a "
        "key collision. Every entry must be a distinct WorkClass member."
    )


def test_every_external_effect_class_has_a_validation_requirement() -> None:
    unmapped = unmapped_external_effect_classes()
    if unmapped:
        pytest.fail(
            "ExternalEffectClass member(s) with no external-validation clause in "
            f"_EXTERNAL_VALIDATION_BY_AUTHORITY (agent_foundry.work.decompose): "
            f"{unmapped}. Every work item states how its external effect is "
            "validated; add a clause, or map the member to None if it touches "
            "nothing outside the run."
        )


@pytest.mark.parametrize("authority_class", sorted(ExternalEffectClass, key=lambda e: e.value))
def test_external_validation_requirement_resolves_for_every_authority_class(
    authority_class: ExternalEffectClass,
) -> None:
    """No member reaches the caller as an unhandled lookup failure."""
    requirement = external_validation_requirement(authority_class, ["validation output"])
    assert requirement is None or requirement.strip()


def test_validation_table_holds_no_key_that_is_not_an_external_effect_class() -> None:
    """The reverse direction for the authority table, as above for precedence."""
    from agent_foundry.work.decompose import _EXTERNAL_VALIDATION_BY_AUTHORITY

    unknown = sorted(
        repr(key)
        for key in _EXTERNAL_VALIDATION_BY_AUTHORITY
        if not isinstance(key, ExternalEffectClass)
    )
    if unknown:
        pytest.fail(
            "_EXTERNAL_VALIDATION_BY_AUTHORITY key(s) that are not "
            f"ExternalEffectClass members (agent_foundry.work.decompose): {unknown}. "
            "A stale key maps nothing and leaves the member it was meant to cover "
            "looking mapped to the forward check."
        )
