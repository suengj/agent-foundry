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


def _absence_messages(findings) -> list[str]:
    """Every message from a dimension that has a "found vs not found" shape."""
    absence_dims = {
        "reproducibility",
        "testability",
        "authority-ownership-clarity",
        "runtime-isolation",
        "credential-permission-isolation",
        "fragmented-agent-rule-surfaces",
    }
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


def test_no_absence_claim_asserted_for_unread_file_hole() -> None:
    observations = _BASE_OBSERVATIONS + [_observation("file-read-skipped", "big file")]
    findings = assess_readiness(Path("."), observations, [], stats=_stats())
    for message in _absence_messages(findings):
        assert "No " not in message, message


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
