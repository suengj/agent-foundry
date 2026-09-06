"""Evidence-backed inspection/profile truth across representative project shapes.

SUE-580's Required Evidence asks for "Representative Python, Node/static-site,
docs/content and runtime-service fixtures." Python is already covered by
`greenfield-minimal` and `brownfield-sample` (see `test_inspect.py` and
`test_profile_synthesis.py`). This module adds the three missing shapes —
`node-static-site`, `docs-content-handbook`, `runtime-service-sample` — and
proves two things about each, in the letter of the non-negotiable rules this
work item states:

1. **A false convention is worse than a missing convention.** Where a fixture
   genuinely carries no test convention the pipeline can honestly claim (the
   Node fixture's real `package.json` test script does not invoke pytest; the
   runtime-service fixture has no test harness at all), the assertion is that
   none is claimed — never that a plausible-looking one was invented.
2. **The four shapes are materially distinguishable**, not cosmetic variants
   of each other: different convention subjects, different classification
   provenance (INFERRED vs. DECLARED), different profile-dimension resolution
   counts, all traced to real, quoted evidence.

Every number and string asserted here was read off an actual
`inspect_project` / `synthesize_project_profile` run against the fixture in
this repository, not invented ahead of time — see the module for the fixture
contents each assertion is keyed to.
"""

from __future__ import annotations

from pathlib import Path

from agent_foundry.inspect import inspect_project
from agent_foundry.inspect.classification import CLASSIFICATION_DIMENSIONS
from agent_foundry.inspect.conventions import TEST_INVOCATION_SUBJECT, TEST_RUNNER_SUBJECT
from agent_foundry.models.common import ProfileResolution, ProvenanceKind
from agent_foundry.profile import synthesize_project_profile

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "projects"

GREENFIELD = FIXTURES / "greenfield-minimal"
BROWNFIELD = FIXTURES / "brownfield-sample"
NODE_STATIC_SITE = FIXTURES / "node-static-site"
DOCS_CONTENT = FIXTURES / "docs-content-handbook"
RUNTIME_SERVICE = FIXTURES / "runtime-service-sample"

_NON_WRITE_SCOPE_DIMENSIONS = tuple(d for d in CLASSIFICATION_DIMENSIONS if d != "authority.write_scope")


def _profile_by_name(root: Path):
    intake = inspect_project(root)
    profile = synthesize_project_profile(intake)
    return intake, profile, {d.dimension: d for d in profile.dimensions}


# ---------------------------------------------------------------------------
# Node / static-site
# ---------------------------------------------------------------------------


def test_node_static_site_no_structured_test_invocation_is_claimed() -> None:
    """package.json declares a real `test` script — `node run-checks.js` — that
    is a genuine content check for the site, but it does not invoke pytest.
    The structured-convention detector only recognises a pytest invocation, so
    it must claim nothing here rather than promoting an unrelated script to a
    'test-invocation' convention. Absence, not invention, is the correct
    answer."""
    intake = inspect_project(NODE_STATIC_SITE)
    assert not [c for c in intake.conventions if c.subject == TEST_INVOCATION_SUBJECT]


def test_node_static_site_no_test_runner_mention_despite_instruction_to_run_tests() -> None:
    """AGENTS.md explicitly says to run `npm test` before submitting changes —
    a real, actionable test instruction — but the mention detector only looks
    for the literal word 'pytest'. It must not read 'npm test' as a pytest
    mention; the correct output is no test-runner convention at all."""
    intake = inspect_project(NODE_STATIC_SITE)
    assert not [c for c in intake.conventions if c.subject == TEST_RUNNER_SUBJECT]


def test_node_static_site_conventions_are_exactly_ci_checkout_and_git_policy() -> None:
    intake = inspect_project(NODE_STATIC_SITE)
    by_subject = {c.subject: c for c in intake.conventions}
    assert set(by_subject) == {"ci-checkout", "git-policy"}

    ci = by_subject["ci-checkout"]
    assert ci.source_ref == ".github/workflows/ci.yml"
    assert "actions/checkout@v4" in ci.evidence
    assert ci.provenance.kind is ProvenanceKind.INFERRED

    git_policy = by_subject["git-policy"]
    assert git_policy.source_ref == "AGENTS.md"
    assert git_policy.evidence == "Do not commit the build output directory."
    assert git_policy.provenance.kind is ProvenanceKind.INFERRED


def test_node_static_site_intake_mode_inferred_brownfield_from_named_signals() -> None:
    intake = inspect_project(NODE_STATIC_SITE)
    finding = next(f for f in intake.classification_findings if f.dimension == "intake_mode")
    assert finding.value == "brownfield"
    assert finding.provenance.kind is ProvenanceKind.INFERRED
    # 3 of 5 signals: a >=3-file source tree, CI workflow definitions, and
    # >=8 source files (this fixture's src/ + top-level *.js tooling files).
    assert finding.provenance.confidence == 0.7
    assert "source tree with at least three source files" in finding.reason
    assert "CI workflow definitions" in finding.reason
    assert "at least eight source files" in finding.reason
    # The signals this fixture does *not* trip must not be claimed present.
    assert "existing Foundry artifacts" not in finding.reason
    assert "deploy or runtime manifest" not in finding.reason


def test_node_static_site_lint_marker_resolves_via_eslint_not_python_markers() -> None:
    _, _, by = _profile_by_name(NODE_STATIC_SITE)
    dim = by["testability.lint-type-entrypoint"]
    assert dim.resolution is ProfileResolution.RESOLVED
    assert dim.attributions[0].value == "lint/type marker present: eslint.config.js"


def test_node_static_site_package_metadata_includes_lockfile_and_manifest() -> None:
    _, _, by = _profile_by_name(NODE_STATIC_SITE)
    dim = by["repository.package-metadata"]
    assert dim.resolution is ProfileResolution.RESOLVED
    value = dim.attributions[0].value
    assert "package.json" in value
    assert "package-lock.json" in value


def test_node_static_site_test_entrypoint_is_correctly_none_observed_not_unknown() -> None:
    """No pytest.ini/tox.ini/conftest.py/.coveragerc marker exists — genuinely
    true for this fixture — and the traversal is exhaustive, so the dimension
    must resolve to an observed absence rather than fall back to UNKNOWN."""
    _, _, by = _profile_by_name(NODE_STATIC_SITE)
    dim = by["testability.test-entrypoint"]
    assert dim.resolution is ProfileResolution.RESOLVED
    assert dim.attributions[0].value == "none-observed"
    assert dim.attributions[0].provenance.kind is ProvenanceKind.OBSERVED


def test_node_static_site_undeclared_classification_dimensions_are_unknown() -> None:
    """No `.foundry/project.yaml` exists in this fixture, so every dimension
    besides `intake_mode` must resolve UNKNOWN — never a guess drawn from the
    presence of JS tooling."""
    _, _, by = _profile_by_name(NODE_STATIC_SITE)
    for dimension in _NON_WRITE_SCOPE_DIMENSIONS:
        if dimension == "intake_mode":
            continue
        assert by[dimension].resolution is ProfileResolution.UNKNOWN, dimension


# ---------------------------------------------------------------------------
# docs/content
# ---------------------------------------------------------------------------


def test_docs_content_no_conventions_observed_is_the_correct_answer() -> None:
    """This fixture has no Makefile, no CI, no package manifest, and no agent
    instruction surface — there is genuinely nothing for the convention
    detectors to find. The correct output is an explicit, evidenced
    'no-conventions-observed' fact, not silence and not a fabricated one."""
    intake, _, by = _profile_by_name(DOCS_CONTENT)
    assert intake.conventions == []
    dim = by["assurance.conventions-observed"]
    assert dim.resolution is ProfileResolution.RESOLVED
    assert dim.attributions[0].value == "no-conventions-observed"
    assert dim.attributions[0].provenance.kind is ProvenanceKind.OBSERVED
    assert dim.attributions[0].provenance.confidence == 1.0


def test_docs_content_intake_mode_inferred_greenfield_at_low_confidence() -> None:
    """No brownfield signal fires for a prose-only repository — there is no
    code tree, no CI, no Foundry artifact, and no deploy manifest — so the
    heuristic reports greenfield, but at its lowest, no-signal confidence
    (0.55), not as a confident claim about the project's nature."""
    intake = inspect_project(DOCS_CONTENT)
    finding = next(f for f in intake.classification_findings if f.dimension == "intake_mode")
    assert finding.value == "greenfield"
    assert finding.provenance.kind is ProvenanceKind.INFERRED
    assert finding.provenance.confidence == 0.55
    assert "no brownfield signals present" in finding.reason


def test_docs_content_structural_dimensions_resolve_to_observed_absence() -> None:
    """Every structural presence/absence dimension this fixture genuinely has
    no marker for must resolve RESOLVED with a 'none-observed'-shaped value —
    the traversal is small and exhaustive, so absence is directly observed,
    not merely un-investigated."""
    _, _, by = _profile_by_name(DOCS_CONTENT)
    for dimension, expected_value in (
        ("repository.package-metadata", "none-observed"),
        ("repository.ownership-boundaries", "no-nested-project-boundaries-observed"),
        ("repository.foundry-artifacts", "none-observed"),
        ("testability.test-entrypoint", "none-observed"),
        ("testability.lint-type-entrypoint", "none-observed"),
        ("testability.ci-entrypoint", "none-observed"),
        ("testability.config-schema", "none-observed"),
        ("operating.deploy-surface", "none-observed"),
        ("integration.config-surface", "none-observed"),
        ("instruction.fragmentation", "no-agent-instruction-surface-observed"),
    ):
        dim = by[dimension]
        assert dim.resolution is ProfileResolution.RESOLVED, dimension
        assert dim.attributions[0].value == expected_value, dimension
        assert dim.attributions[0].provenance.kind is ProvenanceKind.OBSERVED, dimension


def test_docs_content_undeclared_classification_dimensions_are_unknown() -> None:
    _, _, by = _profile_by_name(DOCS_CONTENT)
    for dimension in _NON_WRITE_SCOPE_DIMENSIONS:
        if dimension == "intake_mode":
            continue
        assert by[dimension].resolution is ProfileResolution.UNKNOWN, dimension


def test_docs_content_prose_docs_are_not_read_as_agent_instruction_surface() -> None:
    """`docs/guide/*.md` is ordinary prose content, not `docs/ai/*.md` (the
    agent-facing doc path) and not one of the recognised AGENTS.md/CLAUDE.md
    instruction files — it must not be counted as an instruction surface or
    project-doc observation."""
    intake = inspect_project(DOCS_CONTENT)
    subjects = {obs.subject for obs in intake.observations}
    assert "agent-instruction-surface" not in subjects
    assert "project-docs" not in subjects


# ---------------------------------------------------------------------------
# runtime-service
# ---------------------------------------------------------------------------


def test_runtime_service_declared_classification_matches_owner_manifest() -> None:
    """Every dimension the owner declared in `.foundry/project.yaml` must come
    through as DECLARED, at the declared value, sourced to that file — the
    highest-precedence evidence there is."""
    _, _, by = _profile_by_name(RUNTIME_SERVICE)
    expected = {
        "intake_mode": "brownfield",
        "project.name": "sample-runtime-service",
        "primary_work_mode": "operate",
        "state.persistence": "persistent-shared-external",
        "state.temporal_mode": "continuous",
        "impact.external_effect": "runtime-mutation",
        "impact.reversibility": "rollback-required",
        "impact.consequence": "high",
        "execution.autonomy": "bounded-external-write",
        "execution.ambiguity": "bounded-judgment",
        "execution.concurrency": "coordinated-graph",
        "assurance.required": "runtime-readback",
        "access.sensitivity": "confidential",
    }
    for dimension, value in expected.items():
        dim = by[dimension]
        assert dim.resolution is ProfileResolution.RESOLVED, dimension
        assert dim.attributions[0].value == value, dimension
        assert dim.attributions[0].provenance.kind is ProvenanceKind.DECLARED, dimension
        assert dim.attributions[0].provenance.source_ref == ".foundry/project.yaml", dimension
    # primary_artifact was left out of the manifest on purpose, and must stay
    # UNKNOWN rather than being guessed from the deploy/runtime evidence.
    assert by["primary_artifact"].resolution is ProfileResolution.UNKNOWN


def test_runtime_service_deploy_surface_observes_both_runtime_markers() -> None:
    _, _, by = _profile_by_name(RUNTIME_SERVICE)
    dim = by["operating.deploy-surface"]
    assert dim.resolution is ProfileResolution.RESOLVED
    value = dim.attributions[0].value
    assert "Dockerfile" in value
    assert "docker-compose.yml" in value
    assert dim.attributions[0].provenance.kind is ProvenanceKind.OBSERVED


def test_runtime_service_integration_config_surface_names_file_not_contents() -> None:
    """The external-effect/credential surface (`env.example`) must be recorded
    as a filename-presence fact — never anything drawn from the placeholder
    value inside it (which is a synthetic `replace-me`, never a real secret)."""
    intake, _, by = _profile_by_name(RUNTIME_SERVICE)
    dim = by["integration.config-surface"]
    assert dim.resolution is ProfileResolution.RESOLVED
    value = dim.attributions[0].value
    assert "env.example" in value
    assert "replace-me" not in value
    obs = next(o for o in intake.observations if o.subject == "integration-config")
    assert "replace-me" not in obs.content


def test_runtime_service_has_no_test_entrypoint_and_makes_no_test_claim() -> None:
    """This fixture deliberately carries no test harness at all — it exists to
    exercise deploy/runtime and external-effect evidence, not testability
    evidence. The pipeline must report the genuine absence, and must not
    surface a test-invocation or test-runner convention from anywhere."""
    intake, _, by = _profile_by_name(RUNTIME_SERVICE)
    dim = by["testability.test-entrypoint"]
    assert dim.resolution is ProfileResolution.RESOLVED
    assert dim.attributions[0].value == "none-observed"
    subjects = {c.subject for c in intake.conventions}
    assert TEST_INVOCATION_SUBJECT not in subjects
    assert TEST_RUNNER_SUBJECT not in subjects


def test_runtime_service_conventions_are_exactly_ci_checkout() -> None:
    intake = inspect_project(RUNTIME_SERVICE)
    subjects = {c.subject for c in intake.conventions}
    assert subjects == {"ci-checkout"}


# ---------------------------------------------------------------------------
# Cross-shape material distinguishability
# ---------------------------------------------------------------------------

_SHAPE_FIXTURES = {
    "greenfield-minimal": GREENFIELD,
    "brownfield-sample": BROWNFIELD,
    "node-static-site": NODE_STATIC_SITE,
    "docs-content-handbook": DOCS_CONTENT,
    "runtime-service-sample": RUNTIME_SERVICE,
}

# The exact convention-subject set each shape produces. Hand-derived from an
# actual `inspect_project` run against each fixture (see the module docstring)
# — this is a fixed expectation of *this test*, not a second implementation
# of convention discovery, and any real change to discovery behaviour should
# make exactly these lines fail rather than pass silently.
_EXPECTED_CONVENTION_SUBJECTS = {
    "greenfield-minimal": frozenset({"test-invocation"}),
    "brownfield-sample": frozenset({"ci-checkout", "git-policy", "test-invocation", "test-runner"}),
    "node-static-site": frozenset({"ci-checkout", "git-policy"}),
    "docs-content-handbook": frozenset(),
    "runtime-service-sample": frozenset({"ci-checkout"}),
}


def test_convention_subject_sets_match_expected_and_are_all_pairwise_distinct() -> None:
    actual = {
        name: frozenset(c.subject for c in inspect_project(path).conventions)
        for name, path in _SHAPE_FIXTURES.items()
    }
    assert actual == _EXPECTED_CONVENTION_SUBJECTS
    names = list(actual)
    for i, left in enumerate(names):
        for right in names[i + 1 :]:
            assert actual[left] != actual[right], (
                f"{left} and {right} produced the same convention-subject set "
                f"{actual[left]!r} — the shapes are not materially distinguishable"
            )


def test_resolved_classification_dimension_counts_distinguish_declared_from_undeclared_shapes() -> None:
    """A shape with an owner declaration (brownfield-sample, runtime-service)
    resolves nearly every classification dimension; a shape with none
    (greenfield-minimal, node-static-site, docs-content-handbook) resolves
    only `intake_mode`. The count itself is the distinguishing evidence, not
    merely the presence of *a* value somewhere."""
    counts = {}
    for name, path in _SHAPE_FIXTURES.items():
        _, _, by = _profile_by_name(path)
        counts[name] = sum(
            1
            for dimension in _NON_WRITE_SCOPE_DIMENSIONS
            if by[dimension].resolution is ProfileResolution.RESOLVED
        )
    assert counts == {
        "greenfield-minimal": 1,
        "brownfield-sample": 14,
        "node-static-site": 1,
        "docs-content-handbook": 1,
        "runtime-service-sample": 14,
    }


def test_intake_mode_provenance_kind_distinguishes_declared_from_inferred_shapes() -> None:
    kinds = {}
    for name, path in _SHAPE_FIXTURES.items():
        finding = next(
            f for f in inspect_project(path).classification_findings if f.dimension == "intake_mode"
        )
        kinds[name] = finding.provenance.kind
    assert kinds == {
        "greenfield-minimal": ProvenanceKind.INFERRED,
        "brownfield-sample": ProvenanceKind.DECLARED,
        "node-static-site": ProvenanceKind.INFERRED,
        "docs-content-handbook": ProvenanceKind.INFERRED,
        "runtime-service-sample": ProvenanceKind.DECLARED,
    }


def test_every_new_fixture_synthesizes_without_duplicate_dimensions() -> None:
    """Baseline sanity shared with `test_profile_synthesis.py`'s fixture-wide
    checks (auto-discovered there via directory iteration): every new fixture
    must still produce a profile with no duplicate dimension name and must be
    deterministic on repeat synthesis."""
    for path in (NODE_STATIC_SITE, DOCS_CONTENT, RUNTIME_SERVICE):
        intake = inspect_project(path)
        profile = synthesize_project_profile(intake)
        names = [d.dimension for d in profile.dimensions]
        assert len(names) == len(set(names)), path.name
        assert synthesize_project_profile(intake) == synthesize_project_profile(intake)
