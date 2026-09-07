"""Absence-derived classification findings: the producer/consumer contract.

`propose_classification_findings` can only see the entries it was handed — it has
no access to the walk's own accounting, so it cannot know whether the region that
would hold a signal was ever reached. It therefore *marks* the findings it derives
from absence (`ABSENCE_ENUMERATION_REASON_PREFIXES`), and the consumer that does
hold `TraversalStats` (`profile.synth`) gates them.

These tests pin both halves: that the producer's reason really starts with a
declared prefix, and that an entry-limited walk over a repository with CI, a
Dockerfile and 30 source files never publishes `intake_mode = greenfield`.
"""

from __future__ import annotations

from pathlib import Path

from agent_foundry.inspect import inspect_project
from agent_foundry.inspect.classification import (
    ABSENCE_ENUMERATION_REASON_PREFIXES,
    reason_is_absence_enumeration,
)
from agent_foundry.models import ProfileResolution
from agent_foundry.profile import synthesize_project_profile


def _build_padded_brownfield_repo(root: Path, *, padding: int = 300) -> None:
    """A brownfield repository whose brownfield signals sort *after* a large
    directory: `.aaa/` alone can exhaust a low entry limit."""
    (root / ".aaa").mkdir(parents=True)
    for index in range(padding):
        (root / ".aaa" / f"pad{index}.txt").write_text("x\n", encoding="utf-8")
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / ".github" / "workflows" / "ci.yml").write_text("name: ci\non: push\n", encoding="utf-8")
    (root / "Dockerfile").write_text("FROM python:3.12\n", encoding="utf-8")
    (root / "src").mkdir()
    for index in range(30):
        (root / "src" / f"mod{index}.py").write_text("x = 1\n", encoding="utf-8")


def _intake_mode_dimension(intake):
    profile = synthesize_project_profile(intake)
    return next(d for d in profile.dimensions if d.dimension == "intake_mode")


def test_greenfield_from_silence_reason_carries_a_declared_absence_prefix(tmp_path: Path) -> None:
    """The producer marks its own absence-derived reason, so the consumer never has
    to pattern-match prose it does not own."""
    repo = tmp_path / "empty-repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "notes.md").write_text("hello\n", encoding="utf-8")

    intake = inspect_project(repo)
    finding = next(f for f in intake.classification_findings if f.dimension == "intake_mode")
    assert finding.value == "greenfield"
    assert reason_is_absence_enumeration(finding.reason), (
        f"reason {finding.reason!r} is an enumeration of absent signals but does not "
        f"start with any of {ABSENCE_ENUMERATION_REASON_PREFIXES}"
    )


def test_a_positively_evidenced_brownfield_reason_is_not_marked_as_absence(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _build_padded_brownfield_repo(repo, padding=5)
    intake = inspect_project(repo)
    finding = next(f for f in intake.classification_findings if f.dimension == "intake_mode")
    assert finding.value == "brownfield"
    assert not reason_is_absence_enumeration(finding.reason)


def test_entry_limited_walk_does_not_report_a_running_service_as_greenfield(tmp_path: Path) -> None:
    """The blocker reproduction: same repository, two entry limits.

    Fully walked it is brownfield on four signals. Walked with an entry limit that
    the padding directory exhausts first, the classifier sees none of those signals
    and proposes `greenfield` with a reason enumerating everything it "checked" —
    the most confident possible phrasing of a fact never observed. The profile must
    report UNKNOWN there, not a confident negative.
    """
    repo = tmp_path / "repo"
    _build_padded_brownfield_repo(repo)

    full = inspect_project(repo, max_entries=2000)
    assert full.traversal_stats.entry_limit_reached is False
    full_dim = _intake_mode_dimension(full)
    assert full_dim.resolution is ProfileResolution.RESOLVED
    assert full_dim.attributions[0].value == "brownfield"

    truncated = inspect_project(repo, max_entries=60)
    assert truncated.traversal_stats.entry_limit_reached is True
    # The classifier still proposes greenfield — it cannot know what it missed.
    proposed = next(f for f in truncated.classification_findings if f.dimension == "intake_mode")
    assert proposed.value == "greenfield"
    # ...but the profile, which does know, must not publish it.
    truncated_dim = _intake_mode_dimension(truncated)
    assert truncated_dim.resolution is ProfileResolution.UNKNOWN, (
        "intake_mode resolved to "
        f"{[a.value for a in truncated_dim.attributions]} over a walk that stopped at "
        "its entry limit before reaching the CI workflow, Dockerfile and source tree"
    )
    assert truncated_dim.attributions == []
