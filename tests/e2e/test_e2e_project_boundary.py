"""One target, one project: a nested project's files are not the target's evidence.

The mutation this file exists for: take a project, inspect it, then plant a complete
second project inside it — its own manifest, its own `Dockerfile`, its own
`env.example`, its own instruction surface — and require that **nothing about the
target's diagnosis changes** except the recorded fact that a boundary is there.

Measured on Agent Foundry itself before this held: eight fixture repositories under
`tests/fixtures/projects/` supplied 22 of 25 adoption evidence references, two wrong
readiness findings, and a compiled write scope over seven `env.example` files nobody
wanted changed. Every one of those checks passed. The bundle was a correct compilation
of a wrong diagnosis, which is why this is a boundary problem and not a validation one:
no validator can tell that a granted path is the wrong path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_foundry.adopt import plan_adoption
from agent_foundry.inspect import inspect_project
from agent_foundry.inspect.traversal import (
    NESTED_PROJECT_MARKERS,
    nested_project_roots,
    walk_repository,
)

# What the target says about its own surfaces. `repository-structure` is deliberately
# excluded and checked separately: that a new directory exists *is* a fact about the
# target, and a test claiming otherwise would be asserting something false. What must
# not change is every claim about what the target contains.
def _diagnosis(root: Path) -> dict[str, object]:
    intake = inspect_project(root)
    return {
        "observations": sorted(
            (item.subject, item.content, item.provenance.source_ref or "")
            for item in intake.observations
            if item.subject not in {"nested-project", "repository-structure"}
        ),
        "conventions": sorted(
            (item.subject, item.pattern, item.source_ref, item.evidence)
            for item in intake.conventions
        ),
        "classification": sorted(
            (item.dimension, item.value or "", item.provenance.kind.value)
            for item in intake.classification_findings
        ),
        "readiness": sorted(
            (item.dimension, item.message, item.blocker)
            for item in intake.readiness_findings
        ),
    }


def _target_project(root: Path) -> Path:
    """A small, complete project: source, tests, manifest, instruction surface."""
    (root / "src" / "target").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "src" / "target" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "src" / "target" / "core.py").write_text("def run() -> int:\n    return 1\n", encoding="utf-8")
    (root / "src" / "target" / "io.py").write_text("def load() -> None:\n    return None\n", encoding="utf-8")
    (root / "tests" / "conftest.py").write_text("", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[project]\nname = "target"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    (root / "AGENTS.md").write_text("Run pytest before proposing a change.\n", encoding="utf-8")
    return root


def _plant_nested_project(parent: Path, name: str) -> Path:
    """A complete second project, with every surface that would mislead a diagnosis."""
    nested = parent / name
    (nested / "src").mkdir(parents=True)
    (nested / "src" / "__init__.py").write_text("", encoding="utf-8")
    (nested / "pyproject.toml").write_text(
        '[project]\nname = "nested"\nversion = "9.9.9"\n', encoding="utf-8"
    )
    (nested / "Dockerfile").write_text("FROM python:3.11-slim\n", encoding="utf-8")
    (nested / "env.example").write_text("NESTED_TOKEN=\n", encoding="utf-8")
    (nested / "AGENTS.md").write_text("Nested rules; not the target's.\n", encoding="utf-8")
    (nested / "Makefile").write_text(".PHONY: test\ntest:\n\tpytest -q\n", encoding="utf-8")
    return nested


def test_planting_a_whole_project_inside_the_target_changes_no_evidence_about_it(
    tmp_path: Path,
) -> None:
    """The mutation. Every claim about what the target contains must be unchanged."""
    root = _target_project(tmp_path / "project")
    before = _diagnosis(root)

    _plant_nested_project(root / "components", "other-service")
    after = _diagnosis(root)

    assert after == before, {
        key: (before[key], after[key]) for key in before if before[key] != after[key]
    }


def test_the_structure_observation_notices_the_directory_and_nothing_in_it(
    tmp_path: Path,
) -> None:
    """A new directory is a fact about the target; its contents are not.

    This is the one thing planting a project legitimately changes, so it is asserted
    rather than excluded from the comparison above and left unexamined.
    """
    root = _target_project(tmp_path / "project")
    _plant_nested_project(root / "components", "other-service")

    structure = [
        item.content
        for item in inspect_project(root).observations
        if item.subject == "repository-structure"
    ]
    top_level = next(item for item in structure if item.startswith("top-level entries:"))
    assert "components" in top_level

    # Nothing inside the nested project is named anywhere in the structure record.
    for item in structure:
        assert "other-service" not in item
        assert "Dockerfile" not in item


def test_the_planted_project_is_recorded_rather_than_silently_skipped(
    tmp_path: Path,
) -> None:
    """"Not attributed" must be distinguishable from "not there".

    An exclusion that leaves no trace reads exactly like an absence, which is the same
    confusion a truncated traversal produced when it reported a repository as having
    no tests.
    """
    root = _target_project(tmp_path / "project")
    _plant_nested_project(root / "components", "other-service")

    boundaries = [
        item
        for item in inspect_project(root).observations
        if item.subject == "nested-project"
    ]
    assert len(boundaries) == 1
    assert boundaries[0].provenance.source_ref == "components/other-service"
    assert "not evidence about this project" in boundaries[0].content


def test_the_nested_project_still_inspects_correctly_as_its_own_target(
    tmp_path: Path,
) -> None:
    """Excluding it from the parent must not make it uninspectable in its own right."""
    root = _target_project(tmp_path / "project")
    nested = _plant_nested_project(root / "components", "other-service")

    subjects = {item.subject for item in inspect_project(nested).observations}
    assert "package-metadata" in subjects
    assert "runtime-deploy-hint" in subjects
    assert "integration-config" in subjects
    assert "agent-instruction-surface" in subjects


def test_the_planted_project_changes_no_adoption_change(tmp_path: Path) -> None:
    """The plan is about the target, so planting a project must not add work to it."""
    root = _target_project(tmp_path / "project")

    def plan() -> list[tuple[str, str]]:
        result = plan_adoption(inspect_project(root))
        return sorted(
            (change.action.value, change.target) for change in result.change_set.changes
        )

    before = plan()
    _plant_nested_project(root / "components", "other-service")
    assert plan() == before


def test_no_evidence_reference_points_inside_a_nested_project(tmp_path: Path) -> None:
    root = _target_project(tmp_path / "project")
    _plant_nested_project(root / "components", "other-service")

    result = plan_adoption(inspect_project(root))
    for change in result.change_set.changes:
        for ref in change.evidence.evidence_refs:
            assert not ref.startswith("components/other-service/"), (
                f"{change.target} cites {ref!r} from a nested project"
            )


def test_a_marker_at_the_repository_root_is_the_target_not_a_boundary(
    tmp_path: Path,
) -> None:
    """The root's own `pyproject.toml` declares the target, not a nested project."""
    root = _target_project(tmp_path / "project")
    assert nested_project_roots(root.resolve(), walk_repository(root.resolve()).entries) == []

    subjects = {item.subject for item in inspect_project(root).observations}
    assert "package-metadata" in subjects


@pytest.mark.parametrize("marker", sorted(NESTED_PROJECT_MARKERS - {".git"}))
def test_every_declared_marker_establishes_a_boundary(marker: str, tmp_path: Path) -> None:
    """Each marker in the set is load-bearing, not decorative."""
    root = _target_project(tmp_path / "project")
    nested = root / "components" / "thing"
    nested.mkdir(parents=True)
    (nested / marker).write_text("{}\n", encoding="utf-8")
    (nested / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")

    intake = inspect_project(root)
    assert "components/thing" in {
        item.provenance.source_ref
        for item in intake.observations
        if item.subject == "nested-project"
    }
    assert not any(item.subject == "runtime-deploy-hint" for item in intake.observations)


def test_a_nested_git_directory_establishes_a_boundary(tmp_path: Path) -> None:
    """A separate repository is the least ambiguous nested project there is."""
    root = _target_project(tmp_path / "project")
    nested = root / "components" / "cloned"
    (nested / ".git").mkdir(parents=True)
    (nested / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")

    intake = inspect_project(root)
    assert "components/cloned" in {
        item.provenance.source_ref
        for item in intake.observations
        if item.subject == "nested-project"
    }
    assert not any(item.subject == "runtime-deploy-hint" for item in intake.observations)


def test_a_lock_file_alone_is_not_a_project(tmp_path: Path) -> None:
    """A lock file travels with a project; it does not constitute one.

    Splitting a repository at every `requirements.txt` or `package-lock.json` would
    make an ordinary layout into a dozen projects and hide most of it from its own
    diagnosis. The marker set is deliberately narrower than `PACKAGE_METADATA_FILES`.
    """
    root = _target_project(tmp_path / "project")
    subdir = root / "src" / "target" / "vendored"
    subdir.mkdir(parents=True)
    (subdir / "requirements.txt").write_text("attrs\n", encoding="utf-8")
    (subdir / "poetry.lock").write_text("# lock\n", encoding="utf-8")

    intake = inspect_project(root)
    assert not any(item.subject == "nested-project" for item in intake.observations)


def test_only_the_outermost_boundary_is_reported(tmp_path: Path) -> None:
    """A project inside a project inside the target is excluded once, not twice."""
    root = _target_project(tmp_path / "project")
    _plant_nested_project(root / "components", "outer")
    _plant_nested_project(root / "components" / "outer", "inner")

    boundaries = {
        item.provenance.source_ref
        for item in inspect_project(root).observations
        if item.subject == "nested-project"
    }
    assert boundaries == {"components/outer"}
