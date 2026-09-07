"""The real-repository survey emits counts, one operator label, and nothing else.

SUE-581 asks whether `ProjectProfile` materially reduces V0.1's defining usability
failure — an undeclared brownfield project resolving to an empty operating state. The
answer has to come from a corpus of real, materially different repositories, which by
definition is not in this branch. What *is* in this branch is the method:
`tests/e2e/real_repository_survey.py`, exercised here over the committed fixtures and a
`tmp_path` construction, so the suite stays hermetic and needs neither `/tmp` nor the
network.

Three properties are proved rather than promised, following
`test_e2e_friction_survey.py` and `test_e2e_profile_delta_survey.py`:

* the record's *shape* rules out a private value in every field but the one
  deliberately-isolated `repository_label`, and a blank label leaks nothing;
* the survey never writes into a target;
* the rejection signal is a computed property of the record, so "31 of 31 resolved"
  cannot by itself read as a good profile.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from agent_foundry.adopt.authority import AuthorityAxis
from agent_foundry.inspect.classification import CLASSIFICATION_DIMENSIONS
from agent_foundry.inspect.conventions import TEST_INVOCATION_SUBJECT, TEST_RUNNER_SUBJECT
from agent_foundry.models import AdoptionAction, ProvenanceKind

from tests.e2e import support
from tests.e2e.friction_survey import MANIFEST_DIMENSION_COUNT
from tests.e2e.friction_survey import survey_repository as friction_survey_repository
from tests.e2e.real_repository_survey import (
    AUTHORITY_BEARING_DIMENSIONS,
    CLASSIFICATION_DIMENSION_NAMES,
    HIGH_COVERAGE_SHARE,
    EvidenceRejection,
    RealRepositorySurvey,
    _parse_argv,
    aggregate,
    baseline_comparison_rows,
    build_adversarial_project,
    survey,
    survey_repository,
)

# Enumerated from disk rather than listed by hand, exactly as the two earlier survey
# tests do: a fixture added tomorrow is surveyed the day it is added.
FIXTURE_TARGETS = sorted(path for path in support.FIXTURES.iterdir() if path.is_dir())

DECLARED_FIXTURE = support.FIXTURES / "e2e-synthetic"
UNDECLARED_FIXTURE = support.FIXTURES / "brownfield-foundry-scratch-only"

# A string no repository could contain, used to prove the label reaches exactly one
# field and is never interpolated into another.
LABEL_MARKER = "zz-label-marker-9137"


def _blank_targets(paths: list[Path]) -> list[tuple[str, Path]]:
    return [("", path) for path in paths]


# ---------------------------------------------------------------------------
# Privacy: a property of the type, plus one deliberately isolated exception.
# ---------------------------------------------------------------------------


def test_only_the_label_field_can_hold_a_name() -> None:
    """Every field but `repository_label` is a number, a boolean, or fixed vocabulary.

    This is the same structural claim the friction and profile-delta surveys make, with
    the one difference SUE-581 deliberately introduces: a public corpus is worth naming,
    so exactly one field may carry a name. It is typed `str`, it is the only `str` in
    the record, and it is supplied by the operator — never derived from a target.
    """
    numeric = {"int", "bool"}
    vocabulary_fields = {
        "resolved_dimension_names",
        "conflicted_dimension_names",
        "unknown_dimension_names",
        "authority_dimension_names_unknown",
        "adoption_actions",
        "convention_subjects",
        "readiness_blocker_dimensions",
    }
    string_fields = set()
    for item in dataclasses.fields(RealRepositorySurvey):
        annotation = str(item.type)
        if item.name == "repository_label":
            assert annotation == "str"
            string_fields.add(item.name)
            continue
        if item.name in vocabulary_fields:
            assert annotation == "tuple[str, ...]"
            continue
        assert annotation in numeric, (
            f"{item.name} is typed {annotation!r}; a survey field that is neither a "
            "number nor a declared vocabulary tuple is a field a private value can reach"
        )
    assert string_fields == {"repository_label"}, (
        "a second free-text field would defeat the isolation the label depends on"
    )


def test_the_record_has_no_field_a_dimension_value_could_land_in() -> None:
    """`ProfileDimension.attributions[*].value` is repository content and has no
    counterpart field here — the concrete form of the structural claim above."""
    field_names = {item.name for item in dataclasses.fields(RealRepositorySurvey)}
    for forbidden in ("value", "values", "attribution", "attributions", "content", "path", "evidence"):
        assert forbidden not in field_names


def test_a_supplied_label_reaches_exactly_one_field_and_no_other() -> None:
    """The isolation half of the label contract: never interpolated into anything."""
    record = survey_repository(DECLARED_FIXTURE, repository_label=LABEL_MARKER)
    assert record.repository_label == LABEL_MARKER
    for item in dataclasses.fields(RealRepositorySurvey):
        if item.name == "repository_label":
            continue
        value = getattr(record, item.name)
        assert LABEL_MARKER not in json.dumps(value), (
            f"{item.name} carries the label; the label must occupy one field alone"
        )
    # The computed properties are derived from those fields, so they inherit the same
    # isolation — asserted rather than assumed.
    assert LABEL_MARKER not in json.dumps(list(record.rejection_reasons))


def test_a_blank_label_leaks_nothing_so_a_private_target_is_recordable() -> None:
    """The property a future private corpus depends on: with the label left blank, the
    aggregate holds no target's own name, path, or any home-directory marker."""
    result = survey(_blank_targets(FIXTURE_TARGETS))
    assert result.failed == 0
    assert all(item.repository_label == "" for item in result.surveys)
    payload = json.dumps(aggregate(result), sort_keys=True)

    for target in FIXTURE_TARGETS:
        assert target.name not in payload
        assert str(target) not in payload
    for marker in ("/Users/", "/home/", str(support.REPO_ROOT)):
        assert marker not in payload


def test_recorded_dimension_names_cannot_vary_with_repository_content() -> None:
    """Two structurally different fixtures record the same dimension *vocabulary*.

    Dimension names are string literals fixed in `agent_foundry.profile.synth`; the
    direct way to check they cannot be built from a target is to profile two very
    different targets and find the name sets identical, and each target's own name
    absent from them.
    """
    declared = survey_repository(DECLARED_FIXTURE)
    undeclared = survey_repository(UNDECLARED_FIXTURE)

    def names(record: RealRepositorySurvey) -> set[str]:
        return set(
            record.resolved_dimension_names
            + record.conflicted_dimension_names
            + record.unknown_dimension_names
        )

    assert names(declared) == names(undeclared)
    for target, record in ((DECLARED_FIXTURE, declared), (UNDECLARED_FIXTURE, undeclared)):
        for name in names(record):
            assert target.name not in name
            assert str(target) not in name


def test_the_vocabulary_tuples_only_carry_foundry_vocabulary() -> None:
    # `test-runner` and `test-invocation` are imported from the module that owns them;
    # `ci-checkout` and `git-policy` are literals at their own call sites in
    # `inspect/conventions.py` and are named the same way `test_e2e_friction_survey.py`
    # names them, so the two tests cannot disagree about the vocabulary.
    known_conventions = {TEST_RUNNER_SUBJECT, TEST_INVOCATION_SUBJECT, "ci-checkout", "git-policy"}
    known_actions = {member.value for member in AdoptionAction}
    known_rejections = {member.value for member in EvidenceRejection}
    for target in FIXTURE_TARGETS:
        record = survey_repository(target)
        assert set(record.convention_subjects) <= known_conventions
        assert set(record.adoption_actions) <= known_actions
        assert set(record.rejection_reasons) <= known_rejections
        assert set(record.authority_dimension_names_unknown) <= AUTHORITY_BEARING_DIMENSIONS
        for name in record.readiness_blocker_dimensions:
            assert target.name not in name


def test_the_survey_reports_a_failure_without_quoting_it(tmp_path: Path) -> None:
    """A target that cannot be inspected is counted by exception type, never message —
    and a failed target contributes no label either."""
    missing = tmp_path / "not-a-directory-with-a-revealing-name"
    result = survey([(missing.name, missing)])
    assert result.surveys == []
    assert result.failed == 1
    assert result.failure_types == ("FileNotFoundError",)
    assert missing.name not in json.dumps(aggregate(result))


def test_the_harness_source_names_no_repository_it_surveys() -> None:
    """No corpus list and no per-repository branch live in the harness.

    A named corpus baked into the module would be a second source of truth about what
    was surveyed; a branch on a target's identity would be the project-type classifier
    SUE-581 forbids. Neither can hide from this: the module's own source is scanned for
    every fixture's name.
    """
    source = (Path(__file__).parent / "real_repository_survey.py").read_text(encoding="utf-8")
    for target in FIXTURE_TARGETS:
        assert target.name not in source


# ---------------------------------------------------------------------------
# Read-only.
# ---------------------------------------------------------------------------


def test_the_survey_never_writes_into_a_target(tmp_path: Path) -> None:
    """Proved, not asserted: content, mode and mtime of every path, before and after.

    mtime is the load-bearing part — an inspector that opened and rewrote a file
    identically would pass a content-only comparison.
    """
    target = tmp_path / "target"
    build_adversarial_project(target)
    before = support.tree_snapshot(target)
    survey_repository(target, repository_label=LABEL_MARKER)
    assert support.tree_snapshot(target) == before


def test_build_adversarial_project_refuses_a_directory_that_holds_anything(tmp_path: Path) -> None:
    """The one writing function in the harness cannot land on an existing repository."""
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "README.md").write_text("existing\n", encoding="utf-8")
    with pytest.raises(ValueError):
        build_adversarial_project(occupied)
    assert (occupied / "README.md").read_text(encoding="utf-8") == "existing\n"


# ---------------------------------------------------------------------------
# The vocabularies are derived from the code that owns them.
# ---------------------------------------------------------------------------


def test_authority_bearing_dimensions_are_the_adoption_guard_s_own_axes() -> None:
    """Which manifest fields bear authority is `adopt.authority`'s decision, not this
    survey's. A new axis there is counted here the day it is added."""
    assert AUTHORITY_BEARING_DIMENSIONS == {axis.value for axis in AuthorityAxis}
    assert AUTHORITY_BEARING_DIMENSIONS
    assert AUTHORITY_BEARING_DIMENSIONS <= CLASSIFICATION_DIMENSION_NAMES


def test_the_classification_vocabulary_is_the_inspectors_own() -> None:
    assert CLASSIFICATION_DIMENSION_NAMES == set(CLASSIFICATION_DIMENSIONS)
    assert len(CLASSIFICATION_DIMENSIONS) == MANIFEST_DIMENSION_COUNT


def test_the_v01_baseline_number_is_the_friction_surveys_own_number() -> None:
    """The before/after contrast is only meaningful if 'before' is the figure V0.1's
    own measurement already quotes. Recomputing it here would be a second source of
    truth, so it is checked equal on every committed fixture."""
    for target in FIXTURE_TARGETS:
        assert (
            survey_repository(target).baseline_manifest_fields_populated
            == friction_survey_repository(target).manifest_fields_populated
        )


@pytest.mark.parametrize("target", FIXTURE_TARGETS, ids=lambda item: item.name)
def test_every_committed_fixture_surveys_without_error(target: Path) -> None:
    record = survey_repository(target)
    assert record.entries_visited > 0
    assert record.dimensions_total > 0
    assert (
        record.dimensions_resolved + record.dimensions_conflicted + record.dimensions_unknown
        == record.dimensions_total
    )
    assert record.attributions_total == (
        record.attributions_observed
        + record.attributions_declared
        + record.attributions_inferred
        + record.attributions_normative
    )
    assert record.attributions_total == (
        record.attributions_with_evidence_refs + record.attributions_without_evidence_refs
    )
    assert record.dimensions_resolved == (
        record.resolved_dimensions_with_evidence_refs
        + record.resolved_dimensions_without_evidence_refs
    )
    assert record.conventions_discovered == (
        record.conventions_observed
        + record.conventions_declared
        + record.conventions_inferred
        + record.conventions_normative
    )
    assert 0 <= record.baseline_manifest_fields_populated <= MANIFEST_DIMENSION_COUNT
    assert (
        record.baseline_manifest_fields_populated + record.baseline_manifest_fields_unpopulated
        == MANIFEST_DIMENSION_COUNT
    )
    # `profile.synth` deliberately never publishes `authority.write_scope`; the survey
    # counts the withholding rather than restating which dimension it is.
    assert record.classification_dimensions_withheld_from_profile >= 1
    assert record.conventions_structured <= record.conventions_declared


# ---------------------------------------------------------------------------
# The measurement the survey exists to produce.
# ---------------------------------------------------------------------------


def test_the_profile_resolves_more_than_the_v01_manifest_for_an_undeclared_project() -> None:
    """V0.1's defining failure, and what V0.2 does about it — on committed fixtures.

    The undeclared fixture's manifest populates exactly one of sixteen characteristics
    and resolves no toolkit at all. Its profile still resolves structural dimensions,
    which is the improvement claim; what it does *not* do is fill in the substantive
    half, and the assertions below pin both halves so neither can be quoted alone.
    """
    undeclared = survey_repository(UNDECLARED_FIXTURE)

    assert not undeclared.baseline_declaration_present
    assert undeclared.baseline_manifest_fields_populated == 1
    assert undeclared.baseline_toolkit_roles_resolved == 0
    assert undeclared.baseline_toolkit_capabilities_resolved == 0

    assert undeclared.dimensions_resolved > undeclared.baseline_manifest_fields_populated
    # ... and the improvement is structural, not substantive: what an owner would have
    # had to declare is still overwhelmingly unknown.
    assert undeclared.classification_dimensions_unknown > 0


def test_an_undeclared_project_leaves_every_authority_dimension_unknown() -> None:
    """A rising authority-unknown count is the correct outcome, not a failure.

    Nothing in this survey may fill an authority-bearing dimension to improve a coverage
    number: with no declaration there is no owner decision, and UNKNOWN is the honest
    record of that.
    """
    undeclared = survey_repository(UNDECLARED_FIXTURE)
    assert undeclared.authority_dimensions_total == len(AUTHORITY_BEARING_DIMENSIONS)
    assert undeclared.authority_dimensions_unknown == undeclared.authority_dimensions_total
    assert undeclared.authority_dimensions_resolved == 0
    assert set(undeclared.authority_dimension_names_unknown) == AUTHORITY_BEARING_DIMENSIONS


def test_a_declared_project_resolves_authority_dimensions_only_from_declarations() -> None:
    declared = survey_repository(DECLARED_FIXTURE)
    assert declared.baseline_declaration_present
    assert declared.authority_dimensions_resolved == declared.authority_dimensions_total
    assert declared.authority_dimensions_declared_only == declared.authority_dimensions_resolved
    assert declared.attributions_declared > 0


def test_toolkit_readiness_does_not_move_with_profile_coverage() -> None:
    """A `ProjectProfile` feeds no toolkit resolution in this version.

    The undeclared fixture resolves profile dimensions and still resolves zero roles and
    zero capabilities. Recording that is the point: the survey has to be able to show
    where the profile *fails* to improve V0.1 usability, not only where it helps.
    """
    undeclared = survey_repository(UNDECLARED_FIXTURE)
    assert undeclared.dimensions_resolved > 0
    assert undeclared.baseline_toolkit_roles_resolved == 0
    assert undeclared.baseline_toolkit_capabilities_resolved == 0


def test_traversal_truncation_and_unread_files_are_recorded_per_repository() -> None:
    for target in FIXTURE_TARGETS:
        record = survey_repository(target)
        assert isinstance(record.entry_limit_reached, bool)
        assert isinstance(record.depth_limit_reached, bool)
        assert record.walk_exhaustive <= record.walk_path_exhaustive
        if record.files_over_read_limit or not record.walk_path_exhaustive:
            assert not record.walk_exhaustive


# ---------------------------------------------------------------------------
# The adversarial case: total coverage, poor evidence, still rejected.
# ---------------------------------------------------------------------------


def test_total_coverage_is_still_rejected_when_the_evidence_is_poor(tmp_path: Path) -> None:
    """The required adversarial case.

    The construction declares every characteristic in one file, mentions a test runner
    in prose, and holds nothing else — no package metadata, no CI, no structured test
    configuration. Its profile resolves *every* dimension over a walk that left no hole
    at all, which is the strongest possible coverage number, and the survey still
    surfaces reasons not to take it at face value.
    """
    target = tmp_path / "adversarial"
    build_adversarial_project(target)
    record = survey_repository(target)

    assert record.dimensions_unknown == 0
    assert record.dimensions_conflicted == 0
    assert record.coverage_ratio == 1.0
    assert record.high_coverage
    assert record.walk_exhaustive, "the coverage was not bought with a truncated walk"
    # The V0.1 baseline looks perfect here too: every manifest characteristic is
    # populated. Neither number is a statement about whether any of it is true.
    assert record.baseline_manifest_fields_populated == MANIFEST_DIMENSION_COUNT

    assert not record.coverage_is_supported
    assert record.high_coverage_unsupported
    reasons = set(record.rejection_reasons)
    assert EvidenceRejection.SINGLE_SOURCE_CLASSIFICATION.value in reasons
    assert EvidenceRejection.UNCORROBORATED_AUTHORITY_DECLARATION.value in reasons
    assert EvidenceRejection.CONVENTIONS_WITHOUT_STRUCTURED_DECLARATION.value in reasons
    assert EvidenceRejection.EVIDENCE_SPARSE_COVERAGE.value in reasons


def test_the_adversarial_coverage_collapses_without_its_one_declaration(tmp_path: Path) -> None:
    """The concrete measure of how little is underneath it: delete one file and the
    substantive half of the profile is gone."""
    target = tmp_path / "adversarial"
    build_adversarial_project(target)
    full = survey_repository(target)
    (target / ".foundry" / "project.yaml").unlink()
    stripped = survey_repository(target)

    assert full.classification_dimensions_resolved > stripped.classification_dimensions_resolved
    assert stripped.authority_dimensions_unknown == stripped.authority_dimensions_total
    assert stripped.dimensions_resolved < full.dimensions_resolved


def test_evidence_breadth_discriminates_rather_than_firing_on_any_declaration() -> None:
    """`evidence-sparse-coverage` is about evidence *breadth*, not about declaring.

    Agent Foundry itself is declared and high-coverage, and does not trip it; the
    adversarial construction is declared and total-coverage, and does. If the signal
    fired on every declared project it would carry no information.
    """
    self_record = survey_repository(support.REPO_ROOT)
    assert self_record.coverage_ratio >= HIGH_COVERAGE_SHARE
    assert EvidenceRejection.EVIDENCE_SPARSE_COVERAGE.value not in self_record.rejection_reasons


def test_the_rejection_signal_is_computed_from_the_record_not_annotated() -> None:
    """Changing a recorded count changes the verdict — so the verdict is a property of
    the evidence, not a note somebody attached to a repository."""
    record = survey_repository(DECLARED_FIXTURE)
    widened = dataclasses.replace(
        record,
        distinct_evidence_sources=record.dimensions_resolved * 10,
        conventions_structured=1,
        classification_declaration_sources=3,
        authority_dimensions_declared_only=0,
    )
    assert widened.rejection_reasons == () or set(widened.rejection_reasons) < set(
        record.rejection_reasons
    )

    narrowed = dataclasses.replace(record, distinct_evidence_sources=0)
    assert EvidenceRejection.EVIDENCE_SPARSE_COVERAGE.value in narrowed.rejection_reasons


def test_completeness_alone_is_never_treated_as_correctness() -> None:
    """A record with no rejection reason is not thereby certified correct — the survey
    says only that it found no reason to reject it."""
    record = survey_repository(DECLARED_FIXTURE)
    clean = dataclasses.replace(
        record,
        distinct_evidence_sources=record.dimensions_total * 10,
        conventions_structured=max(record.conventions_declared, 1),
        conventions_declared=max(record.conventions_declared, 1),
        classification_declaration_sources=5,
        authority_dimensions_declared_only=0,
        walk_path_exhaustive=True,
        walk_exhaustive=True,
    )
    assert clean.coverage_is_supported
    # `coverage_is_supported` is the *absence* of a reason to reject, and the record
    # exposes no field claiming correctness for anything to read as one.
    assert "correct" not in {item.name for item in dataclasses.fields(RealRepositorySurvey)}


# ---------------------------------------------------------------------------
# Aggregate and entry point.
# ---------------------------------------------------------------------------


def test_the_aggregate_carries_one_row_per_repository_and_is_json() -> None:
    labelled = [(f"{LABEL_MARKER}-{index}", path) for index, path in enumerate(FIXTURE_TARGETS)]
    result = survey(labelled)
    payload = aggregate(result)
    rows = payload["per_repository"]
    assert isinstance(rows, list)
    assert len(rows) == len(FIXTURE_TARGETS)
    assert [row["repository_label"] for row in rows] == [label for label, _ in labelled]
    for row in rows:
        assert row["v01_manifest_dimension_count"] == MANIFEST_DIMENSION_COUNT
        assert row["v02_dimensions_resolved"] <= row["v02_dimensions_total"]
    json.dumps(payload, sort_keys=True)


def test_the_baseline_rows_put_v01_and_v02_side_by_side() -> None:
    rows = baseline_comparison_rows(survey(_blank_targets([UNDECLARED_FIXTURE])))
    row = rows[0]
    assert row["v01_manifest_fields_populated"] == 1
    assert row["v01_toolkit_roles_resolved"] == 0
    assert row["v02_dimensions_resolved"] > row["v01_manifest_fields_populated"]
    assert row["repository_label"] == ""


def test_an_empty_aggregate_reports_nothing_but_counts() -> None:
    payload = aggregate(survey([]))
    assert payload == {"repositories": 0, "failed": 0, "failure_types": []}


def test_targets_come_from_the_command_line_and_labels_default_to_blank(tmp_path: Path) -> None:
    for name in ("alpha", "beta"):
        (tmp_path / name / ".git").mkdir(parents=True)

    targets, public = _parse_argv([str(tmp_path / "alpha")])
    assert targets == [("", tmp_path / "alpha")]
    assert not public

    targets, public = _parse_argv(["--public-labels", str(tmp_path / "alpha")])
    assert targets == [("alpha", (tmp_path / "alpha"))]
    assert public

    targets, _ = _parse_argv(["--label", f"public-name={tmp_path / 'beta'}"])
    assert targets == [("public-name", tmp_path / "beta")]

    targets, _ = _parse_argv(["--under", str(tmp_path)])
    assert [label for label, _ in targets] == ["", ""]
    assert sorted(path.name for _, path in targets) == ["alpha", "beta"]


def test_unknown_options_and_malformed_labels_are_rejected() -> None:
    with pytest.raises(ValueError):
        _parse_argv(["--nope"])
    with pytest.raises(ValueError):
        _parse_argv(["--label", "no-equals-sign"])


def test_the_adversarial_construction_is_available_to_the_entry_point(tmp_path: Path) -> None:
    targets, _ = _parse_argv(["--adversarial", str(tmp_path / "built")])
    assert [path.name for _, path in targets] == ["built"]
    assert (tmp_path / "built" / ".foundry" / "project.yaml").is_file()


def test_the_construction_declares_no_project_type_and_names_no_language() -> None:
    """The adversarial fixture must not smuggle in the project-type classifier the
    contract forbids: it is a declaration with nothing behind it, not a shape."""
    source = (Path(__file__).parent / "real_repository_survey.py").read_text(encoding="utf-8")
    declaration_start = source.index("_ADVERSARIAL_DECLARATION = ")
    declaration = source[declaration_start : source.index('"""', declaration_start + 40)]
    for forbidden in ("python", "node", "rust", "golang", "ruby", "java"):
        assert forbidden not in declaration.lower()


def test_provenance_kinds_are_counted_over_the_whole_enum() -> None:
    """Every provenance kind gets a counter, so a new kind cannot be silently dropped
    from the attribution and convention breakdowns."""
    field_names = {item.name for item in dataclasses.fields(RealRepositorySurvey)}
    for kind in ProvenanceKind:
        assert f"attributions_{kind.value}" in field_names
        assert f"conventions_{kind.value}" in field_names
