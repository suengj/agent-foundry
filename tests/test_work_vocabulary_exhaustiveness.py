"""Regression guard: work-model lookup tables must cover their whole enum.

Same drift class as `tests/test_docs_vocabulary_consistency.py`, one layer in.
Decomposition maps enum members to behaviour through dict lookups. A member
added to `WorkClass` or `ExternalEffectClass` without extending the matching
table does not fail at import, or in most of the suite; it fails as a bare
`KeyError` from inside decomposition the first time an input happens to reach
the lookup. These tests name the missing member instead.
"""

from __future__ import annotations

import pytest

from agent_foundry.models.common import ExternalEffectClass, WorkClass
from agent_foundry.work.decompose import (
    external_validation_requirement,
    unmapped_external_effect_classes,
)
from agent_foundry.work.grouping import unranked_work_classes


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


def test_precedence_and_validation_tables_are_keyed_by_the_real_enums() -> None:
    """Guards would silently pass if the tables drifted onto stringly keys."""
    from agent_foundry.work.decompose import _EXTERNAL_VALIDATION_BY_AUTHORITY
    from agent_foundry.work.grouping import _WORK_CLASS_RANK

    assert all(isinstance(key, WorkClass) for key in _WORK_CLASS_RANK)
    assert all(
        isinstance(key, ExternalEffectClass) for key in _EXTERNAL_VALIDATION_BY_AUTHORITY
    )
