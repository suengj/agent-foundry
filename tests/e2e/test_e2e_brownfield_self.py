"""The same slice, over a real brownfield repository: this one.

Agent Foundry is a genuine brownfield target — a real source tree, a real test
runner, real instruction surfaces, real conventions — and it is public, so anyone
reading the release can reproduce every assertion here against the same repository.

Two things this file is for. First, the read-only guarantee: the full path from
inspection to receipt must leave the repository byte-identical, mtimes included.
Second, the measurements AF8 owes — what inspection sees, what it misses, and what a
human still has to supply — pinned as tests so they cannot quietly drift into prose.
"""

from __future__ import annotations

import pytest

from agent_foundry.adopt import plan_adoption
from agent_foundry.inspect import inspect_project
from agent_foundry.models import (
    AdoptionAction,
    AssuranceMode,
    ExternalEffectClass,
    IntakeMode,
    ProvenanceKind,
)
from agent_foundry.secrets import raise_on_embedded_secrets

from tests.e2e import support
from tests.e2e.pipeline import PipelineResult, run_pipeline

# Paths the harness never reads and that change for reasons unrelated to the run.
_SNAPSHOT_EXCLUDED = {".git", ".pytest_cache", "__pycache__"}


def _repo_snapshot() -> dict[str, tuple[str, int, int]]:
    snapshot: dict[str, tuple[str, int, int]] = {}
    for path in sorted(support.REPO_ROOT.iterdir()):
        if path.name in _SNAPSHOT_EXCLUDED or (path / "pyvenv.cfg").is_file():
            continue
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if any(part in _SNAPSHOT_EXCLUDED for part in child.parts):
                    continue
                rel = child.relative_to(support.REPO_ROOT).as_posix()
                stat = child.lstat()
                snapshot[rel] = (
                    "<dir>" if child.is_dir() else str(stat.st_size),
                    stat.st_mode,
                    stat.st_mtime_ns,
                )
        else:
            stat = path.lstat()
            rel = path.relative_to(support.REPO_ROOT).as_posix()
            snapshot[rel] = (str(stat.st_size), stat.st_mode, stat.st_mtime_ns)
    return snapshot


@pytest.fixture(scope="module")
def result() -> PipelineResult:
    return run_pipeline(
        support.REPO_ROOT,
        run_id="RUN-E2E-SELF-001",
        registry=support.self_registry(),
    )


# --- the read-only guarantee ---------------------------------------------------


def test_the_whole_slice_leaves_this_repository_untouched() -> None:
    """Inspect, adopt, resolve, compile, render, validate, receipt — all read-only.

    Size, mode and mtime are all compared. Content is represented by size here rather
    than by digest because this runs over the working tree: a digest of every file
    would be slower without catching anything a size-plus-mtime change would miss, and
    an in-place edit that preserved both is not a failure mode the inspector has.
    """
    before = _repo_snapshot()
    run_pipeline(
        support.REPO_ROOT, run_id="RUN-E2E-READONLY", registry=support.self_registry()
    )
    after = _repo_snapshot()
    assert before == after, {
        key: (before.get(key), after.get(key))
        for key in set(before) | set(after)
        if before.get(key) != after.get(key)
    }


def test_inspection_alone_writes_nothing_either() -> None:
    before = _repo_snapshot()
    inspect_project(support.REPO_ROOT)
    plan_adoption(inspect_project(support.REPO_ROOT))
    assert _repo_snapshot() == before


# --- what inspection saw -------------------------------------------------------


def test_this_repository_is_fully_visible_within_traversal_bounds(
    result: PipelineResult,
) -> None:
    """The virtualenv in this worktree must not consume the traversal budget.

    Before AF8 the skip list matched directory *names*, so `.venv-lane` was walked:
    it sorts before every source directory, holds thousands of files, and exhausted
    the 2000-entry budget before `src/` was reached. Inspection then reported "no test
    entrypoints observed" about a repository with a full suite.
    """
    stats = result.intake.traversal_stats
    assert not stats.entry_limit_reached
    assert not stats.depth_limit_reached
    assert stats.entries_unobservable == 0
    subjects = {observation.subject for observation in result.intake.observations}
    assert "test-entrypoint" in subjects
    assert "agent-instruction-surface" in subjects
    assert "foundry-declaration" in subjects


def test_readiness_reflects_what_is_actually_here(result: PipelineResult) -> None:
    by_dimension = {
        finding.dimension: finding for finding in result.intake.readiness_findings
    }
    assert "Deterministic test entrypoints are observable" in by_dimension["testability"].message
    assert not any(finding.blocker for finding in result.intake.readiness_findings)


# --- measured gaps, pinned rather than described -------------------------------


def test_repository_revision_is_unknown_in_a_git_worktree() -> None:
    """AF8 finding: `repository_revision` is None whenever `.git` is not a directory.

    A `git worktree` checkout carries a `.git` *file* pointing at a gitdir outside the
    repository root, and containment correctly refuses to follow it. The consequence is
    that every downstream identity — evidence `proves_revision`, receipt
    `candidate_revision`, reconciliation's identity findings — has no revision to bind
    to, and reads as "not recorded" rather than "could not be determined".

    This test states which of the two situations this checkout is in, so the finding is
    observable either way rather than silently passing in one of them.
    """
    intake = inspect_project(support.REPO_ROOT)
    git_path = support.REPO_ROOT / ".git"
    if git_path.is_dir():
        assert intake.repository_revision is not None
    else:
        assert git_path.is_file(), "expected a worktree pointer file"
        assert intake.repository_revision is None
    revision_observations = [
        observation
        for observation in intake.observations
        if observation.subject == "repository-revision"
    ]
    assert revision_observations, "the absence must be recorded, not merely absent"


def test_convention_discovery_covers_four_hardcoded_surfaces_only(
    result: PipelineResult,
) -> None:
    """AF8 measurement: what convention discovery can find, and what it cannot.

    Discovery knows four patterns — a pytest mention in an instruction surface, a
    commit constraint in one, a Makefile `test` recipe, and a CI checkout step. This
    repository has the first two and neither of the last two, so it yields exactly the
    conventions those patterns can see. The declared test runner in
    `pyproject.toml [tool.pytest.ini_options]` — a stronger, declared fact — is not
    among them, because nothing reads it.
    """
    subjects = {convention.subject for convention in result.intake.conventions}
    assert subjects <= {"test-runner", "test-invocation", "ci-checkout", "git-policy"}
    assert "test-runner" in subjects
    for convention in result.intake.conventions:
        assert convention.provenance.kind is ProvenanceKind.INFERRED
        assert convention.confidence <= 0.5, (
            "every discoverable convention here is a textual mention, and a mention "
            "is weaker evidence than the declaration in pyproject.toml that is not read"
        )


def test_an_undeclared_copy_of_this_repository_resolves_no_toolkit(tmp_path) -> None:
    """AF8 measurement: how much of the manifest inference can supply. One field.

    Copying the declaration away leaves a repository with a source tree, a test suite,
    CI-shaped metadata and instruction surfaces — and inference still fills exactly
    `intake_mode`, by design: nothing else may be inferred, because inference must not
    expand authority. The measured consequence is that the resolved toolkit is empty
    and no role can be compiled.
    """
    import shutil

    target = tmp_path / "undeclared"
    shutil.copytree(
        support.REPO_ROOT / "src", target / "src", dirs_exist_ok=False
    )
    shutil.copy2(support.REPO_ROOT / "pyproject.toml", target / "pyproject.toml")
    shutil.copy2(support.REPO_ROOT / "AGENTS.md", target / "AGENTS.md")

    intake = inspect_project(target)
    manifest = plan_adoption(intake).manifest
    assert manifest.project.intake_mode is IntakeMode.BROWNFIELD
    declared_fields = [
        manifest.project.name,
        manifest.project.work_modes,
        manifest.project.primary_artifact,
        manifest.state.persistence,
        manifest.state.temporal_mode,
        manifest.impact.external_effect,
        manifest.impact.reversibility,
        manifest.impact.consequence,
        manifest.execution.autonomy,
        manifest.execution.ambiguity,
        manifest.execution.concurrency,
        manifest.access.sensitivity,
        manifest.assurance.required or None,
    ]
    assert all(value is None for value in declared_fields), (
        "inference must not supply a manifest characteristic"
    )

    from agent_foundry.toolkit import resolve_toolkit

    _, lock = resolve_toolkit(manifest)
    assert lock.role_ids == []
    assert lock.capability_ids == []


def test_the_undeclared_copy_is_told_to_declare(tmp_path) -> None:
    """The retrofit plan names the missing declaration instead of reporting success."""
    import shutil

    target = tmp_path / "undeclared"
    shutil.copytree(support.REPO_ROOT / "src", target / "src")
    shutil.copy2(support.REPO_ROOT / "pyproject.toml", target / "pyproject.toml")

    change_set = plan_adoption(inspect_project(target)).change_set
    migrate = [
        change
        for change in change_set.changes
        if change.action is AdoptionAction.MIGRATE
        and change.target == "foundry-project-declaration"
    ]
    assert migrate, [change.target for change in change_set.changes]
    assert migrate[0].authority_requirement.value == "bounded-policy"
    assert "empty toolkit" in migrate[0].evidence.summary


# --- the retrofitted repository reaches the end of the slice --------------------


def test_the_declared_manifest_is_this_repository_s_own(result: PipelineResult) -> None:
    manifest = result.manifest
    assert manifest.project.name == "agent-foundry"
    assert manifest.project.intake_mode is IntakeMode.BROWNFIELD
    assert manifest.impact.external_effect is ExternalEffectClass.REPOSITORY_WRITE
    assert AssuranceMode.DETERMINISTIC_TESTS in manifest.assurance.required
    assert AssuranceMode.INDEPENDENT_REVIEW in manifest.assurance.required
    assert manifest.access.sensitivity is not None


def test_the_retrofit_is_additive_and_the_declaration_is_kept(
    result: PipelineResult,
) -> None:
    """Nothing is rewritten. The one artifact adoption added is now retained."""
    actions = {change.action for change in result.change_set.changes}
    assert AdoptionAction.MIGRATE not in actions, (
        "the declaration exists, so nothing needs migrating"
    )
    assert AdoptionAction.BLOCK not in actions
    kept = {
        change.target
        for change in result.change_set.changes
        if change.action is AdoptionAction.KEEP
    }
    assert "foundry-project-declaration" in kept
    assert "package-metadata" in kept


def test_the_slice_produces_a_usable_bundle_over_this_repository(
    result: PipelineResult,
) -> None:
    bundle = result.bundle
    assert bundle.project_name == "agent-foundry"
    assert bundle.authority.external_effect is ExternalEffectClass.REPOSITORY_WRITE
    assert bundle.write_scope, "a write bundle with no write path is useless"
    for path in bundle.write_scope:
        assert not path.startswith("/") and ".." not in path
        assert (support.REPO_ROOT / path).exists(), (
            f"{path!r} is granted but does not exist in the repository"
        )
    assert result.accepted(), result.rejecting()
    raise_on_embedded_secrets(bundle.model_dump(mode="json"))


def test_the_rendered_contract_is_short_enough_to_hand_to_an_agent(
    result: PipelineResult,
) -> None:
    assert len(result.markdown.encode("utf-8")) < 4000
    assert result.work_item.objective in result.markdown
