"""Readiness must distinguish "not found" from "not fully observed".

SUE-580 / Lane B. These tests prove that ``assess_readiness`` never asserts
absence over ground the walk could not see, and that a deliberately skipped
directory (scoping) is never confused with a genuine hole (incompleteness).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent_foundry.inspect import inspect_project
from agent_foundry.inspect.readiness import assess_readiness
from agent_foundry.models.common import Provenance, ProvenanceKind
from agent_foundry.models.project import (
    ProjectObservation,
    TraversalLimits,
    TraversalStats,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _stats(
    *,
    entries_visited: int = 10,
    entries_skipped: int = 0,
    entries_skipped_ignored_dir: int = 0,
    entries_skipped_refused: int = 0,
    entries_skipped_unreadable: int = 0,
    entries_unobservable: int = 0,
    depth_limit_reached: bool = False,
    entry_limit_reached: bool = False,
) -> TraversalStats:
    return TraversalStats(
        entries_visited=entries_visited,
        entries_skipped=entries_skipped,
        entries_skipped_ignored_dir=entries_skipped_ignored_dir,
        entries_skipped_refused=entries_skipped_refused,
        entries_skipped_unreadable=entries_skipped_unreadable,
        entries_unobservable=entries_unobservable,
        depth_limit_reached=depth_limit_reached,
        entry_limit_reached=entry_limit_reached,
        limits=TraversalLimits(max_depth=8, max_entries=5000, max_file_bytes=200_000),
    )


def _observation(subject: str, content: str = "x", source_ref: str = "some/path") -> ProjectObservation:
    return ProjectObservation(
        subject=subject,
        content=content,
        provenance=Provenance(kind=ProvenanceKind.OBSERVED, confidence=1.0, source_ref=source_ref),
    )


_BASE_OBSERVATIONS = [_observation("repository-structure", "3 files, 1 directories")]


def _completeness_finding(findings):
    matches = [f for f in findings if f.dimension == "inspection-completeness"]
    assert len(matches) == 1
    return matches[0]


def _absence_shaped_dimensions() -> set[str]:
    """Every dimension with a "found vs not found" shape, derived from the
    findings themselves rather than hand-listed (SUE-580 S6): assess a fully
    exhaustive walk that observed nothing beyond the base observations, and
    collect every dimension whose resolved message reads as a plain "No ..."
    absence claim. A dimension added to ``readiness.py`` without an
    ``elif not exhaustive`` branch — the bug this suite exists to catch — still
    shows up here automatically, because it still resolves to a "No ..."
    message on a fully exhaustive walk; only the *gating* on incompleteness is
    what could be silently missing, which is exactly what the tests below
    check for each such dimension.
    """
    findings = assess_readiness(Path("."), _BASE_OBSERVATIONS, [], stats=_stats())
    return {f.dimension for f in findings if f.message.startswith("No ")}


def _absence_messages(findings) -> list[str]:
    """Every message from a dimension that has a "found vs not found" shape."""
    absence_dims = _absence_shaped_dimensions()
    return [f.message for f in findings if f.dimension in absence_dims]


# ---------------------------------------------------------------------------
# A. Fully observed -> no incompleteness claimed
# ---------------------------------------------------------------------------


def test_fully_observed_project_reports_no_incompleteness(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("hello\n")
    intake = inspect_project(tmp_path)
    completeness = _completeness_finding(intake.readiness_findings)
    assert "not fully observed" not in completeness.message
    assert completeness.severity.value == "low"


def test_fully_observed_project_unit_level_no_incompleteness() -> None:
    stats = _stats()
    findings = assess_readiness(Path("."), _BASE_OBSERVATIONS, [], stats=stats)
    completeness = _completeness_finding(findings)
    assert "not fully observed" not in completeness.message
    assert "genuine hole" in completeness.message


# ---------------------------------------------------------------------------
# B. Genuine holes -> incompleteness reported explicitly
# ---------------------------------------------------------------------------


def test_depth_limited_walk_reports_incomplete_inspection() -> None:
    stats = _stats(depth_limit_reached=True)
    findings = assess_readiness(Path("."), _BASE_OBSERVATIONS, [], stats=stats)
    completeness = _completeness_finding(findings)
    assert "not fully observed" in completeness.message
    assert "depth limit reached" in completeness.message
    assert completeness.severity.value == "high"


def test_entry_limited_walk_reports_incomplete_inspection() -> None:
    stats = _stats(entry_limit_reached=True)
    findings = assess_readiness(Path("."), _BASE_OBSERVATIONS, [], stats=stats)
    completeness = _completeness_finding(findings)
    assert "not fully observed" in completeness.message
    assert "entry limit reached" in completeness.message


def test_containment_refused_path_reports_incomplete_inspection() -> None:
    stats = _stats(entries_skipped_refused=2)
    findings = assess_readiness(Path("."), _BASE_OBSERVATIONS, [], stats=stats)
    completeness = _completeness_finding(findings)
    assert "not fully observed" in completeness.message
    assert "2 containment-refused path(s)" in completeness.message


def test_unobservable_path_reports_incomplete_inspection() -> None:
    observations = _BASE_OBSERVATIONS + [
        _observation("path-unobservable", "directory contents could not be observed (permission-denied): secret")
    ]
    stats = _stats(entries_unobservable=1)
    findings = assess_readiness(Path("."), observations, [], stats=stats)
    completeness = _completeness_finding(findings)
    assert "not fully observed" in completeness.message
    assert "1 unobservable path(s)" in completeness.message


def test_unobservable_path_detected_without_stats_via_observation_alone() -> None:
    # `path-unobservable` observations already flow through `observations`
    # regardless of whether a caller threads `TraversalStats` through.
    observations = _BASE_OBSERVATIONS + [_observation("path-unobservable", "x")]
    findings = assess_readiness(Path("."), observations, [], stats=None)
    completeness = _completeness_finding(findings)
    assert "not fully observed" in completeness.message
    assert "1 unobservable path(s)" in completeness.message


def test_oversized_unread_file_reports_incomplete_inspection() -> None:
    observations = _BASE_OBSERVATIONS + [
        _observation("file-read-skipped", "file exceeds read limit (999 > 10 bytes): big.bin")
    ]
    stats = _stats()
    findings = assess_readiness(Path("."), observations, [], stats=stats)
    completeness = _completeness_finding(findings)
    assert "not fully observed" in completeness.message
    assert "1 file(s) skipped for exceeding the read-size limit" in completeness.message


def test_oversized_unread_file_end_to_end_through_inspect_project(tmp_path: Path) -> None:
    (tmp_path / "small.txt").write_text("ok\n")
    (tmp_path / "big.txt").write_text("x" * 5000)
    intake = inspect_project(tmp_path, max_file_bytes=10)
    unread = [o for o in intake.observations if o.subject == "file-read-skipped"]
    assert unread  # wiring precondition: the collector actually flagged the file
    completeness = _completeness_finding(intake.readiness_findings)
    assert "not fully observed" in completeness.message
    assert "file(s) skipped for exceeding the read-size limit" in completeness.message


def test_depth_limited_walk_end_to_end_through_inspect_project(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "c" / "d"
    nested.mkdir(parents=True)
    (nested / "deep.txt").write_text("deep\n")
    intake = inspect_project(tmp_path, max_depth=1)
    assert intake.traversal_stats.depth_limit_reached
    # The end state, asserted rather than described. `inspect.api` passes
    # `stats` into `assess_readiness`, so a depth limit — which travels in no
    # observation and reaches readiness only through `TraversalStats` — has to
    # surface here. Accepting either severity would pass whether or not the
    # call site threads `stats`, which is exactly the failure this test exists
    # to catch.
    completeness = _completeness_finding(intake.readiness_findings)
    assert completeness.severity.value == "high"
    assert "not fully observed" in completeness.message
    assert "depth limit reached" in completeness.message


# ---------------------------------------------------------------------------
# C. Deliberately skipped directories are scoping, not incompleteness
# ---------------------------------------------------------------------------


def test_ignored_directory_only_skip_does_not_report_incompleteness() -> None:
    stats = _stats(entries_skipped=3, entries_skipped_ignored_dir=3)
    findings = assess_readiness(Path("."), _BASE_OBSERVATIONS, [], stats=stats)
    completeness = _completeness_finding(findings)
    assert "not fully observed" not in completeness.message
    assert completeness.severity.value == "low"
    assert "entries_skipped_ignored_dir=3" in completeness.message


def test_ignored_directory_only_skip_end_to_end_via_git_dir(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("hello\n")
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n")
    intake = inspect_project(tmp_path)
    assert intake.traversal_stats.entries_skipped_ignored_dir >= 1
    assert intake.traversal_stats.entries_skipped_refused == 0
    assert intake.traversal_stats.entries_unobservable == 0
    completeness = _completeness_finding(intake.readiness_findings)
    assert "not fully observed" not in completeness.message


def test_ignored_directory_skip_qualifies_a_resolved_absence_claim() -> None:
    # A resolved "none observed" claim (e.g. no test entrypoints) must say
    # explicitly that directories were skipped, not read as universal.
    stats = _stats(entries_skipped=2, entries_skipped_ignored_dir=2)
    findings = assess_readiness(Path("."), _BASE_OBSERVATIONS, [], stats=stats)
    testability = [f for f in findings if f.dimension == "testability"][0]
    assert "No test entrypoints observed" in testability.message
    assert "entries_skipped_ignored_dir=2" in testability.message


def _owner_excluded(path: str) -> ProjectObservation:
    """The observation `collect_nested_project_observations` emits for an
    owner-declared exclusion: DECLARED provenance, boundary-prefixed content."""
    return ProjectObservation(
        subject="nested-project",
        content=(
            f"nested project boundary: {path} is excluded by owner declaration; "
            "its contents are not evidence about this project"
        ),
        provenance=Provenance(kind=ProvenanceKind.DECLARED, source_ref=path),
    )


def test_owner_declared_nested_exclusion_qualifies_a_resolved_absence_claim() -> None:
    """SUE-580 S3. The other exclusion class, scoped the same way.

    ``_scope_absence`` scoped a skipped directory but not an owner-declared
    nested-project exclusion, even though both remove ground from the evidence
    with the same effect on a "none observed" claim — and an owner may exclude
    an arbitrary *markerless* directory. Unscoped, a reader of
    ``runtime-isolation`` alone is told no deploy surface exists in a repository
    whose only Dockerfile sits inside the excluded subtree.
    """
    observations = _BASE_OBSERVATIONS + [
        _owner_excluded("src"),
        # An override *decision* shares the `nested-project` subject but does not
        # name a boundary; a rejected one names a path that is not excluded at
        # all, so it must never be reported as scope.
        _observation(
            "nested-project",
            "override exclude on vendor: not applied — not an excluded "
            "nested-project boundary; override has no effect",
            source_ref="vendor",
        ),
    ]
    findings = assess_readiness(Path("."), observations, [], stats=_stats())
    isolation = [f for f in findings if f.dimension == "runtime-isolation"][0]
    assert isolation.message.startswith("No deploy/runtime surfaces observed"), isolation.message
    assert "nested project boundaries: src" in isolation.message, isolation.message
    assert "vendor" not in isolation.message, (
        "a rejected override names a path that was never excluded; scoping a "
        f"claim by it would be a second false statement: {isolation.message!r}"
    )


def test_manifest_detected_nested_project_scopes_an_absence_claim_too() -> None:
    """This test previously pinned the opposite, and the assertion it pinned was wrong.

    It used to assert that a manifest-detected boundary leaves the absence
    message untouched — the deliberate asymmetry, asserted rather than left to
    chance. The argument was that a subtree carrying its own project manifest is
    a *different project*, so its contents were never candidates for a claim
    about this one, and naming it would add nothing.

    Three things falsify that, so the assertion is inverted here rather than
    deleted:

    1. ``_scope_absence`` does not stay silent — it *enumerates* the exclusions
       that shaped the claim. A reader handed a list reads it as the list, so
       naming ``.git`` while suppressing a nested boundary is worse than naming
       neither.
    2. "Different project" is Foundry's own inference from a subdirectory
       manifest, not the owner's assertion. In a uv/poetry-style workspace
       (``[tool.uv.workspace] members = ["packages/*"]``) the inference is
       false — the root manifest is the owner saying these are one project —
       and the repository published "no deploy surface" over a tree containing
       ``packages/api/Dockerfile``. The owner-declared half, which already
       scoped, is the half where a human actually asserted the exclusion.
    3. ``vendor`` and ``node_modules`` are "not this project" by identical
       reasoning and are scoped. There is no principled line between them.

    So the scope note is now emitted for both kinds of boundary.
    """
    observations = _BASE_OBSERVATIONS + [
        _observation(
            "nested-project",
            "nested project boundary: components/other declares its own project "
            "manifest; its contents are not evidence about this project",
            source_ref="components/other",
        ),
    ]
    findings = assess_readiness(Path("."), observations, [], stats=_stats())
    isolation = [f for f in findings if f.dimension == "runtime-isolation"][0]
    assert isolation.message == (
        "No deploy/runtime surfaces observed in repository inventory "
        "(outside nested project boundaries: components/other)"
    )


def test_a_path_that_merely_spells_cursor_is_not_an_instruction_surface() -> None:
    """A false positive at OBSERVED 1.0 is the same defect class as a false absence.

    ``fragmented-agent-rule-surfaces`` used to be decided by substring-scanning
    the ``source_ref`` of *every* observation for ``AGENTS`` / ``CLAUDE`` /
    ``.cursor``. A ``source_ref`` is not an assertion that a surface is there —
    it is not even an assertion that the path exists. A **rejected**
    ``nested-project`` override decision carries the path of a directory the
    walk has just determined does not exist, so "this path does not exist" was
    republished as "a surface was OBSERVED here" at confidence 1.0, in a
    repository with zero instruction surfaces of any kind.

    The surface is now read off the ``agent-instruction-surface`` subject, which
    is the only record that a collector actually observed one — the same key
    ``profile/synth.py`` uses for ``instruction.fragmentation``, so the two can
    no longer publish contradictory facts from one intake.
    """
    observations = _BASE_OBSERVATIONS + [
        _observation(
            "nested-project",
            "override exclude on .cursor/rules: not applied — override path does "
            "not exist as a directory in this repository",
            source_ref=".cursor/rules",
        ),
        _observation(
            "nested-project",
            "override exclude on components/CLAUDE-service: not applied — override "
            "path does not exist as a directory in this repository",
            source_ref="components/CLAUDE-service",
        ),
    ]
    findings = assess_readiness(Path("."), observations, [], stats=_stats())
    fragmentation = [f for f in findings if f.dimension == "fragmented-agent-rule-surfaces"][0]
    assert fragmentation.message.startswith("No agent instruction surfaces observed"), (
        "no collector observed an instruction surface, so none may be reported: "
        f"{fragmentation.message!r} at confidence {fragmentation.provenance.confidence}"
    )
    assert fragmentation.provenance.kind is not ProvenanceKind.OBSERVED


def test_instruction_surfaces_are_counted_from_the_subject_not_stray_source_refs() -> None:
    """Removing a surface must remove it from the count.

    Under the substring scan, an owner who excluded ``.cursor`` still saw
    ``.cursor/rules/note.md`` counted as a live surface, because the excluded
    path survived in some *other* observation's ``source_ref`` — so Foundry went
    on reporting fragmentation across a surface that was no longer evidence.
    """
    surface = _observation("agent-instruction-surface", "agent rules", source_ref="AGENTS.md")
    stray = _observation(
        "nested-project",
        "nested project boundary: .cursor is excluded by owner declaration; its "
        "contents are not evidence about this project",
        source_ref=".cursor",
    )
    findings = assess_readiness(Path("."), _BASE_OBSERVATIONS + [surface, stray], [], stats=_stats())
    fragmentation = [f for f in findings if f.dimension == "fragmented-agent-rule-surfaces"][0]
    assert fragmentation.message == "Single agent instruction surface observed", (
        fragmentation.message
    )
    assert fragmentation.provenance.source_ref == "AGENTS.md"


def test_two_observed_surfaces_still_report_fragmentation() -> None:
    """The finding must still fire on the evidence it is actually for."""
    observations = _BASE_OBSERVATIONS + [
        _observation("agent-instruction-surface", "agent rules", source_ref="AGENTS.md"),
        _observation("agent-instruction-surface", "cursor rules", source_ref=".cursor/rules/a.md"),
    ]
    findings = assess_readiness(Path("."), observations, [], stats=_stats())
    fragmentation = [f for f in findings if f.dimension == "fragmented-agent-rule-surfaces"][0]
    assert "must not be treated as normative" in fragmentation.message
    assert fragmentation.provenance.kind is ProvenanceKind.OBSERVED
    assert fragmentation.provenance.source_ref == ".cursor/rules/a.md"


def test_both_exclusion_classes_are_named_when_both_apply() -> None:
    """Skipped directories and owner exclusions are independent scopes."""
    observations = _BASE_OBSERVATIONS + [_owner_excluded("vendor/app")]
    stats = _stats(entries_skipped=2, entries_skipped_ignored_dir=2)
    findings = assess_readiness(Path("."), observations, [], stats=stats)
    testability = [f for f in findings if f.dimension == "testability"][0]
    assert "entries_skipped_ignored_dir=2" in testability.message, testability.message
    assert "nested project boundaries: vendor/app" in testability.message, testability.message


# ---------------------------------------------------------------------------
# D. Absence is never asserted over unobserved ground
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "make_stats",
    [
        lambda: _stats(depth_limit_reached=True),
        lambda: _stats(entry_limit_reached=True),
        lambda: _stats(entries_skipped_refused=1),
    ],
)
def test_no_absence_claim_asserted_when_walk_incomplete(make_stats) -> None:
    stats = make_stats()
    findings = assess_readiness(Path("."), _BASE_OBSERVATIONS, [], stats=stats)
    for message in _absence_messages(findings):
        assert "No " not in message, message
        assert "not confirmed" in message
        assert "not fully observed" in message


#: Readiness dimensions whose absence claim depends on what is *inside* a file,
#: from the per-dimension audit in ``readiness.py``'s module docstring. Only
#: ``testability`` qualifies: ``test-entrypoint`` is emitted both by marker
#: filenames and by a ``test:`` target parsed out of the Makefile's bytes
#: (``_MAKEFILE_TARGET_SUBJECTS`` in ``inspect/collectors.py``), which is why
#: ``profile/synth.py`` classifies that same subject as
#: ``_SubjectDerivation.CONTENT``. Every other absence-shaped dimension is
#: settled by the entry list alone.
_CONTENT_DERIVED_DIMENSIONS = frozenset({"testability"})


def test_content_only_hole_still_allows_a_filename_derived_absence_claim() -> None:
    # SUE-580 S2: a size-skipped file is a *content* hole, not a *path* hole —
    # the walk saw the entry and knows its name; it only declined to read its
    # bytes. A dimension derived purely from filename/path presence (deploy
    # markers, integration-config filenames, package-metadata filenames,
    # agent-instruction-surface paths) must not be made uncertain by it:
    # a resolved "No ... observed" claim still stands.
    observations = _BASE_OBSERVATIONS + [_observation("file-read-skipped", "big file")]
    findings = assess_readiness(Path("."), observations, [], stats=_stats())
    checked = [
        f
        for f in findings
        if f.dimension in _absence_shaped_dimensions()
        and f.dimension not in _CONTENT_DERIVED_DIMENSIONS
    ]
    assert checked, "expected at least one filename-derived absence dimension to check"
    for finding in checked:
        assert finding.message.startswith("No "), finding.message
        assert "not confirmed" not in finding.message, finding.message


def test_content_only_hole_withholds_a_content_derived_absence_claim() -> None:
    """SUE-580 B1. The defect this replaces was encoded by the test above.

    The previous version of ``test_absence_claim_still_asserted_for_content_only_hole``
    asserted that *every* absence-shaped dimension keeps its confident "No ..."
    claim over a content hole, ``testability`` included — pinning the bug rather
    than catching it. That was wrong for exactly one dimension: ``has_tests``
    reads the ``test-entrypoint`` subject, which ``collectors.py`` also emits
    from a ``test:`` target parsed out of the Makefile's *bytes*. With the
    Makefile unread, "No test entrypoints observed" at MEDIUM/0.7 is a confident
    false negative over evidence the walk never looked at — and the profile,
    which classifies the same subject as CONTENT, got it right in the same run.

    Splitting the two claims apart is the fix; asserting both halves in separate
    tests is what keeps either half from being weakened silently.
    """
    observations = _BASE_OBSERVATIONS + [_observation("file-read-skipped", "big file")]
    findings = assess_readiness(Path("."), observations, [], stats=_stats())
    for dimension in _CONTENT_DERIVED_DIMENSIONS:
        finding = next(f for f in findings if f.dimension == dimension)
        assert not finding.message.startswith("No "), (
            f"{dimension} is derived from file content; it must not publish a "
            f"confident absence over an unread file: {finding.message!r}"
        )
        assert "not confirmed" in finding.message, finding.message
        assert "not fully observed" in finding.message, finding.message
        assert "read-size limit" in finding.message, (
            "the withheld claim must name the content hole that caused it, not "
            f"an empty hole list: {finding.message!r}"
        )
        assert finding.provenance.confidence == 0.0, finding.provenance.confidence


def test_completeness_summary_does_not_vouch_for_more_than_the_report_does() -> None:
    """SUE-580 B1, second half. The summary certified a claim it did not cover.

    With only a content hole, the old summary said "Findings elsewhere in this
    report that would otherwise read as confirmed absence are withheld or
    explicitly qualified instead" — flatly false about the confident
    ``testability`` negative sitting next to it, and still an overstatement now
    that ``testability`` is withheld, because the filename-derived findings
    beside it are *not* withheld and correctly still stand. The summary has to
    say which half it means.
    """
    observations = _BASE_OBSERVATIONS + [_observation("file-read-skipped", "big file")]
    findings = assess_readiness(Path("."), observations, [], stats=_stats())
    summary = _completeness_finding(findings).message
    assert "Content-derived findings" in summary, summary
    assert "filename-derived findings still stand" in summary, summary

    # A path hole withholds every absence claim, so there the unqualified
    # sentence is the true one.
    path_hole = assess_readiness(
        Path("."), _BASE_OBSERVATIONS, [], stats=_stats(depth_limit_reached=True)
    )
    path_summary = _completeness_finding(path_hole).message
    assert "Findings elsewhere in this report" in path_summary, path_summary
    assert "Content-derived findings" not in path_summary, path_summary


def test_absence_claim_only_made_when_exhaustive_and_reads_as_confident() -> None:
    findings = assess_readiness(Path("."), _BASE_OBSERVATIONS, [], stats=_stats())
    testability = [f for f in findings if f.dimension == "testability"][0]
    assert testability.message == "No test entrypoints observed"
    assert testability.provenance.confidence == 0.7


# ---------------------------------------------------------------------------
# E. Determinism
# ---------------------------------------------------------------------------


def test_readiness_output_is_byte_stable_for_incomplete_walk() -> None:
    stats = _stats(depth_limit_reached=True, entries_skipped_refused=1)
    observations = _BASE_OBSERVATIONS + [_observation("path-unobservable", "y")]
    first = assess_readiness(Path("."), observations, [], stats=stats)
    second = assess_readiness(Path("."), observations, [], stats=stats)
    assert [f.model_dump() for f in first] == [f.model_dump() for f in second]


def test_readiness_output_deterministic_across_pythonhashseed(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("hello\n")
    (tmp_path / "big.bin").write_bytes(b"x" * 5000)
    script = (
        "import sys; sys.path.insert(0, %r)\n"
        "from agent_foundry.inspect import inspect_project\n"
        "from agent_foundry.models import dump_json\n"
        "print(dump_json(inspect_project(%r, max_file_bytes=10)))\n"
    ) % (str(REPO_ROOT / "src"), str(tmp_path))

    def _run(seed: str) -> str:
        env = {**os.environ, "PYTHONHASHSEED": seed}
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        return result.stdout

    first = _run("1")
    second = _run("2")
    assert first == second
    assert first.strip()
