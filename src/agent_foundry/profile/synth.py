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
  were discovered, each published with the strongest evidence backing that
  category and the provenance kind that evidence carries (see
  ``_conventions_dimension``: a joined summary must never restate a DECLARED fact
  as INFERRED, nor floor one subject's confidence on an unrelated subject's).
* ``intake.traversal_stats`` — both to gate "absence" claims (see below) and to
  report the walk's own coverage as first-class dimensions.

**No project-type hard-coding.** Every dimension above is either (a) a direct,
1:1 echo of a fixed evidence field defined upstream in ``inspect/``, or (b) a
structural presence/absence fact keyed by that same fixed vocabulary. There is no
branch anywhere in this module keyed on an inferred project *category* (a named
domain or application-shape label of any kind), and no lookup table that amounts
to one. ``tests/test_profile_synthesis.py`` (test H) scans for the most naive
form of that — a quoted string literal spelling a forbidden category word — but
a word-list scan cannot prove the absence of a differently-spelled lookup table.
The two committed golden profiles (test J) are the real backstop: they pin the
*shape* of the output for two structurally different fixtures, so a change that
started routing output through a project-kind table would have to also keep
those two golden files byte-identical to pass review.

**Absence is not evidence, with one narrow, structural exception.** For every
dimension sourced from ``classification_findings`` (state, impact, execution,
assurance, access, work-mode, artifact, intake-mode facts), the *complete*
absence of a valued finding always yields ``UNKNOWN`` — never a value guessed
from silence, regardless of how much of the tree was walked. A finding that
*exists* but whose value was itself chosen from silence — its reason enumerates
signals that were checked and not found, which the producer marks with
``ABSENCE_ENUMERATION_REASON_PREFIXES`` — answers to the same rule and is gated
on ``_traversal_exhaustive`` in ``_classification_dimension``: ``intake_mode =
greenfield`` must not be published over a repository whose CI workflow,
container manifest and source tree simply sat past the walk's entry limit.

The one exception is a small family of purely structural "is file/marker X
present anywhere in the walked tree" dimensions (test harness markers, CI
workflow files, deploy hints, and so on): here, and only when the traversal was *exhaustive* (see
``_traversal_exhaustive``), "no such marker was observed" is itself a directly
observed fact — not a claim about safety, risk, or authority, and not drawn from
a walk that hit a depth/entry limit, left a path unobservable, refused a
containment escape, or skipped a file for exceeding the read-size limit (all
genuine holes — the last one because a content-derived observation, such as a
Makefile target, could never have been emitted for a file the walk never read —
so these dimensions fall back to ``UNKNOWN`` exactly like every other one when
any of them occurred). A
*deliberately skipped* directory (``.git``, ``node_modules``, and the rest of
``SKIP_DIR_NAMES`` — true of nearly every real repository) is not such a hole,
so it does not force ``UNKNOWN``; instead the resolved value says explicitly
that directories were skipped (``_scope_none_observed``), rather than reading as
a universal claim over ground the walk knowingly did not cover.

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
from agent_foundry.inspect.classification import (
    CLASSIFICATION_DIMENSIONS,
    reason_is_absence_enumeration,
)

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


def _traversal_exhaustive(stats: TraversalStats, *, unread_file_count: int = 0) -> bool:
    """True only when the walk left no genuine hole in the ground it covered.

    A depth/entry limit, an unobservable path, a containment refusal (a
    symlink resolving outside the root), or a file skipped for exceeding the
    read-size limit are all genuine holes: the unexamined content might hold
    anything a content-derived observation (a Makefile target, say) would have
    reported, so "no marker of kind X was found" must fall back to UNKNOWN
    rather than be reported as resolved. This gate is deliberately coarse — a
    read-skipped file anywhere in the intake forces every exhaustive-absence
    dimension to UNKNOWN, even one that would not itself have depended on that
    file's content — because the alternative (mapping each dimension to the
    specific files whose content could affect it) would silently need updating
    every time a new observation subject started reading a new file, and a
    stale mapping there fails open exactly where this module must fail closed.

    A *deliberately ignored* directory (``.git``, ``node_modules``, ``vendor``,
    ``build``, and the rest of ``SKIP_DIR_NAMES``) is different in kind — it is
    a documented, bounded exclusion, not an unknown hole — so it does not gate
    this check at all. It still must not be swallowed silently: callers that
    report a resolved "not observed" fact scope that claim to say a skip
    happened, rather than asserting it holds over ground the walk knowingly
    did not cover (see ``_scope_none_observed``).
    """
    return (
        not stats.depth_limit_reached
        and not stats.entry_limit_reached
        and stats.entries_unobservable == 0
        and stats.entries_skipped_refused == 0
        and unread_file_count == 0
    )


def _scope_none_observed(value: str, stats: TraversalStats) -> str:
    """Qualify a resolved "not observed" claim when directories were skipped.

    "None observed" is only ever a claim about the ground the walk actually
    covered. When ``SKIP_DIR_NAMES`` caused entries to be skipped (true of
    almost every real repository — a `.git` directory alone guarantees it),
    the claim must say so explicitly rather than read as universal.
    """
    if stats.entries_skipped_ignored_dir <= 0:
        return value
    return (
        f"{value} outside skipped directories "
        f"(entries_skipped_ignored_dir={stats.entries_skipped_ignored_dir})"
    )


# ---------------------------------------------------------------------------
# classification_findings -> profile dimensions (generic, 1:1, data-driven)
# ---------------------------------------------------------------------------


def _classification_dimension(
    name: str,
    findings: list[ClassificationFinding],
    *,
    exhaustive: bool,
) -> ProfileDimension:
    """Echo valued classification findings, gating the ones derived from absence.

    A finding whose reason is an *enumeration of signals that were checked and
    not found* (``reason_is_absence_enumeration``) is a claim about ground the
    walk covered — exactly like a "no marker observed" structural fact, and
    subject to the same rule. When the walk stopped at a depth/entry limit, hit
    an unobservable path, refused a containment escape, or skipped a file for
    size, the signals it enumerates may sit in the region it never looked at, so
    the finding is dropped here and the dimension falls back to UNKNOWN rather
    than publishing a confident negative (``intake_mode = greenfield`` over a
    repository whose CI, Dockerfile and source tree were simply never reached).

    Only the absence-derived findings are dropped: a declared or
    positively-evidenced finding for the same dimension still resolves it, since
    a truncated walk does not un-see what it did see.
    """
    attributions = [
        _make_attribution(finding.value, finding.provenance, finding.evidence_refs)
        for finding in findings
        if finding.value is not None
        and not (reason_is_absence_enumeration(finding.reason) and not exhaustive)
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
        unread_file_count = sum(1 for obs in observations if obs.subject == "file-read-skipped")
        if not _traversal_exhaustive(stats, unread_file_count=unread_file_count):
            return ProfileDimension(dimension=name, resolution=ProfileResolution.UNKNOWN, attributions=[])
        provenance = Provenance(kind=ProvenanceKind.OBSERVED, confidence=1.0, source_ref=".")
        value = _scope_none_observed(none_observed_value, stats)
        return _dimension(name, [_make_attribution(value, provenance, [])])

    value = "; ".join(sorted({obs.content for obs in matches}))
    kinds = {obs.provenance.kind for obs in matches}
    # A single-kind aggregate stays that kind; a heterogeneous one (e.g. an
    # OBSERVED file-presence fact unioned with a DECLARED one, as
    # `repository.foundry-artifacts` does) is a derivation over disagreeing
    # provenance kinds, not a direct observation — INFERRED, never OBSERVED,
    # so a declared fact is never silently republished as merely observed.
    kind = next(iter(kinds)) if len(kinds) == 1 else ProvenanceKind.INFERRED
    raw_confidences = [obs.provenance.confidence for obs in matches]
    # Any contributing observation with no stated confidence makes the
    # aggregate's confidence unstated too, rather than quietly computing a
    # floor over only the observations that happened to state one.
    confidence = None if any(c is None for c in raw_confidences) else min(raw_confidences)
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


def _conventions_dimension(
    conventions: list[ConventionSpec],
    observations: list[ProjectObservation],
    *,
    stats: TraversalStats,
) -> ProfileDimension:
    name = "assurance.conventions-observed"
    if not conventions:
        unread_file_count = sum(1 for obs in observations if obs.subject == "file-read-skipped")
        if not _traversal_exhaustive(stats, unread_file_count=unread_file_count):
            return ProfileDimension(dimension=name, resolution=ProfileResolution.UNKNOWN, attributions=[])
        provenance = Provenance(kind=ProvenanceKind.OBSERVED, confidence=1.0, source_ref=".")
        value = _scope_none_observed("no-conventions-observed", stats)
        return _dimension(name, [_make_attribution(value, provenance, [])])

    # One composite fact, not competing alternatives: "a test-invocation convention
    # and a git-policy convention were both discovered" is a single joined value in
    # exactly the way `_repository_structure_dimension` joins co-existing structural
    # facts — splitting it into one attribution per subject would make `_dimension`
    # read four co-existing conventions as CONFLICTED.
    #
    # What the composite must NOT do is launder the evidence it aggregates. Two
    # things are computed per *subject*, because a subject is the thing a claim is
    # about; conventions with different subjects are not competing claims and must
    # not be allowed to weaken or strengthen one another:
    #
    #   * strength — the strongest evidence discovered for that subject. A
    #     `test-invocation` fact parsed out of `pyproject.toml` (DECLARED, 0.8) is
    #     not made less true by a prose mention of `test-runner` in an instruction
    #     file (INFERRED, 0.15); a global `min()` over every convention reported
    #     exactly that, republishing an 0.8 declaration at 0.15.
    #   * kind — the provenance kind backing that strongest evidence, preserved
    #     rather than hardcoded. A dimension carrying nothing but DECLARED facts
    #     said INFERRED before this, which is provenance laundering outright.
    #
    # A single ``Provenance`` cannot carry one confidence per subject, so the
    # per-subject strength and kind are stated in the value itself — every subject
    # is published with the evidence that actually backs it, and no consumer has to
    # infer that a listed subject inherits the aggregate's number. The aggregate's
    # own confidence is then the strongest evidence behind any listed subject
    # (never the weakest, which floors an unrelated claim on an unrelated one), and
    # its kind follows the `_aggregate_observation_dimension` precedent: a single
    # contributing kind is preserved, a heterogeneous set is a derivation over
    # disagreeing provenance and reports INFERRED.
    by_subject: dict[str, list[ConventionSpec]] = {}
    for convention in conventions:
        by_subject.setdefault(convention.subject, []).append(convention)

    parts: list[str] = []
    subject_kinds: set[ProvenanceKind] = set()
    subject_strengths: list[float] = []
    for subject in sorted(by_subject):
        subject_conventions = by_subject[subject]
        strength = max(convention.confidence for convention in subject_conventions)
        strongest_kinds = {
            convention.provenance.kind
            for convention in subject_conventions
            if convention.confidence == strength
        }
        # Same rule as the aggregate one level up: if the strongest evidence for a
        # single subject disagrees with itself about provenance, the subject's kind
        # is a derivation over that disagreement, not either source's own claim.
        subject_kind = (
            next(iter(strongest_kinds)) if len(strongest_kinds) == 1 else ProvenanceKind.INFERRED
        )
        subject_kinds.add(subject_kind)
        subject_strengths.append(strength)
        parts.append(f"{subject} ({subject_kind.value} {strength:.2f})")

    value = ", ".join(parts)
    kind = next(iter(subject_kinds)) if len(subject_kinds) == 1 else ProvenanceKind.INFERRED
    confidence = max(subject_strengths)
    evidence_refs = sorted({convention.source_ref for convention in conventions if convention.source_ref})
    provenance = Provenance(kind=kind, confidence=confidence, source_ref=None)
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
    # The same exhaustiveness gate the observation-derived dimensions use, computed
    # once here because `classification_findings` is the third producer feeding this
    # profile and its absence-derived findings answer to the identical rule.
    unread_file_count = sum(
        1 for obs in intake.observations if obs.subject == "file-read-skipped"
    )
    exhaustive = _traversal_exhaustive(stats, unread_file_count=unread_file_count)

    dimensions: list[ProfileDimension] = []
    for classification_dimension in CLASSIFICATION_DIMENSIONS:
        if classification_dimension in _CLASSIFICATION_EXCLUDED_DIMENSIONS:
            continue
        dimensions.append(
            _classification_dimension(
                classification_dimension,
                grouped.get(classification_dimension, []),
                exhaustive=exhaustive,
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
            # `lint-type-entrypoint` covers filename markers (ruff.toml, mypy.ini,
            # ...); `lint-entrypoint`/`typecheck-entrypoint` are the Makefile
            # `lint:`/`typecheck:` target observations `_MAKEFILE_TARGET_SUBJECTS`
            # emits (collectors.py). All three answer the same question — is a
            # lint or type-check entrypoint present — so all three must feed it.
            frozenset({"lint-type-entrypoint", "lint-entrypoint", "typecheck-entrypoint"}),
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
            # `project-docs` (agent-facing docs under `docs/ai/`, collectors.py)
            # is instruction/context surface exactly as much as an
            # `agent-instruction-surface` file is — a dimension whose stated
            # purpose is measuring fragmentation must count both.
            frozenset({"agent-instruction-surface", "project-docs"}),
            stats=stats,
            none_observed_value="no-agent-instruction-surface-observed",
        )
    )
    dimensions.append(_conventions_dimension(intake.conventions, intake.observations, stats=stats))
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
