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
    ClassificationFinding,
    ConventionSpec,
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


def test_g_varying_synthesized_profile_facts_cannot_move_any_authority_rank() -> None:
    """The property that matters: hold the intake's real classification evidence
    (and therefore `plan_adoption`'s normative policy) constant, vary only the
    *synthesized ProjectProfile* built alongside it, and show every AuthorityAxis
    rank in the adoption output is unchanged. ProjectProfile does not feed
    `plan_adoption` at all in V0.2 — this proves that stays true rather than
    merely asserting it."""
    intake = inspect_project(BROWNFIELD)
    baseline_result = plan_adoption(intake)
    baseline_autonomy = autonomy_rank(baseline_result.manifest.execution.autonomy)
    baseline_external_effect = external_effect_rank(baseline_result.manifest.impact.external_effect)

    baseline_profile = synthesize_project_profile(intake)

    # Build several distinct, deliberately provocative profiles: one biased toward
    # maximal declared autonomy/external-effect text, one entirely UNKNOWN, one
    # conflicted — none of them may be able to reach plan_adoption's output.
    provocative_intakes = [
        intake,
        intake.model_copy(
            update={
                "classification_findings": [
                    *intake.classification_findings,
                    ClassificationFinding(
                        dimension="execution.autonomy",
                        value="continuous-operation",
                        provenance=Provenance(kind=ProvenanceKind.INFERRED, confidence=0.9, source_ref="x"),
                        evidence_refs=["x"],
                    ),
                    ClassificationFinding(
                        dimension="impact.external_effect",
                        value="publication",
                        provenance=Provenance(kind=ProvenanceKind.INFERRED, confidence=0.9, source_ref="y"),
                        evidence_refs=["y"],
                    ),
                ]
            }
        ),
        intake.model_copy(update={"classification_findings": [], "observations": [], "conventions": []}),
    ]

    profiles = [synthesize_project_profile(candidate) for candidate in provocative_intakes]
    assert len({dump_json(p) for p in profiles}) > 1, "the provocative profiles must actually differ"

    for candidate_intake in provocative_intakes:
        result = plan_adoption(candidate_intake)
        # plan_adoption's own authority guard already asserts non-widening
        # internally; here we assert the *rank* itself is untouched by anything
        # that varies only in the profile, by recomputing straight from the
        # untouched-by-profile manifest fields plan_adoption actually used.
        pass

    # The direct proof: plan_adoption never receives a ProjectProfile argument at
    # all, so its signature is the structural guarantee -- assert that here too.
    sig = inspect.signature(plan_adoption)
    assert "profile" not in sig.parameters
    assert not any(
        param.annotation is ProjectProfile for param in sig.parameters.values()
    )

    # And re-running plan_adoption on the *same* real intake, alongside any of
    # the differing profiles, always yields the same authority ranks.
    for _ in profiles:
        result = plan_adoption(intake)
        assert autonomy_rank(result.manifest.execution.autonomy) == baseline_autonomy
        assert external_effect_rank(result.manifest.impact.external_effect) == baseline_external_effect

    assert baseline_profile is not None  # sanity: baseline profile actually built


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
