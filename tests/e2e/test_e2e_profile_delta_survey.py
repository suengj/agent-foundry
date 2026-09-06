"""ProjectProfile before/after comparison, and the proof that it stays public-safe.

`tests/e2e/friction_survey.py` measures inspection/adoption friction and has no notion
of a code version. This module adds the ProjectProfile survey and the before/after
comparison mechanism `tests/e2e/profile_delta_survey.py` implements, checked the same
way the friction survey is: the record type's *shape* rules out a private value, and
the aggregate/comparison output is checked directly against every fixture's own
identifying strings rather than merely trusted to have kept them out.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from tests.e2e import support
from tests.e2e.profile_delta_survey import (
    ProfileSurvey,
    aggregate_profile,
    compare,
    survey_profiles,
    survey_repository_profile,
)

# Every fixture project committed to this repository, enumerated from disk rather than
# listed by hand — a fixture added tomorrow (by another agent, elsewhere) is profiled
# the day it is added, and "every committed fixture" cannot quietly narrow.
FIXTURE_TARGETS = sorted(path for path in support.FIXTURES.iterdir() if path.is_dir())


def test_no_survey_field_can_hold_a_path_a_name_or_content() -> None:
    """Privacy is a property of the type, not of how carefully it is used.

    Every field is an `int` or a `bool`, except the three dimension-name fields, which
    hold `tuple[str, ...]`. A dimension *name* is a string literal fixed in
    `agent_foundry.profile.synth`'s source (see that module and the docstring here) —
    it is never built from a target's content — but a dimension *value* (the actual
    attributed string) is never read by this dataclass at all: there is no field for
    it. A leak would have to be a new field added to this dataclass, not a slip in
    using an existing one.
    """
    numeric = {"int", "bool"}
    vocabulary_fields = {
        "resolved_dimension_names",
        "conflicted_dimension_names",
        "unknown_dimension_names",
    }
    for item in dataclasses.fields(ProfileSurvey):
        annotation = str(item.type)
        if item.name in vocabulary_fields:
            assert annotation == "tuple[str, ...]"
            continue
        assert annotation in numeric, (
            f"{item.name} is typed {annotation!r}; a survey field that is not a "
            "number is a field a private value can reach"
        )


def test_no_dimension_value_field_exists_at_all() -> None:
    """`ProfileDimension.attributions[*].value` has no counterpart field here.

    This is the concrete version of the structural claim above: the dataclass has no
    field named or shaped like a place a repository-content string would land.
    """
    field_names = {item.name for item in dataclasses.fields(ProfileSurvey)}
    for forbidden in ("value", "values", "attribution", "attributions", "content", "path", "name"):
        assert forbidden not in field_names


def test_dimension_names_never_contain_a_fixtures_own_identifying_text() -> None:
    """The concrete privacy proof: run every fixture, and check its own name never
    reappears in what was recorded about it.

    Unlike the friction survey's convention subjects (drawn from an enum), profile
    dimension names are open-ended strings by contract (`ProfileDimension.dimension`
    is documented as free-form). The guarantee here is not "belongs to a small enum";
    it is "cannot vary with repository content" — and the only way to check that
    directly is to look for the fixture's own name in the output and find it absent,
    for every fixture on disk.
    """
    for target in FIXTURE_TARGETS:
        record = survey_repository_profile(target)
        recorded_names = (
            record.resolved_dimension_names
            + record.conflicted_dimension_names
            + record.unknown_dimension_names
        )
        for name in recorded_names:
            assert target.name not in name
            assert str(target) not in name


def test_the_aggregate_output_is_json_and_contains_no_target_text() -> None:
    result = survey_profiles(FIXTURE_TARGETS)
    assert result.failed == 0
    payload = json.dumps(aggregate_profile(result), sort_keys=True)

    for target in FIXTURE_TARGETS:
        assert target.name not in payload
        assert str(target) not in payload
    for marker in ("/Users/", "/home/", str(support.REPO_ROOT)):
        assert marker not in payload


def test_the_survey_reports_a_failure_without_quoting_it(tmp_path: Path) -> None:
    missing = tmp_path / "not-a-directory-with-a-revealing-name"
    result = survey_profiles([missing])
    assert result.surveys == []
    assert result.failed == 1
    assert result.failure_types == ("FileNotFoundError",)
    assert missing.name not in json.dumps(aggregate_profile(result))


def test_the_fixture_list_is_every_fixture_project_on_disk() -> None:
    assert FIXTURE_TARGETS
    on_disk = {path.name for path in support.FIXTURES.iterdir() if path.is_dir()}
    assert {path.name for path in FIXTURE_TARGETS} == on_disk


@pytest.mark.parametrize("target", FIXTURE_TARGETS, ids=lambda item: item.name)
def test_every_committed_fixture_profiles_without_error(target: Path) -> None:
    record = survey_repository_profile(target)
    assert record.dimensions_total > 0
    assert (
        record.dimensions_resolved + record.dimensions_conflicted + record.dimensions_unknown
        == record.dimensions_total
    )
    assert record.attributions_total >= record.attributions_with_confidence
    assert record.attributions_total == (
        record.attributions_with_evidence_refs + record.attributions_without_evidence_refs
    )
    assert record.attributions_total == (
        record.attributions_observed
        + record.attributions_declared
        + record.attributions_inferred
        + record.attributions_normative
    )


def test_a_declared_project_resolves_more_dimensions_than_an_undeclared_one() -> None:
    """The measurement this survey exists to produce, on the two contrasting fixtures
    the friction survey already relies on for the same purpose."""
    declared = survey_repository_profile(support.FIXTURES / "e2e-synthetic")
    undeclared = survey_repository_profile(support.FIXTURES / "brownfield-foundry-scratch-only")

    assert declared.project_name_present
    assert not undeclared.project_name_present
    assert declared.dimensions_resolved > undeclared.dimensions_resolved
    assert declared.dimensions_unknown < undeclared.dimensions_unknown
    assert declared.attributions_declared > 0
    assert undeclared.attributions_declared == 0


# ---------------------------------------------------------------------------
# compare()
# ---------------------------------------------------------------------------


def test_compare_of_identical_payloads_is_empty() -> None:
    result = survey_profiles(FIXTURE_TARGETS)
    payload = aggregate_profile(result)
    delta = compare(payload, payload)
    for value in delta.values():
        if isinstance(value, dict):
            assert value == {} or all(v != 0 for v in value.values() if isinstance(v, int))
        else:
            assert value == 0


def test_compare_reports_the_direction_and_size_of_a_numeric_change() -> None:
    before = {"repositories": 3, "attributions_total": 10, "readiness_blockers_total": 0}
    after = {"repositories": 5, "attributions_total": 7, "readiness_blockers_total": 0}
    delta = compare(before, after)
    assert delta["repositories"] == 2
    assert delta["attributions_total"] == -3
    assert "readiness_blockers_total" not in delta  # unchanged keys are omitted


def test_compare_reports_only_the_dimension_names_whose_counts_actually_moved() -> None:
    before = {"resolved_dimension_counts": {"project.name": 1, "intake_mode": 2}}
    after = {"resolved_dimension_counts": {"project.name": 1, "intake_mode": 3, "state.persistence": 1}}
    delta = compare(before, after)
    assert delta["resolved_dimension_counts"] == {"intake_mode": 1, "state.persistence": 1}
    assert "project.name" not in delta["resolved_dimension_counts"]


def test_compare_output_contains_no_target_text_when_built_from_real_fixtures() -> None:
    half = len(FIXTURE_TARGETS) // 2 or 1
    before = aggregate_profile(survey_profiles(FIXTURE_TARGETS[:half]))
    after = aggregate_profile(survey_profiles(FIXTURE_TARGETS))
    delta_payload = json.dumps(compare(before, after), sort_keys=True)

    for target in FIXTURE_TARGETS:
        assert target.name not in delta_payload
        assert str(target) not in delta_payload
    for marker in ("/Users/", "/home/", str(support.REPO_ROOT)):
        assert marker not in delta_payload


def test_compare_never_returns_a_bool_typed_as_a_number() -> None:
    """A stray `True`/`False` slipping into a numeric delta (`True - False == 1`) would
    silently misrepresent a boolean field as a count. `_numeric_delta` guards this."""
    before = {"walk_exhaustive_flag_example": True}
    after = {"walk_exhaustive_flag_example": False}
    delta = compare(before, after)
    assert "walk_exhaustive_flag_example" not in delta
