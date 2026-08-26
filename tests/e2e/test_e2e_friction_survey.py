"""The friction survey emits counts, and structurally cannot emit anything else.

The V0.1 readiness report quotes aggregate figures over repositories that are not in
this branch. What *is* in this branch is the method: `tests/e2e/friction_survey.py`,
run here over the committed fixtures so its shape is checked, and its privacy property
proved rather than promised.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from agent_foundry.verify import VALIDATOR_IDS  # noqa: F401  (import-order sanity)

from tests.e2e import support
from tests.e2e.friction_survey import (
    MANIFEST_DIMENSION_COUNT,
    RepositorySurvey,
    aggregate,
    discover_repositories,
    survey,
    survey_repository,
)

FIXTURE_TARGETS = [
    support.FIXTURES / "e2e-synthetic",
    support.FIXTURES / "brownfield-sample",
    support.FIXTURES / "greenfield-minimal",
    support.FIXTURES / "brownfield-foundry-scratch-only",
]


def test_no_survey_field_can_hold_a_path_a_name_or_content() -> None:
    """Privacy is a property of the type, not of how carefully it is used.

    Every field is an int or a bool, except `convention_subjects` and
    `adoption_actions`, which hold Foundry's own fixed vocabulary terms. There is no
    position a repository path, project name, or file content could be written into,
    so leaking one would take a change to the dataclass rather than a slip in using it.
    """
    numeric = {"int", "bool"}
    vocabulary_fields = {"convention_subjects", "adoption_actions"}
    for item in dataclasses.fields(RepositorySurvey):
        annotation = str(item.type)
        if item.name in vocabulary_fields:
            assert annotation == "tuple[str, ...]"
            continue
        assert annotation in numeric, (
            f"{item.name} is typed {annotation!r}; a survey field that is not a number "
            "is a field a private value can reach"
        )


def test_the_vocabulary_fields_only_ever_carry_foundry_vocabulary() -> None:
    from agent_foundry.models import AdoptionAction

    known_conventions = {"test-runner", "test-invocation", "ci-checkout", "git-policy"}
    known_actions = {member.value for member in AdoptionAction}
    for target in FIXTURE_TARGETS:
        record = survey_repository(target)
        assert set(record.convention_subjects) <= known_conventions
        assert set(record.adoption_actions) <= known_actions


def test_the_aggregate_output_is_json_and_contains_no_target_text() -> None:
    result = survey(FIXTURE_TARGETS)
    assert result.failed == 0
    payload = json.dumps(aggregate(result), sort_keys=True)

    for target in FIXTURE_TARGETS:
        assert target.name not in payload
        assert str(target) not in payload
    for marker in ("/Users/", "/home/", str(support.REPO_ROOT)):
        assert marker not in payload


def test_the_survey_reports_a_failure_without_quoting_it(tmp_path: Path) -> None:
    """A target that cannot be inspected is counted by exception type, never by message.

    An inspection failure routinely quotes the path that failed, so the message is the
    one thing that must not survive into the record.
    """
    missing = tmp_path / "not-a-directory-with-a-revealing-name"
    result = survey([missing])
    assert result.surveys == []
    assert result.failed == 1
    assert result.failure_types == ("FileNotFoundError",)
    assert missing.name not in json.dumps(aggregate(result))


def test_the_survey_counts_the_manifest_dimensions_the_product_actually_has() -> None:
    """The headline friction number is 'n of MANIFEST_DIMENSION_COUNT'.

    If the manifest grows a characteristic and this constant does not, every figure
    quoted against it silently understates how much an owner has to declare.
    """
    from agent_foundry.inspect.classification import CLASSIFICATION_DIMENSIONS

    assert MANIFEST_DIMENSION_COUNT == len(CLASSIFICATION_DIMENSIONS)


def test_a_declared_project_populates_every_dimension_and_an_undeclared_one_populates_one() -> None:
    """The measurement this whole survey exists to produce, on committed fixtures."""
    declared = survey_repository(support.FIXTURES / "e2e-synthetic")
    assert declared.declaration_present
    assert declared.manifest_fields_populated == MANIFEST_DIMENSION_COUNT
    assert declared.roles_resolved > 0

    undeclared = survey_repository(support.FIXTURES / "brownfield-foundry-scratch-only")
    assert not undeclared.declaration_present
    assert undeclared.manifest_fields_populated == 1, (
        "inference supplies intake_mode and nothing else, by design"
    )
    assert undeclared.roles_resolved == 0
    assert undeclared.capabilities_resolved == 0


def test_discovery_skips_hidden_and_underscored_directories(tmp_path: Path) -> None:
    for name in ("visible", ".hidden", "_scratch"):
        (tmp_path / name / ".git").mkdir(parents=True)
    (tmp_path / "not-a-repo").mkdir()
    found = discover_repositories([tmp_path])
    assert [item.name for item in found] == ["visible"]


@pytest.mark.parametrize("target", FIXTURE_TARGETS, ids=lambda item: item.name)
def test_every_committed_fixture_surveys_without_error(target: Path) -> None:
    record = survey_repository(target)
    assert record.entries_visited > 0
    assert 0 <= record.manifest_fields_populated <= MANIFEST_DIMENSION_COUNT
