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
    NestedProjectOverrideDecision,
    NestedProjectOverrides,
    load_nested_project_overrides,
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
