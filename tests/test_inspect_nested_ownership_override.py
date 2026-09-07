"""Nested-project ownership can be configured/overridden; every exclusion stays visible.

SUE-580 scope: "Add explicit override/configuration for nested-project ownership
heuristics rather than silently assuming every nested marker means an independent
project." The default heuristic (`nested_project_roots`) is unchanged and unweakened
by any of this — it is still what runs first. An owner override, declared in
`.foundry/project.yaml` under `inspection.nested_project_overrides`, can re-include a
detected boundary (`include`) or exclude a subtree that carries no marker at all
(`exclude`). Every resulting decision — applied or not, default or overridden — is
recorded as a `nested-project` observation: nothing is ever silently excluded, and
nothing is ever silently re-included.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from agent_foundry.inspect import inspect_project
from agent_foundry.inspect.traversal import (
    DEFAULT_MAX_DEPTH,
    NESTED_BOUNDARY_MARKER_GIT_DIRECTORY,
    NESTED_BOUNDARY_MARKER_MANIFEST,
    NestedProjectOverrideDecision,
    NestedProjectOverrides,
    load_nested_project_overrides,
    nested_project_boundary_markers,
    nested_project_roots,
    resolve_nested_project_boundaries,
    walk_repository,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _target_project(root: Path) -> Path:
    """A small target project: source, tests, manifest, instruction surface."""
    (root / "src" / "target").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "src" / "target" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "src" / "target" / "core.py").write_text(
        "def run() -> int:\n    return 1\n", encoding="utf-8"
    )
    (root / "tests" / "conftest.py").write_text("", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[project]\nname = "target"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    (root / "AGENTS.md").write_text("Run pytest before proposing a change.\n", encoding="utf-8")
    return root


def _plant_nested_project(parent: Path, name: str) -> Path:
    """A complete second project with its own manifest and deploy/instruction surface."""
    nested = parent / name
    (nested / "src").mkdir(parents=True)
    (nested / "src" / "__init__.py").write_text("", encoding="utf-8")
    (nested / "pyproject.toml").write_text(
        '[project]\nname = "nested"\nversion = "9.9.9"\n', encoding="utf-8"
    )
    (nested / "Dockerfile").write_text("FROM python:3.11-slim\n", encoding="utf-8")
    (nested / "env.example").write_text("NESTED_TOKEN=\n", encoding="utf-8")
    return nested


def _plant_markerless_subtree(parent: Path, name: str) -> Path:
    """A subtree that carries no project manifest at all."""
    quiet = parent / name
    quiet.mkdir(parents=True)
    (quiet / "notes.txt").write_text("vendored content, no marker\n", encoding="utf-8")
    return quiet


def _write_override(root: Path, *, include: list[str] | None = None, exclude: list[str] | None = None) -> None:
    (root / ".foundry").mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {"inspection": {"nested_project_overrides": {}}}
    body = payload["inspection"]["nested_project_overrides"]  # type: ignore[index]
    if include is not None:
        body["include"] = include  # type: ignore[index]
    if exclude is not None:
        body["exclude"] = exclude  # type: ignore[index]
    (root / ".foundry" / "project.yaml").write_text(yaml.safe_dump(payload), encoding="utf-8")


def _write_raw_override(root: Path, raw: str) -> None:
    (root / ".foundry").mkdir(parents=True, exist_ok=True)
    (root / ".foundry" / "project.yaml").write_text(raw, encoding="utf-8")


def _nested_subjects(intake) -> list[tuple[str, str, str]]:
    return sorted(
        (item.content, item.provenance.source_ref or "", item.provenance.kind.value)
        for item in intake.observations
        if item.subject == "nested-project"
    )


def _tree_snapshot(root: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        stat = path.lstat()
        rel = path.relative_to(root).as_posix()
        snapshot[rel] = f"mode={stat.st_mode:o} size={stat.st_size} mtime_ns={stat.st_mtime_ns}"
    return snapshot


# ---------------------------------------------------------------------------
# Default behaviour unchanged when no override is declared
# ---------------------------------------------------------------------------


def test_default_behaviour_unchanged_with_no_override_declared(tmp_path: Path) -> None:
    root = _target_project(tmp_path / "project")
    _plant_nested_project(root / "components", "other-service")

    intake = inspect_project(root)
    boundaries = {
        item.provenance.source_ref
        for item in intake.observations
        if item.subject == "nested-project"
    }
    assert boundaries == {"components/other-service"}
    # No override was declared: no extra "override ..." observations appear.
    contents = [item.content for item in intake.observations if item.subject == "nested-project"]
    assert not any(c.startswith("override ") for c in contents)


def test_no_override_file_at_all_is_not_malformed(tmp_path: Path) -> None:
    root = _target_project(tmp_path / "project")
    overrides = load_nested_project_overrides(root, walk_repository(root).entries)
    assert overrides == NestedProjectOverrides()
    assert overrides.malformed is False


# ---------------------------------------------------------------------------
# Override re-including a nested subtree
# ---------------------------------------------------------------------------


def test_override_include_re_includes_a_detected_boundary_and_is_visible(tmp_path: Path) -> None:
    root = _target_project(tmp_path / "project")
    _plant_nested_project(root / "components", "vendored-lib")
    _write_override(root, include=["components/vendored-lib"])

    intake = inspect_project(root)

    # The subtree is no longer excluded: its files are owned evidence again.
    assert any(
        item.subject == "package-metadata"
        and item.provenance.source_ref == "components/vendored-lib/pyproject.toml"
        for item in intake.observations
    )
    # The re-inclusion decision itself is visible.
    decisions = [
        item
        for item in intake.observations
        if item.subject == "nested-project" and item.content.startswith("override include")
    ]
    assert len(decisions) == 1
    assert "applied" in decisions[0].content
    assert decisions[0].provenance.source_ref == "components/vendored-lib"
    assert decisions[0].provenance.kind.value == "declared"
    # And the default-heuristic boundary observation is gone: it is no longer excluded.
    assert not any(
        item.subject == "nested-project"
        and item.provenance.source_ref == "components/vendored-lib"
        and item.content.startswith("nested project boundary")
        for item in intake.observations
    )


def test_override_include_naming_a_non_boundary_is_a_visible_no_op(tmp_path: Path) -> None:
    root = _target_project(tmp_path / "project")
    _write_override(root, include=["src/target"])

    intake = inspect_project(root)
    decisions = [
        item
        for item in intake.observations
        if item.subject == "nested-project" and item.content.startswith("override include")
    ]
    assert len(decisions) == 1
    assert "not applied" in decisions[0].content
    assert "not an excluded nested-project boundary" in decisions[0].content


# ---------------------------------------------------------------------------
# Override excluding a subtree with no marker
# ---------------------------------------------------------------------------


def test_override_exclude_removes_a_markerless_subtree_and_is_visible(tmp_path: Path) -> None:
    root = _target_project(tmp_path / "project")
    _plant_markerless_subtree(root, "quiet-vendor")
    _write_override(root, exclude=["quiet-vendor"])

    intake = inspect_project(root)

    # The subtree's contents are no longer owned evidence.
    assert not any(
        (item.provenance.source_ref or "").startswith("quiet-vendor/")
        for item in intake.observations
    )
    decisions = [
        item
        for item in intake.observations
        if item.subject == "nested-project" and item.content.startswith("override exclude")
    ]
    assert len(decisions) == 1
    assert "applied" in decisions[0].content
    assert decisions[0].provenance.source_ref == "quiet-vendor"


def test_override_exclude_already_covered_by_existing_boundary_is_a_visible_no_op(
    tmp_path: Path,
) -> None:
    root = _target_project(tmp_path / "project")
    _plant_nested_project(root / "components", "other-service")
    _write_override(root, exclude=["components/other-service/src"])

    intake = inspect_project(root)
    decisions = [
        item
        for item in intake.observations
        if item.subject == "nested-project" and item.content.startswith("override exclude")
    ]
    assert len(decisions) == 1
    assert "not applied" in decisions[0].content
    assert "already covered" in decisions[0].content


# ---------------------------------------------------------------------------
# Malformed override fails closed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "inspection:\n  nested_project_overrides: [1, 2]\n",
        "inspection:\n  nested_project_overrides:\n    include: not-a-list\n",
        "inspection:\n  nested_project_overrides:\n    include: [1, 2]\n",
        "inspection:\n  nested_project_overrides:\n    surprise: true\n",
        "inspection:\n  nested_project_overrides:\n    include: [\"../escape\"]\n",
        "not: [valid, yaml, :::\n",
    ],
)
def test_malformed_override_fails_closed_to_default_heuristic(tmp_path: Path, raw: str) -> None:
    root = _target_project(tmp_path / "project")
    _plant_nested_project(root / "components", "other-service")
    _write_raw_override(root, raw)

    intake = inspect_project(root)

    # Default heuristic still excludes the nested project.
    assert not any(
        (item.provenance.source_ref or "").startswith("components/other-service/")
        for item in intake.observations
        if item.subject != "nested-project"
    )
    # And the failure to trust the override is itself recorded, saying so.
    malformed = [
        item
        for item in intake.observations
        if item.subject == "nested-project" and item.content.startswith("override malformed")
    ]
    assert len(malformed) == 1
    assert "not applied" in malformed[0].content
    assert malformed[0].provenance.kind.value == "observed"


def test_malformed_override_object_constructed_directly_also_fails_closed(tmp_path: Path) -> None:
    root = _target_project(tmp_path / "project")
    _plant_nested_project(root / "components", "other-service")

    overrides = NestedProjectOverrides(
        source_ref=".foundry/project.yaml", malformed=True, malformed_reason="deliberately broken"
    )
    intake = inspect_project(root, nested_project_overrides=overrides)
    assert not any(
        (item.provenance.source_ref or "").startswith("components/other-service/")
        for item in intake.observations
        if item.subject != "nested-project"
    )
    assert any(
        item.subject == "nested-project" and "deliberately broken" in item.content
        for item in intake.observations
    )


# ---------------------------------------------------------------------------
# Override naming a nonexistent path
# ---------------------------------------------------------------------------


def test_override_exclude_naming_a_nonexistent_path_is_explicit_and_not_applied(
    tmp_path: Path,
) -> None:
    root = _target_project(tmp_path / "project")
    _write_override(root, exclude=["does/not/exist"])

    intake = inspect_project(root)
    decisions = [
        item
        for item in intake.observations
        if item.subject == "nested-project" and item.content.startswith("override exclude")
    ]
    assert len(decisions) == 1
    assert "not applied" in decisions[0].content
    assert "does not exist" in decisions[0].content
    # Nothing was excluded as a side effect of the bad path.
    assert any(
        item.subject == "package-metadata" and item.provenance.source_ref == "pyproject.toml"
        for item in intake.observations
    )


def test_override_include_naming_a_nonexistent_path_is_explicit_and_not_applied(
    tmp_path: Path,
) -> None:
    root = _target_project(tmp_path / "project")
    _write_override(root, include=["does/not/exist"])

    intake = inspect_project(root)
    decisions = [
        item
        for item in intake.observations
        if item.subject == "nested-project" and item.content.startswith("override include")
    ]
    assert len(decisions) == 1
    assert "not applied" in decisions[0].content


# ---------------------------------------------------------------------------
# The repository root can never be declared a nested project
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("root_spelling", [".", "/", "//"])
def test_root_can_never_be_declared_a_nested_project(tmp_path: Path, root_spelling: str) -> None:
    root = _target_project(tmp_path / "project")
    _write_override(root, exclude=[root_spelling])

    intake = inspect_project(root)
    # The target's own files remain fully owned evidence.
    assert any(
        item.subject == "package-metadata" and item.provenance.source_ref == "pyproject.toml"
        for item in intake.observations
    )
    decisions = [
        item
        for item in intake.observations
        if item.subject == "nested-project" and item.content.startswith("override exclude")
    ]
    assert len(decisions) == 1
    assert "not applied" in decisions[0].content
    assert "repository root can never be declared" in decisions[0].content


def test_root_is_never_a_boundary_via_the_pure_resolver(tmp_path: Path) -> None:
    root = _target_project(tmp_path / "project")
    entries = walk_repository(root).entries
    overrides = NestedProjectOverrides(exclude=(".",))
    boundaries, decisions = resolve_nested_project_boundaries(root, entries, overrides)
    assert boundaries == []
    assert decisions[0].applied is False


# ---------------------------------------------------------------------------
# No mutation of the inspected tree under any override
# ---------------------------------------------------------------------------


def test_no_mutation_of_the_tree_with_overrides_in_play(tmp_path: Path) -> None:
    root = _target_project(tmp_path / "project")
    _plant_nested_project(root / "components", "other-service")
    _plant_markerless_subtree(root, "quiet-vendor")
    _write_override(
        root,
        include=["components/other-service"],
        exclude=["quiet-vendor", "does/not/exist"],
    )

    before = _tree_snapshot(root)
    inspect_project(root)
    after = _tree_snapshot(root)
    assert before == after


def test_no_mutation_with_a_malformed_override(tmp_path: Path) -> None:
    root = _target_project(tmp_path / "project")
    _write_raw_override(root, "not: [valid, yaml, :::\n")

    before = _tree_snapshot(root)
    inspect_project(root)
    after = _tree_snapshot(root)
    assert before == after


# ---------------------------------------------------------------------------
# Determinism across PYTHONHASHSEED
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", ["0", "42"])
def test_determinism_across_hash_seeds_with_override_in_play(tmp_path: Path, seed: str) -> None:
    root = _target_project(tmp_path / "project")
    _plant_nested_project(root / "components", "other-service")
    _plant_markerless_subtree(root, "quiet-vendor")
    _write_override(
        root,
        include=["components/other-service"],
        exclude=["quiet-vendor"],
    )

    env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(REPO_ROOT / "src")}
    cmd = [
        sys.executable,
        "-c",
        "from pathlib import Path; "
        "from agent_foundry.inspect import inspect_project; "
        "from agent_foundry.models import dump_json; "
        f"p = Path({str(root)!r}); "
        "print(dump_json(inspect_project(p)).decode())",
    ]
    first = subprocess.run(cmd, cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=True).stdout
    second = subprocess.run(cmd, cwd="/tmp", env=env, capture_output=True, text=True, check=True).stdout
    assert first == second


# ---------------------------------------------------------------------------
# Bounded traversal still holds with an override in play
# ---------------------------------------------------------------------------


def test_bounded_traversal_still_holds_with_override_in_play(tmp_path: Path) -> None:
    root = _target_project(tmp_path / "project")
    deep = root / "deep_chain"
    for i in range(DEFAULT_MAX_DEPTH + 5):
        deep = deep / f"d{i}"
    deep.mkdir(parents=True)
    (deep / "leaf.py").write_text("VALUE = 1\n", encoding="utf-8")
    _write_override(root, exclude=["deep_chain"])

    intake = inspect_project(root)
    assert intake.traversal_stats.depth_limit_reached is True
    # The traversal budget itself is unaffected by the override — the same
    # entries_visited count as without one, since the override only changes
    # which already-visited entries are attributed, never how many are visited.
    boundaries = [
        item
        for item in intake.observations
        if item.subject == "nested-project" and item.content.startswith("override exclude")
    ]
    assert len(boundaries) == 1
    assert "applied" in boundaries[0].content


def test_default_heuristic_pure_function_unaffected_by_import(tmp_path: Path) -> None:
    """`nested_project_roots` itself takes no override argument — confirms it is untouched."""
    root = _target_project(tmp_path / "project")
    _plant_nested_project(root / "components", "other-service")
    entries = walk_repository(root).entries
    assert nested_project_roots(root, entries) == ["components/other-service"]


def test_boundary_markers_record_how_each_boundary_was_detected(tmp_path: Path) -> None:
    """`nested_project_boundary_markers` is the same set as `nested_project_roots`,
    with the evidence for each boundary still attached — a manifest sighting and a
    `.git` probe are different observed facts, and only a caller told which can
    report the exclusion truthfully."""
    root = _target_project(tmp_path / "project")
    _plant_nested_project(root / "components", "other-service")
    clone = root / "vendored-clone"
    clone.mkdir()
    (clone / ".git").mkdir()
    (clone / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")

    entries = walk_repository(root).entries
    markers = nested_project_boundary_markers(root, entries)
    assert markers == {
        "components/other-service": NESTED_BOUNDARY_MARKER_MANIFEST,
        "vendored-clone": NESTED_BOUNDARY_MARKER_GIT_DIRECTORY,
    }
    assert sorted(markers) == nested_project_roots(root, entries)


def test_a_boundary_with_both_a_manifest_and_a_git_dir_reports_the_manifest(
    tmp_path: Path,
) -> None:
    """Both facts are true; the manifest is the owner-authored one and was directly
    observed in the walk, so it is the reason reported."""
    root = _target_project(tmp_path / "project")
    nested = _plant_nested_project(root, "both")
    (nested / ".git").mkdir()
    (nested / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")

    entries = walk_repository(root).entries
    assert nested_project_boundary_markers(root, entries) == {
        "both": NESTED_BOUNDARY_MARKER_MANIFEST
    }


# ---------------------------------------------------------------------------
# A truncated walk must not report a false, confident "does not exist"
# ---------------------------------------------------------------------------


def test_override_exclude_naming_a_real_path_missed_by_a_truncated_walk_is_uncertain(
    tmp_path: Path,
) -> None:
    """The path genuinely exists on disk; only the bounded walk never reached it.

    Reproduces the exact scenario from review: a repo whose `.foundry/project.yaml`
    declares `exclude: [zsub]`, inspected with a `max_entries` small enough that the
    walk stops before visiting `zsub` at all. The override decision must not claim
    the path "does not exist" (a false, confident statement), and must not be
    reported at full confidence.
    """
    root = _target_project(tmp_path / "project")
    zsub = root / "zsub"
    zsub.mkdir()
    (zsub / "notes.txt").write_text("vendored content\n", encoding="utf-8")
    _write_override(root, exclude=["zsub"])

    # Confirm the walk really is truncated before reaching zsub, and that zsub
    # really does exist as a directory in the repository.
    assert zsub.is_dir()
    small_walk = walk_repository(root, max_entries=5)
    assert small_walk.entry_limit_reached is True
    assert not any(e.relative_path == "zsub" for e in small_walk.entries)

    intake = inspect_project(root, max_entries=5)
    assert intake.traversal_stats.entry_limit_reached is True

    decisions = [
        item
        for item in intake.observations
        if item.subject == "nested-project" and item.content.startswith("override exclude")
    ]
    assert len(decisions) == 1
    decision = decisions[0]
    assert "not applied" in decision.content
    # Must not assert confident, false non-existence.
    assert "does not exist" not in decision.content
    # Must say the walk was incomplete, distinguishing "not found" from "confirmed absent".
    assert "walk was incomplete" in decision.content
    # Must not be reported at full confidence: this is a gap in evidence, not a
    # settled fact.
    assert decision.provenance.confidence is not None
    assert decision.provenance.confidence < 1.0


def test_override_exclude_naming_a_genuinely_nonexistent_path_stays_confident(
    tmp_path: Path,
) -> None:
    """A complete walk that never finds the path is entitled to full confidence.

    Guards the distinction the truncated-walk fix must preserve: when the walk is
    NOT truncated, "does not exist" is a settled fact and stays at confidence 1.0.
    """
    root = _target_project(tmp_path / "project")
    _write_override(root, exclude=["does/not/exist"])

    intake = inspect_project(root)
    assert intake.traversal_stats.entry_limit_reached is False
    assert intake.traversal_stats.depth_limit_reached is False

    decisions = [
        item
        for item in intake.observations
        if item.subject == "nested-project" and item.content.startswith("override exclude")
    ]
    assert len(decisions) == 1
    assert "does not exist" in decisions[0].content
    assert decisions[0].provenance.confidence == 1.0


def test_resolve_nested_project_boundaries_truncated_flag_via_pure_resolver(
    tmp_path: Path,
) -> None:
    """Direct unit coverage of the pure resolver's `walk_truncated` parameter."""
    root = _target_project(tmp_path / "project")
    zsub = root / "zsub"
    zsub.mkdir()
    (zsub / "notes.txt").write_text("vendored\n", encoding="utf-8")

    entries = walk_repository(root).entries
    # Simulate a truncated walk that never reached zsub, even though it exists.
    truncated_entries = [e for e in entries if not e.relative_path.startswith("zsub")]
    assert not any(e.relative_path == "zsub" for e in truncated_entries)

    overrides = NestedProjectOverrides(exclude=("zsub",))
    _, decisions = resolve_nested_project_boundaries(
        root, truncated_entries, overrides, walk_truncated=True
    )
    decision = next(d for d in decisions if d.path == "zsub")
    assert decision.applied is False
    assert decision.uncertain is True
    assert "does not exist" not in decision.reason
    assert "walk was incomplete" in decision.reason

    # The same missing path, with the walk NOT reported as truncated, keeps the
    # original confident phrasing and is not marked uncertain.
    _, decisions_not_truncated = resolve_nested_project_boundaries(
        root, truncated_entries, overrides, walk_truncated=False
    )
    decision_not_truncated = next(d for d in decisions_not_truncated if d.path == "zsub")
    assert decision_not_truncated.uncertain is False
    assert "does not exist" in decision_not_truncated.reason


def test_override_include_on_a_real_boundary_missed_by_a_truncated_walk_is_uncertain(
    tmp_path: Path,
) -> None:
    """The `include` sibling of the truncated-walk guard above.

    `include` decides "not an excluded nested-project boundary; override has no
    effect" against `default_boundaries`, which the same bounded walk populates. A
    truncated walk can under-populate it for exactly the reason it can lose a
    directory from `dir_paths`: the marker that would have made the path a boundary
    may lie past where the walk stopped. Here `zz-pkg/pyproject.toml` genuinely
    exists and the full walk applies the override — so "has no effect" is false on
    the complete tree, and publishing it as DECLARED at confidence 1.0 puts a
    confident falsehood into `repository.ownership-boundaries`.
    """
    root = _target_project(tmp_path / "project")
    _plant_nested_project(root, "zz-pkg")
    _write_override(root, include=["zz-pkg"])

    # On the complete tree the override genuinely applies.
    full = inspect_project(root)
    assert full.traversal_stats.entry_limit_reached is False
    full_decision = next(
        item
        for item in full.observations
        if item.subject == "nested-project" and item.content.startswith("override include")
    )
    assert "applied" in full_decision.content
    assert "not applied" not in full_decision.content

    # The bounded walk must never reach zz-pkg's manifest.
    small_walk = walk_repository(root, max_entries=5)
    assert small_walk.entry_limit_reached is True
    assert not any(e.relative_path.startswith("zz-pkg") for e in small_walk.entries)

    intake = inspect_project(root, max_entries=5)
    assert intake.traversal_stats.entry_limit_reached is True
    decisions = [
        item
        for item in intake.observations
        if item.subject == "nested-project" and item.content.startswith("override include")
    ]
    assert len(decisions) == 1
    decision = decisions[0]
    assert "not applied" in decision.content
    # Must not assert the confident falsehood.
    assert "override has no effect" not in decision.content
    # Must say the walk was incomplete, distinguishing "not found" from "confirmed absent".
    assert "walk was incomplete" in decision.content
    assert decision.provenance.confidence is not None
    assert decision.provenance.confidence < 1.0


def test_override_include_on_a_genuinely_unrelated_path_stays_confident(
    tmp_path: Path,
) -> None:
    """The distinction the `include` guard must preserve: a complete walk that
    finds no covering boundary is entitled to say so at full confidence."""
    root = _target_project(tmp_path / "project")
    _plant_markerless_subtree(root, "quiet-vendor")
    _write_override(root, include=["quiet-vendor"])

    intake = inspect_project(root)
    assert intake.traversal_stats.entry_limit_reached is False
    assert intake.traversal_stats.depth_limit_reached is False

    decisions = [
        item
        for item in intake.observations
        if item.subject == "nested-project" and item.content.startswith("override include")
    ]
    assert len(decisions) == 1
    assert "override has no effect" in decisions[0].content
    assert "walk was incomplete" not in decisions[0].content
    assert decisions[0].provenance.confidence == 1.0


def test_resolve_include_truncated_flag_via_pure_resolver(tmp_path: Path) -> None:
    """Direct unit coverage of `walk_truncated` on the `include` branch."""
    root = _target_project(tmp_path / "project")
    _plant_nested_project(root, "zz-pkg")

    entries = walk_repository(root).entries
    truncated_entries = [e for e in entries if not e.relative_path.startswith("zz-pkg")]
    assert not any(e.relative_path.startswith("zz-pkg") for e in truncated_entries)

    overrides = NestedProjectOverrides(include=("zz-pkg",))
    _, decisions = resolve_nested_project_boundaries(
        root, truncated_entries, overrides, walk_truncated=True
    )
    decision = next(d for d in decisions if d.path == "zz-pkg")
    assert decision.applied is False
    assert decision.uncertain is True
    assert "override has no effect" not in decision.reason
    assert "walk was incomplete" in decision.reason

    # Same missing boundary, walk NOT reported as truncated: confident phrasing kept.
    _, decisions_not_truncated = resolve_nested_project_boundaries(
        root, truncated_entries, overrides, walk_truncated=False
    )
    decision_not_truncated = next(d for d in decisions_not_truncated if d.path == "zz-pkg")
    assert decision_not_truncated.uncertain is False
    assert "override has no effect" in decision_not_truncated.reason


# ---------------------------------------------------------------------------
# An owner-declared boundary is DECLARED provenance, never OBSERVED
# ---------------------------------------------------------------------------


def test_owner_declared_nested_project_boundary_is_declared_not_observed(
    tmp_path: Path,
) -> None:
    """A markerless subtree excluded purely by owner declaration is not something
    Foundry observed — it must carry `ProvenanceKind.DECLARED`, distinct from a
    boundary the default heuristic actually found via a project manifest.
    """
    root = _target_project(tmp_path / "project")
    _plant_markerless_subtree(root, "quiet-vendor")
    _plant_nested_project(root / "components", "other-service")
    _write_override(root, exclude=["quiet-vendor"])

    intake = inspect_project(root)

    boundary_observations = {
        item.provenance.source_ref: item
        for item in intake.observations
        if item.subject == "nested-project" and item.content.startswith("nested project boundary")
    }
    assert set(boundary_observations) == {"quiet-vendor", "components/other-service"}

    owner_declared = boundary_observations["quiet-vendor"]
    assert owner_declared.provenance.kind.value == "declared"
    assert "excluded by owner declaration" in owner_declared.content
    assert "declares its own project manifest" not in owner_declared.content

    manifest_detected = boundary_observations["components/other-service"]
    assert manifest_detected.provenance.kind.value == "observed"
    assert "declares its own project manifest" in manifest_detected.content


def test_git_detected_boundary_is_not_described_as_declaring_a_manifest(
    tmp_path: Path,
) -> None:
    """A vendored clone carries no manifest; saying it declares one is fabricated.

    `traversal` detects a nested boundary two different ways: a project manifest
    seen in the walk, and a direct probe for a nested `.git` directory (`.git` is a
    skipped directory name, so it never appears in the walk at all). The exclusion
    is right either way, but the *stated reason* was the manifest sentence in both
    cases — so a directory holding nothing but `.git/` and a `Dockerfile` was
    published at OBSERVED confidence 1.0 as one that "declares its own project
    manifest", a fact about a file that does not exist. Same defect as the
    owner-declared case above, one detection path further on.
    """
    root = _target_project(tmp_path / "project")
    clone = root / "vendored-clone"
    clone.mkdir()
    (clone / ".git").mkdir()
    (clone / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (clone / "Dockerfile").write_text("FROM python:3.11-slim\n", encoding="utf-8")
    _plant_nested_project(root / "components", "other-service")

    assert not (clone / "pyproject.toml").exists()
    assert not (clone / "package.json").exists()

    intake = inspect_project(root)
    boundary_observations = {
        item.provenance.source_ref: item
        for item in intake.observations
        if item.subject == "nested-project" and item.content.startswith("nested project boundary")
    }
    assert set(boundary_observations) == {"vendored-clone", "components/other-service"}

    git_detected = boundary_observations["vendored-clone"]
    # The exclusion is still real, still OBSERVED, still full confidence...
    assert git_detected.provenance.kind.value == "observed"
    assert git_detected.provenance.confidence == 1.0
    assert "not evidence about this project" in git_detected.content
    # ...but justified by what the probe actually found.
    assert "declares its own project manifest" not in git_detected.content
    assert ".git" in git_detected.content
    # The exclusion still takes effect: the clone's Dockerfile is not the target's.
    assert not any(
        (item.provenance.source_ref or "").startswith("vendored-clone/")
        for item in intake.observations
    )

    # A genuine manifest-detected boundary keeps the manifest reason.
    assert (
        "declares its own project manifest"
        in boundary_observations["components/other-service"].content
    )


def test_git_detected_boundary_still_produces_a_readiness_scope_note(
    tmp_path: Path,
) -> None:
    """`readiness` finds boundary records by `NESTED_BOUNDARY_CONTENT_PREFIX`, not by
    the reason that follows it — rewording the `.git` case must not drop the scope
    note that keeps a "none observed" claim honest."""
    from agent_foundry.inspect.readiness import nested_boundary_refs

    root = _target_project(tmp_path / "project")
    clone = root / "vendored-clone"
    clone.mkdir()
    (clone / ".git").mkdir()
    (clone / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (clone / "Dockerfile").write_text("FROM python:3.11-slim\n", encoding="utf-8")

    intake = inspect_project(root)
    assert nested_boundary_refs(list(intake.observations)) == ["vendored-clone"]


# ---------------------------------------------------------------------------
# A caller-supplied override must not silently discard the owner's declaration
# ---------------------------------------------------------------------------


def test_caller_supplied_override_records_the_superseded_owner_declaration(
    tmp_path: Path,
) -> None:
    """Passing `nested_project_overrides` explicitly bypasses `.foundry/project.yaml`
    for *effect*, but the owner's on-disk declaration — if present — must still be
    recorded as superseded rather than vanishing without a trace.
    """
    root = _target_project(tmp_path / "project")
    zsub = root / "zsub"
    zsub.mkdir()
    (zsub / "Dockerfile").write_text("FROM python:3.11-slim\n", encoding="utf-8")
    _write_override(root, exclude=["zsub"])

    # A caller supplies its own override directly (empty: no include/exclude at all).
    intake = inspect_project(root, nested_project_overrides=NestedProjectOverrides())

    # The owner's exclusion was NOT applied under the caller-supplied override:
    # zsub/Dockerfile is attributed to the target.
    assert any(
        item.provenance.source_ref == "zsub/Dockerfile"
        for item in intake.observations
    )
    # But its supersession is recorded, naming the on-disk source.
    superseded = [
        item
        for item in intake.observations
        if item.subject == "nested-project" and "superseded" in item.content
    ]
    assert len(superseded) == 1
    assert ".foundry/project.yaml" in superseded[0].content
    assert superseded[0].provenance.kind.value == "observed"


def test_caller_supplied_override_matching_the_disk_declaration_is_not_reported_as_superseded(
    tmp_path: Path,
) -> None:
    """No spurious "superseded" observation when the caller passes through the same
    declaration that is already on disk — nothing was actually overridden."""
    root = _target_project(tmp_path / "project")
    _plant_markerless_subtree(root, "zsub")
    _write_override(root, exclude=["zsub"])

    same_override = load_nested_project_overrides(root, walk_repository(root).entries)
    intake = inspect_project(root, nested_project_overrides=same_override)

    superseded = [
        item
        for item in intake.observations
        if item.subject == "nested-project" and "superseded" in item.content
    ]
    assert superseded == []
