"""ProjectProfile synthesis: determinism, epistemic honesty, authority non-expansion.

Test naming follows the Manager's contract letters (A-K) so a failure maps
directly back onto the acceptance criterion it proves.
"""

from __future__ import annotations

import inspect
import os
import random
import subprocess
import sys
from pathlib import Path

import pytest

from agent_foundry.adopt import plan_adoption
from agent_foundry.adopt.authority import autonomy_rank, external_effect_rank
from agent_foundry.inspect import inspect_project
from agent_foundry.models import (
    Autonomy,
    ClassificationFinding,
    ConventionSpec,
    ExternalEffectClass,
    ProfileResolution,
    Provenance,
    ProvenanceKind,
    ProjectIntake,
    ProjectObservation,
    ProjectProfile,
    TraversalLimits,
    TraversalStats,
    dump_json,
    load_json,
)
from agent_foundry.profile import synthesize_project_profile
from agent_foundry.profile import synth as profile_synth

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "projects"
GOLDEN = REPO_ROOT / "tests" / "golden"
# Deliberately *outside* `tests/fixtures/`: `test_models_public_boundary.py`'s
# provider-neutrality scan globs every .yaml/.yml/.json under `tests/fixtures/`,
# and these golden files legitimately quote real path fragments from the
# `brownfield-sample` fixture (`.github/workflows/...`, `CLAUDE.md`, `.cursor/...`)
# as part of the synthesized evidence they snapshot. That is real inspection
# output, not a provider-specific surface this package exposes, but the scanner
# cannot tell the difference — so these live one directory up instead of
# fighting the scanner's fixed word list.
GREENFIELD = FIXTURES / "greenfield-minimal"
BROWNFIELD = FIXTURES / "brownfield-sample"

ALL_FIXTURES = sorted(p for p in FIXTURES.iterdir() if p.is_dir())


def _subprocess_env() -> dict[str, str]:
    return {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}


def _minimal_intake(**overrides: object) -> ProjectIntake:
    limits = TraversalLimits(max_depth=4, max_entries=100, max_file_bytes=65536, skipped_dir_names=[])
    stats = TraversalStats(
        entries_visited=1,
        entries_skipped=0,
        depth_limit_reached=False,
        entry_limit_reached=False,
        limits=limits,
    )
    base: dict[str, object] = {
        "schema_version": "0.2",
        "project_root": ".",
        "repository_revision": None,
        "observations": [],
        "classification_findings": [],
        "conventions": [],
        "readiness_findings": [],
        "traversal_stats": stats,
    }
    base.update(overrides)
    return ProjectIntake.model_validate(base)


# ---------------------------------------------------------------------------
# A. Determinism (byte-identical)
# ---------------------------------------------------------------------------


def test_a_synthesis_is_byte_identical_on_repeat() -> None:
    intake = inspect_project(BROWNFIELD)
    first = dump_json(synthesize_project_profile(intake))
    second = dump_json(synthesize_project_profile(intake))
    assert first == second


def test_a_synthesis_deterministic_across_hash_seed_and_cwd() -> None:
    script = (
        "from agent_foundry.inspect import inspect_project; "
        "from agent_foundry.profile import synthesize_project_profile; "
        "from agent_foundry.models import dump_json; "
        f"intake = inspect_project({str(BROWNFIELD)!r}); "
        "print(dump_json(synthesize_project_profile(intake)).decode('utf-8'), end='')"
    )
    outputs: dict[tuple[str, str], str] = {}
    for hash_seed in ("0", "1", "42"):
        for cwd in (REPO_ROOT, FIXTURES):
            completed = subprocess.run(
                [sys.executable, "-c", script],
                cwd=cwd,
                env={**_subprocess_env(), "PYTHONHASHSEED": hash_seed},
                capture_output=True,
                text=True,
                check=True,
            )
            outputs[(hash_seed, str(cwd))] = completed.stdout
    distinct = set(outputs.values())
    assert len(distinct) == 1, (
        "profile output varied across PYTHONHASHSEED/cwd: "
        f"{sorted(key for key, value in outputs.items() if value != next(iter(distinct)))}"
    )
    assert distinct.pop().strip()


@pytest.mark.parametrize("fixture", ALL_FIXTURES, ids=[p.name for p in ALL_FIXTURES])
def test_a_every_fixture_synthesizes_deterministically(fixture: Path) -> None:
    intake = inspect_project(fixture)
    first = dump_json(synthesize_project_profile(intake))
    second = dump_json(synthesize_project_profile(intake))
    assert first == second


# ---------------------------------------------------------------------------
# B. Ordering robustness — shuffled equivalent evidence -> identical output
# ---------------------------------------------------------------------------


def test_b_shuffled_observations_and_findings_produce_identical_profile() -> None:
    intake = inspect_project(BROWNFIELD)
    canonical = dump_json(synthesize_project_profile(intake))

    rng = random.Random(1234)
    for _ in range(5):
        shuffled_observations = list(intake.observations)
        shuffled_findings = list(intake.classification_findings)
        shuffled_conventions = list(intake.conventions)
        rng.shuffle(shuffled_observations)
        rng.shuffle(shuffled_findings)
        rng.shuffle(shuffled_conventions)
        shuffled_intake = intake.model_copy(
            update={
                "observations": shuffled_observations,
                "classification_findings": shuffled_findings,
                "conventions": shuffled_conventions,
            }
        )
        candidate = dump_json(synthesize_project_profile(shuffled_intake))
        assert candidate == canonical


def test_b_duplicate_evidence_in_different_orders_still_dedupes_identically() -> None:
    """Same finding listed twice, in each of the two possible orders, must collapse
    to one attribution either way — proving the dedup key, not merely the sort."""
    finding_a = ClassificationFinding(
        dimension="execution.autonomy",
        value="suggest",
        provenance=Provenance(kind=ProvenanceKind.DECLARED, confidence=0.8, source_ref=".foundry/project.yaml"),
        evidence_refs=[".foundry/project.yaml"],
    )
    finding_b = finding_a.model_copy(deep=True)

    forward = _minimal_intake(classification_findings=[finding_a, finding_b])
    backward = _minimal_intake(classification_findings=[finding_b, finding_a])

    profile_forward = synthesize_project_profile(forward)
    profile_backward = synthesize_project_profile(backward)
    assert dump_json(profile_forward) == dump_json(profile_backward)

    dim = next(d for d in profile_forward.dimensions if d.dimension == "execution.autonomy")
    assert dim.resolution is ProfileResolution.RESOLVED
    assert len(dim.attributions) == 1


# ---------------------------------------------------------------------------
# C. UNKNOWN — missing evidence yields an explicit UNKNOWN, never a guessed value
# ---------------------------------------------------------------------------


def test_c_no_evidence_at_all_yields_unknown_everywhere_expected() -> None:
    intake = _minimal_intake()
    profile = synthesize_project_profile(intake)
    by_name = {d.dimension: d for d in profile.dimensions}

    # Every classification-derived dimension must be UNKNOWN with zero evidence.
    for name in (
        "project.name",
        "primary_work_mode",
        "primary_artifact",
        "state.persistence",
        "impact.external_effect",
        "execution.autonomy",
        "assurance.required",
        "access.sensitivity",
    ):
        dim = by_name[name]
        assert dim.resolution is ProfileResolution.UNKNOWN, name
        assert dim.attributions == [], name


def test_c_greenfield_fixture_leaves_declared_dimensions_unknown_not_false() -> None:
    """The greenfield fixture declares nothing, so every declared/risk dimension
    must read UNKNOWN — never a value manufactured from the fact that nothing
    was declared (e.g. never 'read-only', never 'stateless')."""
    profile = synthesize_project_profile(inspect_project(GREENFIELD))
    by_name = {d.dimension: d for d in profile.dimensions}
    for name in (
        "state.persistence",
        "impact.external_effect",
        "impact.reversibility",
        "impact.consequence",
        "execution.autonomy",
        "execution.ambiguity",
        "execution.concurrency",
        "assurance.required",
        "access.sensitivity",
    ):
        dim = by_name[name]
        assert dim.resolution is ProfileResolution.UNKNOWN, name


def test_c_truncated_traversal_forces_structural_dimensions_to_unknown() -> None:
    """A limit-truncated walk must not let 'no marker observed' pass as resolved:
    the unexamined region might hold anything."""
    limits = TraversalLimits(max_depth=1, max_entries=1, max_file_bytes=1024, skipped_dir_names=[])
    truncated_stats = TraversalStats(
        entries_visited=1,
        entries_skipped=0,
        depth_limit_reached=True,
        entry_limit_reached=False,
        limits=limits,
    )
    intake = _minimal_intake(traversal_stats=truncated_stats)
    profile = synthesize_project_profile(intake)
    by_name = {d.dimension: d for d in profile.dimensions}

    for name in (
        "repository.package-metadata",
        "testability.test-entrypoint",
        "operating.deploy-surface",
        "integration.config-surface",
        "instruction.fragmentation",
        "repository.ownership-boundaries",
        "assurance.conventions-observed",
    ):
        dim = by_name[name]
        assert dim.resolution is ProfileResolution.UNKNOWN, (
            f"{name} resolved to {dim.resolution} from a truncated walk; "
            "absence under a truncated walk proves nothing"
        )


def test_c_exhaustive_empty_walk_resolves_structural_absence_not_unknown() -> None:
    """The counterpart to the truncation test: a *complete* walk that finds no
    marker is allowed to state that as a resolved structural fact."""
    intake = _minimal_intake()  # depth/entry limits false, unobservable=0 by default
    profile = synthesize_project_profile(intake)
    by_name = {d.dimension: d for d in profile.dimensions}
    dim = by_name["testability.test-entrypoint"]
    assert dim.resolution is ProfileResolution.RESOLVED
    assert dim.attributions[0].value == "none-observed"


def test_c_unobservable_paths_do_not_get_silently_dropped() -> None:
    limits = TraversalLimits(max_depth=4, max_entries=100, max_file_bytes=65536, skipped_dir_names=[])
    stats = TraversalStats(
        entries_visited=3,
        entries_skipped=1,
        entries_unobservable=1,
        depth_limit_reached=False,
        entry_limit_reached=False,
        limits=limits,
    )
    observation = ProjectObservation(
        subject="path-unobservable",
        content="directory contents could not be observed (permission-denied): secrets/",
        provenance=Provenance(kind=ProvenanceKind.OBSERVED, source_ref="secrets/"),
    )
    intake = _minimal_intake(traversal_stats=stats, observations=[observation])
    profile = synthesize_project_profile(intake)
    by_name = {d.dimension: d for d in profile.dimensions}

    unobservable_dim = by_name["evidence.unobservable-paths"]
    assert unobservable_dim.resolution is ProfileResolution.RESOLVED
    assert unobservable_dim.attributions[0].value == "1 unobservable path(s)"
    assert "secrets/" in unobservable_dim.attributions[0].evidence_refs

    # And the exhaustiveness-gated structural dims must fall back to UNKNOWN
    # because of the unobservable path, even with limits both false.
    assert by_name["testability.test-entrypoint"].resolution is ProfileResolution.UNKNOWN


def test_c_a_containment_refusal_forces_unknown_not_none_observed() -> None:
    """B1 regression: a symlink resolving outside the root (`entries_skipped_refused`)
    is a genuine hole — unlike a deliberately skipped `.git`/`vendor` directory, the
    walk never even considered what is behind it. "not observed" must not be
    reported as a resolved fact over that ground."""
    limits = TraversalLimits(max_depth=4, max_entries=100, max_file_bytes=65536, skipped_dir_names=[])
    stats = TraversalStats(
        entries_visited=2,
        entries_skipped=1,
        entries_skipped_refused=1,
        depth_limit_reached=False,
        entry_limit_reached=False,
        limits=limits,
    )
    intake = _minimal_intake(traversal_stats=stats)
    profile = synthesize_project_profile(intake)
    by_name = {d.dimension: d for d in profile.dimensions}

    for name in (
        "testability.test-entrypoint",
        "operating.deploy-surface",
        "repository.ownership-boundaries",
        "assurance.conventions-observed",
    ):
        assert by_name[name].resolution is ProfileResolution.UNKNOWN, (
            f"{name} resolved to a positive claim over ground a containment "
            "refusal never let the walk examine"
        )


def test_c_a_skipped_ignored_directory_scopes_none_observed_rather_than_forcing_unknown() -> None:
    """B1 regression, the other half: `entries_skipped_ignored_dir` (a `.git`,
    `vendor`, or `build` directory the walk deliberately did not descend into —
    true of nearly every real repository) must NOT force UNKNOWN the way a
    genuine hole does. It also must not let a resolved "not observed" fact read
    as universal — the value must say a skip happened."""
    limits = TraversalLimits(max_depth=4, max_entries=100, max_file_bytes=65536, skipped_dir_names=["vendor", "build"])
    stats = TraversalStats(
        entries_visited=3,
        entries_skipped=2,
        entries_skipped_ignored_dir=2,
        depth_limit_reached=False,
        entry_limit_reached=False,
        limits=limits,
    )
    intake = _minimal_intake(traversal_stats=stats)
    profile = synthesize_project_profile(intake)
    by_name = {d.dimension: d for d in profile.dimensions}

    for name in ("testability.test-entrypoint", "operating.deploy-surface", "repository.ownership-boundaries"):
        dim = by_name[name]
        assert dim.resolution is ProfileResolution.RESOLVED, name
        value = dim.attributions[0].value
        assert "outside skipped directories" in value, (
            f"{name}={value!r} does not scope its 'not observed' claim to "
            "exclude the directories the walk deliberately skipped"
        )
        assert "entries_skipped_ignored_dir=2" in value


def test_c_real_ignored_dir_and_refused_symlink_fixtures_reproduce_the_scoped_and_unknown_paths(
    tmp_path: Path,
) -> None:
    """The same two cases, built as real filesystem trees and run through the
    real inspector end to end — not only through hand-built `TraversalStats` —
    so the fix is proven against `inspect_project`'s actual accounting, not just
    against a stats object this test happens to construct correctly."""
    ignored = tmp_path / "ignored-dir-project"
    (ignored / "vendor" / "sub" / "tests").mkdir(parents=True)
    (ignored / "build").mkdir(parents=True)
    (ignored / "vendor" / "sub" / "pyproject.toml").write_text("x = 1\n")
    (ignored / "vendor" / "sub" / "tests" / "test_x.py").write_text("def test_x(): pass\n")
    (ignored / "build" / "Dockerfile").write_text("FROM scratch\n")
    (ignored / "main.py").write_text("print(1)\n")

    ignored_intake = inspect_project(ignored)
    assert ignored_intake.traversal_stats.entries_skipped_ignored_dir > 0
    assert ignored_intake.traversal_stats.entries_skipped_refused == 0
    ignored_profile = synthesize_project_profile(ignored_intake)
    by_name = {d.dimension: d for d in ignored_profile.dimensions}
    for name in ("testability.test-entrypoint", "operating.deploy-surface"):
        dim = by_name[name]
        assert dim.resolution is ProfileResolution.RESOLVED
        assert "outside skipped directories" in dim.attributions[0].value, (
            f"{name} must not claim 'none-observed' unscoped when the walk "
            "skipped vendor/ and build/ without saying so"
        )
    assert by_name["repository.ownership-boundaries"].resolution is ProfileResolution.RESOLVED
    assert (
        "outside skipped directories"
        in by_name["repository.ownership-boundaries"].attributions[0].value
    )

    outside_root = tmp_path / "outside-root"
    outside_root.mkdir()
    (outside_root / "file.txt").write_text("secret\n")
    symlinked = tmp_path / "symlink-project"
    (symlinked / "inside").mkdir(parents=True)
    (symlinked / "main.py").write_text("print(1)\n")
    (symlinked / "inside" / "escape").symlink_to(outside_root, target_is_directory=True)

    symlink_intake = inspect_project(symlinked)
    assert symlink_intake.traversal_stats.entries_skipped_refused > 0
    symlink_profile = synthesize_project_profile(symlink_intake)
    by_name_symlink = {d.dimension: d for d in symlink_profile.dimensions}
    for name in ("testability.test-entrypoint", "operating.deploy-surface", "repository.ownership-boundaries"):
        assert by_name_symlink[name].resolution is ProfileResolution.UNKNOWN, (
            f"{name} resolved a positive claim over ground the walk refused to "
            "cross into"
        )


def test_c_makefile_lint_and_typecheck_targets_reach_the_lint_type_entrypoint_dimension(
    tmp_path: Path,
) -> None:
    """B1 revision-2 regression, path 1: `_MAKEFILE_TARGET_SUBJECTS` (collectors.py)
    emits `lint-entrypoint`/`typecheck-entrypoint` observations for a Makefile's
    `lint:`/`typecheck:` targets, distinct from the filename-marker subject
    `lint-type-entrypoint` (ruff.toml, mypy.ini, ...). All three must feed the
    same dimension, or a Makefile-only project silently under-reports."""
    (tmp_path / "Makefile").write_text("lint:\n\truff check .\n\ntypecheck:\n\tmypy .\n")
    (tmp_path / "main.py").write_text("print(1)\n")

    intake = inspect_project(tmp_path)
    subjects = {obs.subject for obs in intake.observations}
    assert {"lint-entrypoint", "typecheck-entrypoint"} <= subjects, (
        "the fixture must actually produce both Makefile-target observations, "
        "or this test proves nothing"
    )

    profile = synthesize_project_profile(intake)
    dim = next(d for d in profile.dimensions if d.dimension == "testability.lint-type-entrypoint")
    assert dim.resolution is ProfileResolution.RESOLVED
    assert "lint" in dim.attributions[0].value
    assert "typecheck" in dim.attributions[0].value


def test_c_agent_facing_project_docs_reach_the_instruction_fragmentation_dimension(
    tmp_path: Path,
) -> None:
    """B1 revision-2 regression, path 2: `project-docs` (agent-facing docs under
    `docs/ai/`, collectors.py) is instruction/context surface exactly as much as
    an `agent-instruction-surface` file — a dimension whose stated purpose is
    measuring fragmentation must count both, not just one."""
    (tmp_path / "docs" / "ai").mkdir(parents=True)
    (tmp_path / "docs" / "ai" / "project-context.md").write_text("# context\n")
    (tmp_path / "AGENTS.md").write_text("# agent rules\n")
    (tmp_path / "main.py").write_text("print(1)\n")

    intake = inspect_project(tmp_path)
    subjects = {obs.subject for obs in intake.observations}
    assert {"agent-instruction-surface", "project-docs"} <= subjects, (
        "the fixture must actually produce both subjects, or this test proves nothing"
    )

    profile = synthesize_project_profile(intake)
    dim = next(d for d in profile.dimensions if d.dimension == "instruction.fragmentation")
    assert dim.resolution is ProfileResolution.RESOLVED
    assert "AGENTS.md" in dim.attributions[0].value
    assert "docs/ai/project-context.md" in dim.attributions[0].value


def test_c_a_file_skipped_for_size_forces_unknown_rather_than_none_observed(tmp_path: Path) -> None:
    """B1 revision-2 regression, path 3: a Makefile too large to read
    (`file-read-skipped`) means `test:`-target detection never ran — the
    intake itself records the disqualifying fact (`evidence.unread-files`), and
    the exhaustive-absence exception must account for it rather than reporting
    'none-observed' over content the walk knowingly never read."""
    oversized_makefile = "test:\n\tpytest\n" + ("# " + "x" * 70_000 + "\n")
    (tmp_path / "Makefile").write_text(oversized_makefile)
    (tmp_path / "main.py").write_text("print(1)\n")

    intake = inspect_project(tmp_path)
    assert any(obs.subject == "file-read-skipped" for obs in intake.observations), (
        "the fixture Makefile must actually exceed the read-size limit, or "
        "this test proves nothing"
    )
    # And no marker-based test-entrypoint observation exists either — the only
    # evidence this project could have produced was inside the unread file.
    assert not any(obs.subject == "test-entrypoint" for obs in intake.observations)

    profile = synthesize_project_profile(intake)
    dim = next(d for d in profile.dimensions if d.dimension == "testability.test-entrypoint")
    assert dim.resolution is ProfileResolution.UNKNOWN, (
        f"expected UNKNOWN over an unread Makefile, got {dim.resolution} "
        f"{[a.value for a in dim.attributions]}"
    )


def test_c_an_unread_file_does_not_make_a_filename_derived_absence_unknown(
    tmp_path: Path,
) -> None:
    """R1 regression. The counterpart to the test directly above: there, the
    unread file was the *only* place the answer could have been. Here the unread
    file is an oversized Python source file, and the dimensions under test are
    decided purely by filenames on the walked entry list — `Dockerfile` and the
    other deploy markers, `.env.example` and the other integration markers,
    `*.schema.json`. The walk saw and recorded every name in this tree; an
    unread *body* of one of those files cannot change whether a file named
    `Dockerfile` is among them.

    Reporting those dimensions as UNKNOWN because some unrelated file was too
    large is absence-as-evidence in its own right: it launders a hole in one
    dimension's evidence into a hole in another's, and the profile then says
    "unknown" about something it directly observed.
    """
    (tmp_path / "app.py").write_text("x = 1\n" + ("# " + "y" * 70_000 + "\n"))
    (tmp_path / "README.md").write_text("# sample\n")

    intake = inspect_project(tmp_path)
    unread = [obs for obs in intake.observations if obs.subject == "file-read-skipped"]
    assert unread, "the fixture file must actually exceed the read-size limit"
    stats = intake.traversal_stats
    assert not stats.depth_limit_reached and not stats.entry_limit_reached
    assert stats.entries_unobservable == 0 and stats.entries_skipped_refused == 0, (
        "the fixture must leave a content hole and no path hole, or this test "
        "proves nothing about the difference between the two"
    )

    by_name = {d.dimension: d for d in synthesize_project_profile(intake).dimensions}

    # SUE-580 S5: the previous version of this loop asserted
    #     "none-observed" in value or value
    # whose right operand is a non-empty string, so the whole disjunction was
    # always truthy and the assertion could never fail — the exact failure mode
    # this suite exists to prevent. Each dimension's own none-observed value is
    # spelled out instead, so a dimension that silently started publishing some
    # other value goes red.
    for name, expected in {
        "operating.deploy-surface": "none-observed",
        "integration.config-surface": "none-observed",
        "testability.config-schema": "none-observed",
        "repository.package-metadata": "none-observed",
        "instruction.fragmentation": "no-agent-instruction-surface-observed",
    }.items():
        dim = by_name[name]
        assert dim.resolution is ProfileResolution.RESOLVED, (
            f"{name} is decided by filenames on the entry list, but resolved to "
            f"{dim.resolution} because an unrelated oversized file went unread"
        )
        assert len(dim.attributions) == 1, name
        # startswith, not equality: `_scope_none_observed` may append an
        # "outside ..." qualifier, which is a scope on the same claim, not a
        # different claim.
        assert dim.attributions[0].value.startswith(expected), (
            f"{name} published {dim.attributions[0].value!r}, expected the "
            f"none-observed value {expected!r}"
        )

    # The content-derived half of the same profile must NOT have moved: an unread
    # file could genuinely hide a Makefile target, a nested-project override or a
    # parsed convention.
    #
    # SUE-580 S1: this list covers EVERY content-derived dimension whose
    # none-observed branch this fixture can reach, not just the two it used to
    # name. `_SubjectDerivation` is a hand-maintained per-call-site judgement and
    # only the safe direction was guarded: mismarking a CONTENT subject as NAME
    # publishes an absence claim over ground the walk could not read, and the
    # suite stayed green through a three-way flip of
    # `repository.ownership-boundaries`, `testability.lint-type-entrypoint` and
    # `testability.ci-entrypoint`. Flipping any one of these to NAME now fails
    # here. (`repository.revision` is the sixth CONTENT call site; its
    # none-observed branch is unreachable from a real walk, so it is covered at
    # unit level by the table test below.)
    for name in (
        "repository.ownership-boundaries",
        "testability.test-entrypoint",
        "testability.lint-type-entrypoint",
        "testability.ci-entrypoint",
        "assurance.conventions-observed",
    ):
        assert by_name[name].resolution is ProfileResolution.UNKNOWN, (
            f"{name} is derived from file content; an unread file must keep it "
            f"UNKNOWN, got {by_name[name].resolution} "
            f"{[a.value for a in by_name[name].attributions]}"
        )


#: Every ``_SubjectDerivation.CONTENT`` call site in ``profile/synth.py``, and
#: every ``NAME`` one, as of SUE-580. A dimension moving between these lists is
#: a deliberate re-classification of what evidence decides its emptiness, and
#: must be made here as well as at the call site.
_CONTENT_DERIVED_DIMENSIONS = (
    "repository.revision",
    "repository.ownership-boundaries",
    "testability.test-entrypoint",
    "testability.lint-type-entrypoint",
    "testability.ci-entrypoint",
    "assurance.conventions-observed",
)

_NAME_DERIVED_DIMENSIONS = (
    "repository.structure",
    "repository.package-metadata",
    "repository.foundry-artifacts",
    "testability.config-schema",
    "operating.deploy-surface",
    "integration.config-surface",
    "instruction.fragmentation",
)


def test_c_every_content_derived_dimension_is_gated_on_the_content_hole() -> None:
    """SUE-580 S1. The unguarded direction of the `_SubjectDerivation` judgement.

    The classification is correct today, but only its *safe* direction had a
    test: marking a NAME subject as CONTENT costs a little precision and was
    caught, while marking a CONTENT subject as NAME publishes a confident
    absence over bytes the walk never read and was caught by nothing. A probe
    flipping three CONTENT call sites to NAME in one patch left the entire suite
    green.

    Every content-derived dimension must therefore be UNKNOWN over a
    ``file-read-skipped`` observation, and — so this cannot be satisfied by
    over-gating everything — every name-derived dimension must stay RESOLVED
    over the same evidence.
    """
    unread = ProjectObservation(
        subject="file-read-skipped",
        content="file exceeds read limit (99999 > 10 bytes): big.py",
        provenance=Provenance(kind=ProvenanceKind.OBSERVED, confidence=1.0, source_ref="big.py"),
    )
    by_name = {
        d.dimension: d
        for d in synthesize_project_profile(_minimal_intake(observations=[unread])).dimensions
    }

    for name in _CONTENT_DERIVED_DIMENSIONS:
        assert by_name[name].resolution is ProfileResolution.UNKNOWN, (
            f"{name} is classified CONTENT but published an absence over an "
            f"unread file: {by_name[name].resolution} "
            f"{[a.value for a in by_name[name].attributions]}"
        )

    for name in _NAME_DERIVED_DIMENSIONS:
        assert by_name[name].resolution is ProfileResolution.RESOLVED, (
            f"{name} is classified NAME and is settled by the entry list, but an "
            f"unrelated unread file made it {by_name[name].resolution}"
        )


def test_c_nested_project_boundary_scopes_the_none_observed_claims_it_creates(
    tmp_path: Path,
) -> None:
    """SUE-580 S3. An owner-declared exclusion must scope its own absences.

    ``_scope_none_observed`` already scopes a "none observed" claim when
    ``SKIP_DIR_NAMES`` caused a skip, on the stated reasoning that such a claim
    "must not read as universal". A nested-project boundary excludes ground for
    a different reason with the identical effect — and, on this branch, an owner
    may apply it to an arbitrary *markerless* directory. Without scoping, a
    reader of ``operating.deploy-surface`` alone is told at OBSERVED 1.0 that no
    deploy surface exists in a repository that contains a Dockerfile.
    """
    (tmp_path / ".foundry").mkdir()
    (tmp_path / ".foundry" / "project.yaml").write_text(
        "inspection:\n"
        "  nested_project_overrides:\n"
        "    exclude:\n"
        "      - src\n"
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Dockerfile").write_text("FROM python:3.12\n")
    (tmp_path / "README.md").write_text("# sample\n")

    intake = inspect_project(tmp_path)
    assert any(
        obs.subject == "nested-project" and obs.provenance.source_ref == "src"
        for obs in intake.observations
    ), "the fixture's owner-declared exclusion must actually apply"

    by_name = {d.dimension: d for d in synthesize_project_profile(intake).dimensions}
    deploy = by_name["operating.deploy-surface"]
    assert deploy.resolution is ProfileResolution.RESOLVED
    value = deploy.attributions[0].value
    assert value.startswith("none-observed"), value
    assert "nested project boundaries" in value and "src" in value, (
        "a 'none observed' claim created by an owner-declared exclusion must name "
        f"that exclusion rather than read as universal, got {value!r}"
    )


def test_c_a_path_hole_still_gates_filename_derived_absence(tmp_path: Path) -> None:
    """R1's guard rail. Splitting the content hole out of the exhaustiveness gate
    must not weaken the *path* holes: a depth limit, an entry limit, a
    containment refusal or an unobservable path means the walk never saw the
    ground at all — not even the filenames — so a filename-derived absence is
    exactly as unsound there as a content-derived one."""
    limits = TraversalLimits(
        max_depth=1, max_entries=1, max_file_bytes=1024, skipped_dir_names=[]
    )
    name_derived = (
        "operating.deploy-surface",
        "integration.config-surface",
        "testability.config-schema",
        "repository.package-metadata",
        "instruction.fragmentation",
    )
    holes = {
        "depth limit": dict(depth_limit_reached=True),
        "entry limit": dict(entry_limit_reached=True),
        "containment refusal": dict(entries_skipped_refused=1),
        "unobservable path": dict(entries_unobservable=1),
    }
    for label, hole in holes.items():
        fields = dict(
            entries_visited=1,
            entries_skipped=0,
            depth_limit_reached=False,
            entry_limit_reached=False,
            limits=limits,
        )
        fields.update(hole)
        stats = TraversalStats(**fields)
        profile = synthesize_project_profile(_minimal_intake(traversal_stats=stats))
        by_name = {d.dimension: d for d in profile.dimensions}
        for name in name_derived:
            assert by_name[name].resolution is ProfileResolution.UNKNOWN, (
                f"{name} published a filename-derived absence over a {label} — "
                "the walk never saw those filenames at all"
            )


# ---------------------------------------------------------------------------
# D. Conflict — one CONFLICTED dimension, attributions preserved
# ---------------------------------------------------------------------------


def test_d_disagreeing_declared_values_produce_one_conflicted_dimension() -> None:
    """Two sources genuinely disagree about `execution.autonomy`: one dimension,
    resolution=conflicted, both provenance-bearing attributions preserved —
    never last-write-wins, never highest-confidence-wins, never two dimensions."""
    finding_a = ClassificationFinding(
        dimension="execution.autonomy",
        value="suggest",
        provenance=Provenance(kind=ProvenanceKind.DECLARED, confidence=0.8, source_ref=".foundry/project.yaml"),
        evidence_refs=[".foundry/project.yaml"],
    )
    finding_b = ClassificationFinding(
        dimension="execution.autonomy",
        value="approved-apply",
        provenance=Provenance(kind=ProvenanceKind.INFERRED, confidence=0.4, source_ref="README.md"),
        evidence_refs=["README.md#L3"],
    )
    intake = _minimal_intake(classification_findings=[finding_a, finding_b])
    profile = synthesize_project_profile(intake)

    matching = [d for d in profile.dimensions if d.dimension == "execution.autonomy"]
    assert len(matching) == 1, "a genuine disagreement must not fork into two dimensions"
    dim = matching[0]
    assert dim.resolution is ProfileResolution.CONFLICTED
    values = {a.value for a in dim.attributions}
    assert values == {"suggest", "approved-apply"}
    kinds = {a.provenance.kind for a in dim.attributions}
    assert kinds == {ProvenanceKind.DECLARED, ProvenanceKind.INFERRED}
    by_value = {a.value: a for a in dim.attributions}
    assert by_value["suggest"].evidence_refs == [".foundry/project.yaml"]
    assert by_value["approved-apply"].evidence_refs == ["README.md#L3"]


def test_d_conflict_survives_round_trip() -> None:
    finding_a = ClassificationFinding(
        dimension="impact.external_effect",
        value="read-only",
        provenance=Provenance(kind=ProvenanceKind.DECLARED, source_ref="a"),
    )
    finding_b = ClassificationFinding(
        dimension="impact.external_effect",
        value="publication",
        provenance=Provenance(kind=ProvenanceKind.OBSERVED, source_ref="b"),
    )
    intake = _minimal_intake(classification_findings=[finding_a, finding_b])
    profile = synthesize_project_profile(intake)
    restored = load_json(ProjectProfile, dump_json(profile))
    dim = next(d for d in restored.dimensions if d.dimension == "impact.external_effect")
    assert dim.resolution is ProfileResolution.CONFLICTED
    assert {a.value for a in dim.attributions} == {"read-only", "publication"}


# ---------------------------------------------------------------------------
# E. Duplicate-name invariant — synthesizer never emits duplicates
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fixture", ALL_FIXTURES, ids=[p.name for p in ALL_FIXTURES])
def test_e_no_fixture_produces_duplicate_dimension_names(fixture: Path) -> None:
    profile = synthesize_project_profile(inspect_project(fixture))
    names = [d.dimension for d in profile.dimensions]
    assert len(names) == len(set(names)), f"duplicate dimension names for {fixture.name}: {names}"


def test_e_the_model_validator_still_rejects_a_hand_built_duplicate() -> None:
    """The synthesizer's own invariant is backstopped by the model's own guard."""
    intake = inspect_project(GREENFIELD)
    profile = synthesize_project_profile(intake)
    duplicated = [*profile.dimensions, profile.dimensions[0]]
    with pytest.raises(Exception):
        ProjectProfile(
            schema_version=profile.schema_version,
            project_name=profile.project_name,
            dimensions=duplicated,
            source_intake_ref=profile.source_intake_ref,
        )


# ---------------------------------------------------------------------------
# F. Provenance retained
# ---------------------------------------------------------------------------


def test_f_every_resolved_or_conflicted_attribution_carries_provenance() -> None:
    profile = synthesize_project_profile(inspect_project(BROWNFIELD))
    for dim in profile.dimensions:
        if dim.resolution is ProfileResolution.UNKNOWN:
            continue
        for attribution in dim.attributions:
            assert attribution.provenance.kind is not None
            # Every attribution states *where* it came from — a source_ref or a
            # non-empty evidence_refs list, never a bare unattributed claim.
            assert attribution.provenance.source_ref or attribution.evidence_refs, (
                f"{dim.dimension}: attribution {attribution.value!r} carries no "
                "source_ref and no evidence_refs"
            )


def test_f_declared_provenance_is_distinguishable_from_inferred_and_observed() -> None:
    profile = synthesize_project_profile(inspect_project(BROWNFIELD))
    by_name = {d.dimension: d for d in profile.dimensions}
    assert by_name["execution.autonomy"].attributions[0].provenance.kind is ProvenanceKind.DECLARED
    assert by_name["intake_mode"].attributions[0].provenance.kind is ProvenanceKind.DECLARED
    convention_dim = by_name["assurance.conventions-observed"]
    assert convention_dim.attributions[0].provenance.kind is ProvenanceKind.INFERRED


def test_f_a_declared_fact_aggregated_with_an_observed_one_is_never_republished_as_observed() -> None:
    """B2 regression: `repository.foundry-artifacts` unions an OBSERVED finding
    (`foundry-artifact`: the file exists) with a DECLARED one
    (`foundry-declaration`: the owner wrote it). The aggregate must report that
    disagreement in kind honestly — INFERRED, a derivation over heterogeneous
    sources — never silently collapse to OBSERVED and understate that an owner
    declaration is part of the evidence."""
    profile = synthesize_project_profile(inspect_project(BROWNFIELD))
    dim = next(d for d in profile.dimensions if d.dimension == "repository.foundry-artifacts")
    assert dim.resolution is ProfileResolution.RESOLVED
    attribution = dim.attributions[0]
    assert attribution.provenance.kind is ProvenanceKind.INFERRED
    assert attribution.provenance.kind is not ProvenanceKind.OBSERVED
    # And confidence must not be silently computed as a floor over only the
    # observations that happened to state one — the underlying observations
    # here carry no confidence at all, so the aggregate must carry none either.
    assert attribution.provenance.confidence is None


# ---------------------------------------------------------------------------
# G. Authority non-expansion
# ---------------------------------------------------------------------------


def test_g_profile_carries_no_field_that_could_move_an_authority_rank() -> None:
    """Structural guard: this duplicates the guard in
    test_models_project_profile.py deliberately — a regression in either module
    must be caught by both, since this suite is what a profile-synthesis change
    is actually reviewed against."""
    import typing

    from pydantic import BaseModel

    from agent_foundry.models.project import ProjectAuthority

    def model_types(annotation: object) -> list[type[BaseModel]]:
        found: list[type[BaseModel]] = []
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            found.append(annotation)
        for arg in typing.get_args(annotation):
            found.extend(model_types(arg))
        return found

    seen: set[type[BaseModel]] = set()
    queue: list[type[BaseModel]] = [ProjectProfile]
    offenders = []
    while queue:
        current = queue.pop()
        if current in seen:
            continue
        seen.add(current)
        for name, field in current.model_fields.items():
            if ProjectAuthority in model_types(field.annotation):
                offenders.append(f"{current.__name__}.{name}")
            for nested in model_types(field.annotation):
                if nested not in seen:
                    queue.append(nested)
    assert offenders == []


def test_g_plan_adoption_cannot_even_receive_a_projectprofile() -> None:
    """The structural half of the guarantee: `plan_adoption` takes no `profile`
    parameter and no `ProjectProfile`-typed parameter at all, in V0.2."""
    sig = inspect.signature(plan_adoption)
    assert "profile" not in sig.parameters
    assert not any(param.annotation is ProjectProfile for param in sig.parameters.values())


def test_g_varying_profile_only_evidence_cannot_move_plan_adoption_authority_ranks() -> None:
    """The property that matters: hold every `classification_finding` fixed — the
    only evidence `plan_adoption`/`synthesize_manifest` actually reads to decide
    `execution.autonomy` / `impact.external_effect` — and vary only evidence that
    feeds *profile-only* dimensions (here, `observations`). If a future change
    wired a profile-only dimension (e.g. `operating.deploy-surface`) into
    authority, this is exactly the shape of change that would move the rank;
    today it must not.

    This is deliberately *not* a monkeypatch of `plan_adoption` itself — the
    guarantee under test is that today's real `synthesize_manifest` ignores
    `observations` for authority-bearing fields, and stays that way. See the
    docstring note below the assertions for how this was checked to actually
    bite.
    """
    intake = inspect_project(BROWNFIELD)
    baseline_result = plan_adoption(intake)
    baseline_autonomy = autonomy_rank(baseline_result.manifest.execution.autonomy)
    baseline_external_effect = external_effect_rank(baseline_result.manifest.impact.external_effect)
    # Anti-vacuity: the fixture must actually carry a *declared* baseline, not an
    # unknown one, or "unchanged" would be trivially true.
    assert baseline_autonomy == autonomy_rank(Autonomy.SUGGEST)
    assert baseline_external_effect == external_effect_rank(ExternalEffectClass.READ_ONLY)

    baseline_profile = synthesize_project_profile(intake)

    # An observation that only ever feeds `operating.deploy-surface` (a
    # profile-only dimension) — classification_findings, and therefore the
    # manifest/authority path, are untouched.
    provocative_observation = ProjectObservation(
        subject="runtime-deploy-hint",
        content="deploy/runtime marker present: continuous-operation-cluster.yaml",
        provenance=Provenance(
            kind=ProvenanceKind.OBSERVED, confidence=1.0, source_ref="k8s/cluster.yaml"
        ),
    )
    varied_intake = intake.model_copy(
        update={"observations": [*intake.observations, provocative_observation]}
    )

    varied_profile = synthesize_project_profile(varied_intake)
    assert dump_json(varied_profile) != dump_json(baseline_profile), (
        "the varied evidence must actually change the synthesized profile "
        "(operating.deploy-surface) or this test proves nothing"
    )

    varied_result = plan_adoption(varied_intake)
    assert autonomy_rank(varied_result.manifest.execution.autonomy) == baseline_autonomy
    assert external_effect_rank(varied_result.manifest.impact.external_effect) == baseline_external_effect


# ---------------------------------------------------------------------------
# H. No project-type hard-coding — structural guard
# ---------------------------------------------------------------------------

_FORBIDDEN_CATEGORY_WORDS = (
    "backend",
    "frontend",
    "front-end",
    "back-end",
    "content",
    "finance",
    "trading",
    "blog",
    "web-app",
    "webapp",
    "web_app",
)


def test_h_no_dimension_echoes_the_authority_write_scope_declaration() -> None:
    """`authority.write_scope` is the one CLASSIFICATION_DIMENSIONS member the
    synthesizer deliberately never echoes (see the module docstring) — a
    repository write-scope path list is authority-shaped text, not something a
    descriptive profile should carry even though nothing in the model forbids
    it. This is the direct, evidence-backed check: without it, the exclusion
    only survives because the goldens would change if it were dropped."""
    for fixture in (GREENFIELD, BROWNFIELD):
        profile = synthesize_project_profile(inspect_project(fixture))
        offenders = [d.dimension for d in profile.dimensions if d.dimension.startswith("authority.")]
        assert offenders == [], f"{fixture.name}: unexpected authority-prefixed dimension(s): {offenders}"


def test_h_synthesizer_source_names_no_project_type_category() -> None:
    """A category *branch* would compare against a string literal naming the
    category (``== "content"``, a dict key ``"trading": ...``, and so on). This
    scans specifically for that shape — a quoted string literal spelling one of
    the forbidden category words — rather than any bare substring match, so it
    does not false-positive on legitimate identifiers this module already uses
    (``ProjectObservation.content``, for one)."""
    import re

    source = Path(inspect.getfile(profile_synth)).read_text(encoding="utf-8")
    lowered = source.lower()
    hits = [
        word
        for word in _FORBIDDEN_CATEGORY_WORDS
        if re.search(rf"""["']{re.escape(word)}["']""", lowered)
    ]
    assert hits == [], f"synthesizer source names forbidden project-type categories: {hits}"


def test_h_synthesizer_has_no_project_kind_parameter_or_branch_on_intake_mode_value() -> None:
    """The synthesizer must not special-case its output on IntakeMode (or any
    other closed classification value) beyond echoing the evidence verbatim: no
    function in this module may take a project 'kind'/'category' argument."""
    for _name, func in inspect.getmembers(profile_synth, inspect.isfunction):
        for param in inspect.signature(func).parameters.values():
            assert param.name not in {"project_kind", "project_category", "project_type"}


# ---------------------------------------------------------------------------
# I. API/CLI equivalence
# ---------------------------------------------------------------------------


def test_i_cli_profile_matches_api_output_json() -> None:
    api_payload = dump_json(synthesize_project_profile(inspect_project(BROWNFIELD)))
    completed = subprocess.run(
        [sys.executable, "-m", "agent_foundry", "profile", str(BROWNFIELD), "--format", "json"],
        cwd=REPO_ROOT,
        env=_subprocess_env(),
        capture_output=True,
        text=True,
        check=True,
    )
    assert completed.stdout.encode("utf-8") == api_payload


def test_i_cli_profile_yaml_round_trips_to_the_same_model() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "agent_foundry", "profile", str(BROWNFIELD), "--format", "yaml"],
        cwd=REPO_ROOT,
        env=_subprocess_env(),
        capture_output=True,
        text=True,
        check=True,
    )
    from agent_foundry.models import load_yaml

    cli_profile = load_yaml(ProjectProfile, completed.stdout.encode("utf-8"))
    api_profile = synthesize_project_profile(inspect_project(BROWNFIELD))
    assert dump_json(cli_profile) == dump_json(api_profile)


def test_i_cli_profile_does_not_mutate_the_target_project(tmp_path: Path) -> None:
    import shutil

    target = tmp_path / "project"
    shutil.copytree(GREENFIELD, target)

    def digest(root: Path) -> dict[str, str]:
        import hashlib

        return {
            p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*"))
            if p.is_file()
        }

    before = digest(target)
    subprocess.run(
        [sys.executable, "-m", "agent_foundry", "profile", str(target)],
        cwd=REPO_ROOT,
        env=_subprocess_env(),
        capture_output=True,
        text=True,
        check=True,
    )
    after = digest(target)
    assert before == after


def test_i_cli_help_lists_profile() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "agent_foundry", "--help"],
        cwd=REPO_ROOT,
        env=_subprocess_env(),
        capture_output=True,
        text=True,
        check=True,
    )
    assert "profile" in completed.stdout


def test_i_cli_profile_missing_project_path_reports_error() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "agent_foundry", "profile", str(REPO_ROOT / "does-not-exist")],
        cwd=REPO_ROOT,
        env=_subprocess_env(),
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1
    assert completed.stderr.strip()


# ---------------------------------------------------------------------------
# J. Golden profiles — deterministic and materially different
# ---------------------------------------------------------------------------


def test_j_greenfield_golden_profile_matches_committed_snapshot() -> None:
    profile = synthesize_project_profile(inspect_project(GREENFIELD))
    golden = (GOLDEN / "project_profile_greenfield.json").read_bytes()
    assert dump_json(profile) == golden


def test_j_brownfield_golden_profile_matches_committed_snapshot() -> None:
    profile = synthesize_project_profile(inspect_project(BROWNFIELD))
    golden = (GOLDEN / "project_profile_brownfield.json").read_bytes()
    assert dump_json(profile) == golden


def test_j_golden_profiles_are_materially_different_not_cosmetic_variants() -> None:
    greenfield = synthesize_project_profile(inspect_project(GREENFIELD))
    brownfield = synthesize_project_profile(inspect_project(BROWNFIELD))
    by_name_green = {d.dimension: d for d in greenfield.dimensions}
    by_name_brown = {d.dimension: d for d in brownfield.dimensions}

    assert set(by_name_green) == set(by_name_brown), "both profiles must cover the same dimension set"

    # Runtime/deploy shape differs.
    assert by_name_green["operating.deploy-surface"].resolution is ProfileResolution.RESOLVED
    assert by_name_green["operating.deploy-surface"].attributions[0].value == "none-observed"
    assert by_name_brown["operating.deploy-surface"].resolution is ProfileResolution.RESOLVED
    assert "Dockerfile" in by_name_brown["operating.deploy-surface"].attributions[0].value

    # External-effect surface: unknown vs. declared.
    assert by_name_green["impact.external_effect"].resolution is ProfileResolution.UNKNOWN
    assert by_name_brown["impact.external_effect"].resolution is ProfileResolution.RESOLVED

    # Testability/observability differs.
    assert by_name_green["testability.ci-entrypoint"].attributions[0].value == "none-observed"
    assert "ci.yml" in by_name_brown["testability.ci-entrypoint"].attributions[0].value

    # Instruction fragmentation differs.
    assert by_name_green["instruction.fragmentation"].attributions[0].value == (
        "no-agent-instruction-surface-observed"
    )
    brown_instructions = by_name_brown["instruction.fragmentation"].attributions[0].value
    assert "AGENTS.md" in brown_instructions and "CLAUDE.md" in brown_instructions

    # Integration surface differs.
    assert by_name_green["integration.config-surface"].attributions[0].value == "none-observed"
    assert by_name_brown["integration.config-surface"].resolution is ProfileResolution.RESOLVED

    # Unknown-region shape differs materially: greenfield leaves every risk/authority
    # -adjacent descriptive dimension unknown; brownfield resolves most of them.
    risk_dims = (
        "state.persistence",
        "impact.external_effect",
        "impact.reversibility",
        "execution.autonomy",
    )
    green_unknown = sum(
        1 for name in risk_dims if by_name_green[name].resolution is ProfileResolution.UNKNOWN
    )
    brown_unknown = sum(
        1 for name in risk_dims if by_name_brown[name].resolution is ProfileResolution.UNKNOWN
    )
    assert green_unknown == len(risk_dims)
    assert brown_unknown == 0


# ---------------------------------------------------------------------------
# K. Native V0.2 schema, not migration-dependent
# ---------------------------------------------------------------------------


def test_k_profile_carries_the_native_v02_schema_version_directly() -> None:
    from agent_foundry.models import FOUNDRY_SCHEMA_VERSION

    profile = synthesize_project_profile(inspect_project(BROWNFIELD))
    assert profile.schema_version == FOUNDRY_SCHEMA_VERSION
    assert FOUNDRY_SCHEMA_VERSION == "0.2"


def test_k_profile_loads_without_invoking_contract_migration() -> None:
    """A native-schema payload must validate straight through `load_json` with no
    migration path exercised — proving synthesis output isn't migration-dependent."""
    profile = synthesize_project_profile(inspect_project(BROWNFIELD))
    payload = dump_json(profile)
    restored = load_json(ProjectProfile, payload)
    assert restored.schema_version == "0.2"
    assert dump_json(restored) == payload


# ---------------------------------------------------------------------------
# L. Aggregate dimensions must not launder the provenance they aggregate
#    (SUE-580 review blocker B1)
# ---------------------------------------------------------------------------


def _convention(
    subject: str, *, confidence: float, kind: ProvenanceKind, source_ref: str
) -> ConventionSpec:
    return ConventionSpec(
        subject=subject,
        pattern=f"{subject} pattern",
        source_ref=source_ref,
        evidence=f"{subject} evidence",
        confidence=confidence,
        provenance=Provenance(kind=kind, confidence=confidence, source_ref=source_ref),
    )


def _conventions_dimension_of(*conventions: ConventionSpec):
    profile = synthesize_project_profile(_minimal_intake(conventions=list(conventions)))
    return next(
        d for d in profile.dimensions if d.dimension == "assurance.conventions-observed"
    )


def test_l_a_declared_convention_is_not_republished_as_inferred() -> None:
    """A dimension aggregating nothing but DECLARED facts must say DECLARED.

    The `test-invocation` fact here is parsed out of a build config by `tomllib`;
    reporting it as INFERRED is provenance laundering in the shipped artifact.
    """
    dim = _conventions_dimension_of(
        _convention(
            "test-invocation",
            confidence=0.8,
            kind=ProvenanceKind.DECLARED,
            source_ref="pyproject.toml",
        )
    )
    assert dim.resolution is ProfileResolution.RESOLVED
    attribution = dim.attributions[0]
    assert attribution.provenance.kind is ProvenanceKind.DECLARED
    assert attribution.provenance.confidence == 0.8


def test_l_a_prose_mention_does_not_drag_a_declared_fact_down_to_its_confidence() -> None:
    """Two conventions with *different subjects* are not competing claims.

    A DECLARED build-config fact (0.8) aggregated with a demoted prose mention of
    another subject (0.15) must not be republished at 0.15: `min()` across
    unrelated subjects is not a floor on anything a consumer can act on, and it
    made a consumer gating at >= 0.5 reject evidence that had just got better.
    Each subject is published with the strongest evidence that backs *it*.
    """
    dim = _conventions_dimension_of(
        _convention(
            "test-invocation",
            confidence=0.8,
            kind=ProvenanceKind.DECLARED,
            source_ref="pyproject.toml",
        ),
        _convention(
            "test-runner",
            confidence=0.15,
            kind=ProvenanceKind.INFERRED,
            source_ref="AGENTS.md",
        ),
    )
    # Co-existing conventions stay ONE composite fact — never CONFLICTED, which is
    # what one-attribution-per-subject would have produced.
    assert dim.resolution is ProfileResolution.RESOLVED
    assert len(dim.attributions) == 1
    attribution = dim.attributions[0]
    assert attribution.provenance.confidence == 0.8
    # Heterogeneous provenance is a derivation, so the aggregate kind is INFERRED —
    # but the per-subject truth is stated, not collapsed.
    assert attribution.provenance.kind is ProvenanceKind.INFERRED
    assert "test-invocation (declared 0.80)" in attribution.value
    assert "test-runner (inferred 0.15)" in attribution.value
    assert sorted(attribution.evidence_refs) == ["AGENTS.md", "pyproject.toml"]


def test_l_the_strongest_evidence_for_one_subject_wins_over_a_weaker_duplicate() -> None:
    """Within a single subject, a demoted mention co-existing with the structured
    declaration it was demoted *because of* must not become the reported strength."""
    dim = _conventions_dimension_of(
        _convention(
            "test-invocation",
            confidence=0.8,
            kind=ProvenanceKind.DECLARED,
            source_ref="Makefile",
        ),
        _convention(
            "test-invocation",
            confidence=0.15,
            kind=ProvenanceKind.INFERRED,
            source_ref="CLAUDE.md",
        ),
    )
    attribution = dim.attributions[0]
    assert attribution.value == "test-invocation (declared 0.80)"
    assert attribution.provenance.kind is ProvenanceKind.DECLARED
    assert attribution.provenance.confidence == 0.8


def test_l_no_subject_is_published_above_the_evidence_that_backs_it() -> None:
    """The other direction of the same rule: aggregating a strong fact must never
    lend its confidence to a weakly-evidenced subject. Every listed subject
    carries its own strength, so nothing gains confidence it did not earn."""
    dim = _conventions_dimension_of(
        _convention(
            "ci-checkout", confidence=1.0, kind=ProvenanceKind.OBSERVED, source_ref="ci.yml"
        ),
        _convention(
            "git-policy", confidence=0.5, kind=ProvenanceKind.INFERRED, source_ref="AGENTS.md"
        ),
    )
    value = dim.attributions[0].value
    assert "ci-checkout (observed 1.00)" in value
    assert "git-policy (inferred 0.50)" in value


# ---------------------------------------------------------------------------
# M. A classification finding derived from absence is gated by the same
#    exhaustiveness rule as a structural "none observed" (SUE-580 blocker B2)
# ---------------------------------------------------------------------------


def _entry_limited_stats() -> TraversalStats:
    limits = TraversalLimits(max_depth=8, max_entries=60, max_file_bytes=65536, skipped_dir_names=[])
    return TraversalStats(
        entries_visited=60,
        entries_skipped=0,
        depth_limit_reached=False,
        entry_limit_reached=True,
        limits=limits,
    )


def _greenfield_from_silence_finding() -> ClassificationFinding:
    from agent_foundry.inspect.classification import ABSENCE_ENUMERATION_REASON_PREFIXES

    return ClassificationFinding(
        dimension="intake_mode",
        value="greenfield",
        reason=ABSENCE_ENUMERATION_REASON_PREFIXES[0] + "CI workflow definitions",
        provenance=Provenance(kind=ProvenanceKind.INFERRED, confidence=0.55, source_ref="."),
        evidence_refs=[],
    )


def test_m_absence_derived_classification_finding_is_unknown_under_a_truncated_walk() -> None:
    """`intake_mode = greenfield` is chosen because a list of brownfield signals was
    checked and none seen. Under an entry-limited walk the signals may sit in the
    region never reached, so the profile must say UNKNOWN rather than publish the
    most confident possible phrasing of a fact it never observed."""
    intake = _minimal_intake(
        traversal_stats=_entry_limited_stats(),
        classification_findings=[_greenfield_from_silence_finding()],
    )
    dim = next(
        d
        for d in synthesize_project_profile(intake).dimensions
        if d.dimension == "intake_mode"
    )
    assert dim.resolution is ProfileResolution.UNKNOWN, (
        "an absence-enumerated intake_mode resolved from a walk that stopped at its "
        "entry limit — absence over unwalked ground is not evidence"
    )
    assert dim.attributions == []


def test_m_absence_derived_classification_finding_still_resolves_when_walk_exhaustive() -> None:
    """The counterpart: over a complete walk, "checked, none found" is a real
    observation and stays resolved."""
    intake = _minimal_intake(classification_findings=[_greenfield_from_silence_finding()])
    dim = next(
        d
        for d in synthesize_project_profile(intake).dimensions
        if d.dimension == "intake_mode"
    )
    assert dim.resolution is ProfileResolution.RESOLVED
    assert dim.attributions[0].value == "greenfield"


def test_m_a_positively_evidenced_finding_survives_a_truncated_walk() -> None:
    """Only absence-derived findings are gated: a truncated walk does not un-see
    what it did see, so a brownfield finding backed by signals it actually found
    still resolves."""
    finding = ClassificationFinding(
        dimension="intake_mode",
        value="brownfield",
        reason="4 of 5 brownfield signals present: CI workflow definitions",
        provenance=Provenance(kind=ProvenanceKind.INFERRED, confidence=0.8, source_ref="."),
        evidence_refs=[".github/workflows/ci.yml"],
    )
    intake = _minimal_intake(
        traversal_stats=_entry_limited_stats(), classification_findings=[finding]
    )
    dim = next(
        d
        for d in synthesize_project_profile(intake).dimensions
        if d.dimension == "intake_mode"
    )
    assert dim.resolution is ProfileResolution.RESOLVED
    assert dim.attributions[0].value == "brownfield"


def test_m_declared_intake_mode_is_not_gated_by_a_truncated_walk() -> None:
    """An owner's declaration is evidence the walk read, not a claim about ground
    it missed."""
    declared = ClassificationFinding(
        dimension="intake_mode",
        value="brownfield",
        reason="declared in .foundry/project.yaml",
        provenance=Provenance(kind=ProvenanceKind.DECLARED, source_ref=".foundry/project.yaml"),
        evidence_refs=[".foundry/project.yaml"],
    )
    intake = _minimal_intake(
        traversal_stats=_entry_limited_stats(), classification_findings=[declared]
    )
    dim = next(
        d
        for d in synthesize_project_profile(intake).dimensions
        if d.dimension == "intake_mode"
    )
    assert dim.resolution is ProfileResolution.RESOLVED
    assert dim.attributions[0].provenance.kind is ProvenanceKind.DECLARED
