"""Deterministic ProjectProfile synthesis from read-only inspection evidence.

**Descriptive project truth, not normative authority.** This module answers "how
does this project appear to operate, based on observable evidence?" and nothing
else. It never answers "what is this agent authorized to do?" — that question is
answered elsewhere (``adopt.manifest`` / ``adopt.authority``), from a different
evidence path, and this module does not feed that path. A ``ProjectProfile`` built
here carries no field an authority decision could be read off of; see
``tests/test_models_project_profile.py`` for the structural guard and
``tests/test_profile_synthesis.py`` for the proof that varying synthesized facts
cannot move an authority rank.

**Evidence sources.** Every profile dimension traces to one of the existing,
already-verified ``ProjectIntake`` evidence producers — never a parallel
observation model:

* ``intake.classification_findings`` — for every member of
  ``agent_foundry.inspect.classification.CLASSIFICATION_DIMENSIONS`` except
  ``authority.write_scope`` (a repository write-scope list is authority-shaped
  text; a descriptive profile leaves it alone on purpose, even though nothing in
  the ``ProjectProfile`` field tree would technically forbid echoing it). Reusing
  that upstream vocabulary directly, rather than re-listing it here, means a future
  classification dimension is picked up automatically instead of silently missing.
* ``intake.observations`` — for structural presence facts (test/lint/CI markers,
  deploy hints, integration config, package metadata, nested-project boundaries,
  agent instruction surfaces, and so on), grouped by the fixed observation
  ``subject`` vocabulary the inspector's collectors already emit.
* ``intake.conventions`` — for a compact summary of which convention categories
  were discovered.
* ``intake.traversal_stats`` — both to gate "absence" claims (see below) and to
  report the walk's own coverage as first-class dimensions.

**No project-type hard-coding.** Every dimension above is either (a) a direct,
1:1 echo of a fixed evidence field defined upstream in ``inspect/``, or (b) a
structural presence/absence fact keyed by that same fixed vocabulary. There is no
branch anywhere in this module keyed on an inferred project *category* (a
a named domain or application-shape label of any kind), and no lookup table that
amounts to one — see ``tests/test_profile_synthesis.py`` (test H) for the
structural guard that keeps it that way.

**Absence is not evidence, with one narrow, structural exception.** For every
dimension sourced from ``classification_findings`` (state, impact, execution,
assurance, access, work-mode, artifact, intake-mode facts), the *complete*
absence of a valued finding always yields ``UNKNOWN`` — never a value guessed
from silence, regardless of how much of the tree was walked. The one exception is
a small family of purely structural "is file/marker X present anywhere in the
walked tree" dimensions (test harness markers, CI workflow files, deploy hints,
and so on): here, and only when the traversal was *exhaustive* (see
``_traversal_exhaustive``), "no such marker was observed" is itself a directly
observed fact about the tree that was actually walked in full — not a claim about
safety, risk, or authority, and not drawn from a *partial* walk. When the walk hit
a depth/entry limit or left any path unobservable, these dimensions fall back to
``UNKNOWN`` exactly like every other one: an unexplored subtree might hold
anything.

**Determinism.** Same structured evidence -> byte-identical ``ProjectProfile``.
Every dict/set-shaped collection this module touches — findings grouped by
dimension, distinct attribution values, evidence-ref lists, convention subjects —
is walked into an explicitly sorted list before it reaches a model field; nothing
here relies on dict insertion order, set iteration order, or the order
``ProjectIntake``'s lists happen to arrive in. See
``tests/test_profile_synthesis.py`` for the shuffle-based ordering-robustness
proof (test B) and the direct byte-identity proof (test A).
"""

from __future__ import annotations

from agent_foundry.models.base import FOUNDRY_SCHEMA_VERSION
from agent_foundry.models.common import Provenance, ProvenanceKind
from agent_foundry.models.common import ProfileResolution
from agent_foundry.models.project import (
    ClassificationFinding,
    ConventionSpec,
    ProfileAttribution,
    ProfileDimension,
    ProjectIntake,
    ProjectObservation,
    ProjectProfile,
    TraversalStats,
)
from agent_foundry.inspect.classification import CLASSIFICATION_DIMENSIONS

# `authority.write_scope` is deliberately never echoed into a profile dimension.
# Every other CLASSIFICATION_DIMENSIONS member is descriptive; this one names a
# repository write-scope list, and a descriptive-truth contract stays clean of
# anything shaped like an authority grant even when nothing in the model would
# technically forbid it.
_CLASSIFICATION_EXCLUDED_DIMENSIONS: frozenset[str] = frozenset({"authority.write_scope"})

_NONE_OBSERVED_DEFAULT = "none-observed"


# ---------------------------------------------------------------------------
# Small shared helpers — every sort below is explicit and total.
# ---------------------------------------------------------------------------


def _attribution_sort_key(attribution: ProfileAttribution) -> tuple:
    provenance = attribution.provenance
    return (
        attribution.value,
        provenance.kind.value,
        -1.0 if provenance.confidence is None else provenance.confidence,
        provenance.source_ref or "",
        tuple(attribution.evidence_refs),
    )


def _make_attribution(
    value: str, provenance: Provenance, evidence_refs: list[str] | set[str]
) -> ProfileAttribution:
    return ProfileAttribution(
        value=value,
        provenance=provenance,
        evidence_refs=sorted(set(evidence_refs)),
    )


def _dedup_attributions(rows: list[ProfileAttribution]) -> list[ProfileAttribution]:
    """Collapse identical (value, provenance, evidence_refs) rows, then sort.

    Two evidence items proposing the *same* fact with the *same* provenance are one
    attribution, not two — but two proposals that differ in provenance, confidence,
    or evidence_refs stay distinct even when their value string is identical, so no
    provenance is silently dropped.
    """
    seen: dict[tuple, ProfileAttribution] = {}
    for attribution in rows:
        key = (
            attribution.value,
            attribution.provenance.kind.value,
            attribution.provenance.confidence,
            attribution.provenance.source_ref,
            tuple(attribution.evidence_refs),
        )
        seen.setdefault(key, attribution)
    return sorted(seen.values(), key=_attribution_sort_key)


def _dimension(name: str, attributions: list[ProfileAttribution]) -> ProfileDimension:
    deduped = _dedup_attributions(attributions)
    if not deduped:
        return ProfileDimension(dimension=name, resolution=ProfileResolution.UNKNOWN, attributions=[])
    distinct_values = {attribution.value for attribution in deduped}
    resolution = (
        ProfileResolution.RESOLVED if len(distinct_values) == 1 else ProfileResolution.CONFLICTED
    )
    return ProfileDimension(dimension=name, resolution=resolution, attributions=deduped)


def _traversal_exhaustive(stats: TraversalStats) -> bool:
    """True only when the walk covered the whole tree within its own bounds.

    Only then may "no marker of kind X was found" be reported as a resolved
    structural fact. When the walk was truncated or left a path unobservable,
    absence proves nothing about the unexamined region, so callers must fall back
    to UNKNOWN instead.
    """
    return (
        not stats.depth_limit_reached
        and not stats.entry_limit_reached
        and stats.entries_unobservable == 0
    )


# ---------------------------------------------------------------------------
# classification_findings -> profile dimensions (generic, 1:1, data-driven)
# ---------------------------------------------------------------------------


def _classification_dimension(name: str, findings: list[ClassificationFinding]) -> ProfileDimension:
    attributions = [
        _make_attribution(finding.value, finding.provenance, finding.evidence_refs)
        for finding in findings
        if finding.value is not None
    ]
    return _dimension(name, attributions)


def _group_classification_findings(
    findings: list[ClassificationFinding],
) -> dict[str, list[ClassificationFinding]]:
    grouped: dict[str, list[ClassificationFinding]] = {}
    for finding in findings:
        grouped.setdefault(finding.dimension, []).append(finding)
    return grouped


# ---------------------------------------------------------------------------
# observations -> aggregate structural-presence dimensions
# ---------------------------------------------------------------------------


def _aggregate_observation_dimension(
    name: str,
    observations: list[ProjectObservation],
    subjects: frozenset[str],
    *,
    stats: TraversalStats,
    none_observed_value: str = _NONE_OBSERVED_DEFAULT,
) -> ProfileDimension:
    matches = [obs for obs in observations if obs.subject in subjects]
    if not matches:
        if not _traversal_exhaustive(stats):
            return ProfileDimension(dimension=name, resolution=ProfileResolution.UNKNOWN, attributions=[])
        provenance = Provenance(kind=ProvenanceKind.OBSERVED, confidence=1.0, source_ref=".")
        return _dimension(name, [_make_attribution(none_observed_value, provenance, [])])

    value = "; ".join(sorted({obs.content for obs in matches}))
    kinds = {obs.provenance.kind for obs in matches}
    kind = next(iter(kinds)) if len(kinds) == 1 else ProvenanceKind.OBSERVED
    confidences = [obs.provenance.confidence for obs in matches if obs.provenance.confidence is not None]
    confidence = min(confidences) if confidences else None
    evidence_refs = sorted({obs.provenance.source_ref for obs in matches if obs.provenance.source_ref})
    source_ref = evidence_refs[0] if len(evidence_refs) == 1 else None
    provenance = Provenance(kind=kind, confidence=confidence, source_ref=source_ref)
    return _dimension(name, [_make_attribution(value, provenance, evidence_refs)])


def _repository_structure_dimension(
    observations: list[ProjectObservation], *, stats: TraversalStats
) -> ProfileDimension:
    # `collect_structure_observations` always emits at least the visited-count
    # observation for any directory that was inspected at all, so the "no
    # observation at all" branch below is unreachable in practice — but the
    # dimension still uses the same join-into-one-fact aggregate as every other
    # structural dimension: "N files, M directories" and "top-level entries: ..."
    # are two co-existing facts about the same tree, not competing alternatives,
    # so they must never be read as CONFLICTED.
    return _aggregate_observation_dimension(
        "repository.structure",
        observations,
        frozenset({"repository-structure"}),
        stats=stats,
    )


def _repository_revision_dimension(
    observations: list[ProjectObservation], *, stats: TraversalStats
) -> ProfileDimension:
    return _aggregate_observation_dimension(
        "repository.revision",
        observations,
        frozenset({"repository-revision"}),
        stats=stats,
    )


def _conventions_dimension(conventions: list[ConventionSpec], *, stats: TraversalStats) -> ProfileDimension:
    name = "assurance.conventions-observed"
    if not conventions:
        if not _traversal_exhaustive(stats):
            return ProfileDimension(dimension=name, resolution=ProfileResolution.UNKNOWN, attributions=[])
        provenance = Provenance(kind=ProvenanceKind.OBSERVED, confidence=1.0, source_ref=".")
        return _dimension(name, [_make_attribution("no-conventions-observed", provenance, [])])

    value = ", ".join(sorted({convention.subject for convention in conventions}))
    confidences = [convention.confidence for convention in conventions]
    confidence = min(confidences) if confidences else None
    evidence_refs = sorted({convention.source_ref for convention in conventions if convention.source_ref})
    provenance = Provenance(kind=ProvenanceKind.INFERRED, confidence=confidence, source_ref=None)
    return _dimension(name, [_make_attribution(value, provenance, evidence_refs)])


def _traversal_coverage_dimension(stats: TraversalStats) -> ProfileDimension:
    # A report about the walk's own accounting, not a claim about the project —
    # always resolvable directly from `traversal_stats`, never gated or UNKNOWN.
    value = (
        f"entries_visited={stats.entries_visited} "
        f"entries_skipped={stats.entries_skipped} "
        f"depth_limit_reached={stats.depth_limit_reached} "
        f"entry_limit_reached={stats.entry_limit_reached}"
    )
    provenance = Provenance(kind=ProvenanceKind.OBSERVED, confidence=1.0, source_ref=".")
    return _dimension("evidence.traversal-coverage", [_make_attribution(value, provenance, [])])


def _unobservable_paths_dimension(
    observations: list[ProjectObservation], stats: TraversalStats
) -> ProfileDimension:
    matches = [obs for obs in observations if obs.subject == "path-unobservable"]
    count = stats.entries_unobservable
    if count == 0:
        value = "0 unobservable paths"
        evidence_refs: list[str] = []
    else:
        value = f"{count} unobservable path(s)"
        evidence_refs = sorted(
            {obs.provenance.source_ref for obs in matches if obs.provenance.source_ref}
        )
    provenance = Provenance(kind=ProvenanceKind.OBSERVED, confidence=1.0, source_ref=".")
    return _dimension("evidence.unobservable-paths", [_make_attribution(value, provenance, evidence_refs)])


def _unread_files_dimension(observations: list[ProjectObservation]) -> ProfileDimension:
    # A fact strictly about files the walk actually visited (their size was known
    # regardless of whether the walk was exhaustive elsewhere) — never gated.
    matches = [obs for obs in observations if obs.subject == "file-read-skipped"]
    if not matches:
        value = "0 files skipped for size"
        evidence_refs: list[str] = []
    else:
        value = f"{len(matches)} file(s) skipped for exceeding the read-size limit"
        evidence_refs = sorted(
            {obs.provenance.source_ref for obs in matches if obs.provenance.source_ref}
        )
    provenance = Provenance(kind=ProvenanceKind.OBSERVED, confidence=1.0, source_ref=".")
    return _dimension("evidence.unread-files", [_make_attribution(value, provenance, evidence_refs)])


def _resolved_single_value(dimension: ProfileDimension) -> str | None:
    if dimension.resolution is ProfileResolution.RESOLVED:
        return dimension.attributions[0].value
    return None


def _source_intake_ref(intake: ProjectIntake, project_name: str | None) -> str:
    revision = intake.repository_revision[:12] if intake.repository_revision else "unknown"
    name = project_name or "unknown-project"
    return f"intake://{name}/rev-{revision}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def synthesize_project_profile(intake: ProjectIntake) -> ProjectProfile:
    """Synthesize a deterministic, descriptive ``ProjectProfile`` from ``intake``.

    Pure function of ``intake``'s content: no filesystem access, no clock, no
    randomness. Every dimension is traced to an existing intake evidence field —
    see the module docstring for exactly which field produces which dimension.
    """
    stats = intake.traversal_stats
    grouped = _group_classification_findings(intake.classification_findings)

    dimensions: list[ProfileDimension] = []
    for classification_dimension in CLASSIFICATION_DIMENSIONS:
        if classification_dimension in _CLASSIFICATION_EXCLUDED_DIMENSIONS:
            continue
        dimensions.append(
            _classification_dimension(
                classification_dimension, grouped.get(classification_dimension, [])
            )
        )

    dimensions.append(_repository_structure_dimension(intake.observations, stats=stats))
    dimensions.append(_repository_revision_dimension(intake.observations, stats=stats))
    dimensions.append(
        _aggregate_observation_dimension(
            "repository.package-metadata",
            intake.observations,
            frozenset({"package-metadata"}),
            stats=stats,
        )
    )
    dimensions.append(
        _aggregate_observation_dimension(
            "repository.ownership-boundaries",
            intake.observations,
            frozenset({"nested-project"}),
            stats=stats,
            none_observed_value="no-nested-project-boundaries-observed",
        )
    )
    dimensions.append(
        _aggregate_observation_dimension(
            "repository.foundry-artifacts",
            intake.observations,
            frozenset({"foundry-artifact", "foundry-declaration"}),
            stats=stats,
        )
    )
    dimensions.append(
        _aggregate_observation_dimension(
            "testability.test-entrypoint",
            intake.observations,
            frozenset({"test-entrypoint"}),
            stats=stats,
        )
    )
    dimensions.append(
        _aggregate_observation_dimension(
            "testability.lint-type-entrypoint",
            intake.observations,
            frozenset({"lint-type-entrypoint"}),
            stats=stats,
        )
    )
    dimensions.append(
        _aggregate_observation_dimension(
            "testability.ci-entrypoint",
            intake.observations,
            frozenset({"ci-entrypoint"}),
            stats=stats,
        )
    )
    dimensions.append(
        _aggregate_observation_dimension(
            "testability.config-schema",
            intake.observations,
            frozenset({"config-schema"}),
            stats=stats,
        )
    )
    dimensions.append(
        _aggregate_observation_dimension(
            "operating.deploy-surface",
            intake.observations,
            frozenset({"runtime-deploy-hint"}),
            stats=stats,
        )
    )
    dimensions.append(
        _aggregate_observation_dimension(
            "integration.config-surface",
            intake.observations,
            frozenset({"integration-config"}),
            stats=stats,
        )
    )
    dimensions.append(
        _aggregate_observation_dimension(
            "instruction.fragmentation",
            intake.observations,
            frozenset({"agent-instruction-surface"}),
            stats=stats,
            none_observed_value="no-agent-instruction-surface-observed",
        )
    )
    dimensions.append(_conventions_dimension(intake.conventions, stats=stats))
    dimensions.append(_traversal_coverage_dimension(stats))
    dimensions.append(_unobservable_paths_dimension(intake.observations, stats))
    dimensions.append(_unread_files_dimension(intake.observations))

    project_name_dimension = next(
        (dim for dim in dimensions if dim.dimension == "project.name"), None
    )
    project_name = _resolved_single_value(project_name_dimension) if project_name_dimension else None

    return ProjectProfile(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        project_name=project_name,
        dimensions=dimensions,
        source_intake_ref=_source_intake_ref(intake, project_name),
    )
