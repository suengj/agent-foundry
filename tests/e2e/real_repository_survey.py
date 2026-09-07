"""Survey real repositories for what ProjectProfile does — and does not — fix in V0.1.

V0.1's defining usability failure is an undeclared brownfield project resolving to an
empty or nearly empty operating/toolkit state: `plan_adoption(intake).manifest` comes
back with one of sixteen characteristics populated, and the toolkit resolves nothing.
`tests/e2e/friction_survey.py` measures exactly that, and `tests/e2e/profile_delta_survey.py`
measures a `ProjectProfile`'s shape. Neither puts the two side by side over a corpus of
*materially different real repositories*, which is what SUE-581 needs, so this module
does that — following the two existing surveys' method rather than inventing a third:

    python -m tests.e2e.real_repository_survey /path/to/repo-a /path/to/repo-b
    python -m tests.e2e.real_repository_survey --under /path/to/corpus .
    python -m tests.e2e.real_repository_survey --public-labels --under /tmp/corpus .
    python -m tests.e2e.real_repository_survey --label click=/tmp/corpus/pallets_click

Targets are always arguments. This module holds no corpus list: a named corpus baked
in here would be a second source of truth about what was surveyed, and the aggregate
would silently stop meaning "the repositories on the command line".

**No project-type branching.** Nothing here inspects a target to decide what *kind* of
project it is, and nothing here varies by target. Every repository goes through one
code path; the differences between repositories show up only as different numbers.

Privacy, and the one deliberate exception
-----------------------------------------
Privacy is a property of the type, exactly as in the two earlier surveys: every field
of `RealRepositorySurvey` is an `int`, a `bool`, or a tuple of terms drawn from
Foundry's own vocabulary — classification/profile dimension names, provenance kinds,
adoption actions, convention subjects, readiness dimensions, and this module's own
fixed rejection-reason vocabulary. A profile dimension's *value* — the attributed
string, which is repository content — is never read into any field here, and neither
is a path, a project name, or a file's bytes.

The one exception is `repository_label`, and it is deliberate, isolated and typed as
such. SUE-581's corpus is public, so naming the public repository makes the survey
*reproducible* — a reader can re-run it and get the same row. That value therefore
gets exactly one field, it is supplied by the operator (never derived from a target's
contents), it is never interpolated into any other field, and it defaults to the empty
string. A private target is recorded by passing no label: every other field is
structurally incapable of holding content, so a blank label leaks nothing.
`test_e2e_real_repository_survey.py` proves both halves — that every non-label field is
a number, a boolean, or fixed vocabulary, and that with labels blank no target's own
name reaches the aggregate.

Read-only
---------
`survey_repository` never writes to a target. `build_adversarial_project` is the only
function here that writes anything at all; it *constructs* a target into an empty
directory the operator names, and is not part of the survey path. The test module
proves the read-only property with a full content/mode/mtime tree snapshot.
"""

from __future__ import annotations

import json
import statistics
import sys
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path

from agent_foundry.adopt import plan_adoption
from agent_foundry.adopt.authority import AuthorityAxis
from agent_foundry.inspect import inspect_project
from agent_foundry.inspect.classification import CLASSIFICATION_DIMENSIONS
from agent_foundry.inspect.conventions import STRUCTURED_CONFIDENCE
from agent_foundry.models import AuthorityRequirement, ProfileResolution, ProvenanceKind
from agent_foundry.profile import synthesize_project_profile
from agent_foundry.toolkit import resolve_toolkit

from tests.e2e.friction_survey import MANIFEST_DIMENSION_COUNT, discover_repositories

# The manifest characteristics an owner can declare, reused from the module that owns
# them. `friction_survey.MANIFEST_DIMENSION_COUNT` is the V0.1 denominator and is
# imported rather than restated, so the before/after contrast below cannot drift from
# the number the V0.1 measurement already quotes.
CLASSIFICATION_DIMENSION_NAMES: frozenset[str] = frozenset(CLASSIFICATION_DIMENSIONS)

# Which manifest fields *bear authority* is not this module's judgement. `adopt.authority`
# owns it: `AuthorityAxis` enumerates the manifest fields whose value defines part of the
# project's authority envelope, and the adoption guard fails closed on anything it has
# not classified. Deriving the set from that enum means a new authority axis is counted
# here the day it is added, and this module can never disagree with the guard.
AUTHORITY_BEARING_DIMENSIONS: frozenset[str] = frozenset(axis.value for axis in AuthorityAxis)


class EvidenceRejection(StrEnum):
    """Reasons to reject a profile *despite* its coverage. Fixed vocabulary.

    A rejection reason is a reason to look, not a verdict: it names a property of the
    evidence under a profile that a high resolved-count would otherwise hide. The whole
    point is that "31 of 31 resolved" must never read, on its own, as a good profile.

    Each reason is a computed property of the survey record — never a note written by
    hand about a particular repository.
    """

    #: Every resolved dimension an owner can declare came from one declaration file and
    #: nothing corroborates it. The substantive half of the profile is one unverified
    #: assertion; deleting that file empties it.
    SINGLE_SOURCE_CLASSIFICATION = "single-source-classification"
    #: Every resolved authority-bearing dimension rests on DECLARED provenance with no
    #: observed corroboration. Authority is an owner's call, so a declaration is the
    #: right source — but a survey that scored this as coverage would be treating an
    #: unverified claim about the authority envelope as an established fact.
    UNCORROBORATED_AUTHORITY_DECLARATION = "uncorroborated-authority-declaration"
    #: Conventions were discovered, but not one of them is a structured declaration —
    #: they are all prose mentions (`inspect/conventions.py` ranks these below every
    #: structured fact for exactly this reason).
    CONVENTIONS_WITHOUT_STRUCTURED_DECLARATION = "conventions-without-structured-declaration"
    #: A high resolved-count produced over a walk that left a hole — a depth/entry
    #: limit, an unobservable path, a refused containment escape, or a file whose bytes
    #: went unread.
    COVERAGE_OVER_INCOMPLETE_WALK = "coverage-over-incomplete-walk"
    #: More resolved dimensions than the evidence has distinct sources to support. A
    #: profile resting on three files does not become better supported by resolving
    #: thirty dimensions off them.
    EVIDENCE_SPARSE_COVERAGE = "evidence-sparse-coverage"


# Thresholds are judgement, and are stated here rather than buried in a condition so a
# reader can disagree with a number without reverse-engineering it. None of them is
# derived from, or tuned to, any particular repository in any corpus.

#: A profile resolving at least this share of its dimensions reads as "high coverage".
HIGH_COVERAGE_SHARE = 0.9
#: `COVERAGE_OVER_INCOMPLETE_WALK` fires only above this share: an incomplete walk that
#: also resolved very little is simply a thin profile, not a coverage claim to distrust.
INCOMPLETE_WALK_COVERAGE_SHARE = 0.9
#: `EVIDENCE_SPARSE_COVERAGE` fires when there is not one distinct evidence source per
#: this many resolved dimensions.
RESOLVED_DIMENSIONS_PER_EVIDENCE_SOURCE = 2


@dataclass(frozen=True)
class RealRepositorySurvey:
    """One repository's row. Every field but `repository_label` is a number, a boolean,
    or a tuple of Foundry's own vocabulary terms — see the module docstring."""

    # -- the one, deliberately isolated, operator-supplied identity field -------------
    repository_label: str

    # -- profile dimension coverage (contract: "profile dimension coverage and
    #    unknown/unobservable rate") ------------------------------------------------
    dimensions_total: int
    dimensions_resolved: int
    dimensions_conflicted: int
    dimensions_unknown: int
    resolved_dimension_names: tuple[str, ...]
    conflicted_dimension_names: tuple[str, ...]
    unknown_dimension_names: tuple[str, ...]

    # -- the substantive half: dimensions an owner can also declare in a manifest.
    #    Separating these from the structural/evidence dimensions is what stops a
    #    profile that resolved only "0 files skipped for size" from reading as covered.
    classification_dimensions_present: int
    classification_dimensions_resolved: int
    classification_dimensions_conflicted: int
    classification_dimensions_unknown: int
    classification_dimensions_declared_only: int
    classification_dimensions_inferred_only: int
    classification_declaration_sources: int
    classification_dimensions_withheld_from_profile: int

    # -- authority-bearing dimensions. A rising unknown count here is the correct
    #    outcome when nothing was declared; it is recorded, never optimised. ---------
    authority_dimensions_total: int
    authority_dimensions_resolved: int
    authority_dimensions_unknown: int
    authority_dimensions_conflicted: int
    authority_dimensions_declared_only: int
    authority_dimension_names_unknown: tuple[str, ...]

    # -- attribution and evidence quality (contract: "false-positive/unsupported
    #    convention rate", "materially wrong inferred facts traced to evidence") -----
    attributions_total: int
    attributions_observed: int
    attributions_declared: int
    attributions_inferred: int
    attributions_normative: int
    attributions_with_evidence_refs: int
    attributions_without_evidence_refs: int
    resolved_dimensions_with_evidence_refs: int
    resolved_dimensions_without_evidence_refs: int
    resolved_dimensions_multi_attribution: int
    distinct_evidence_sources: int

    # -- the V0.1 manifest-only baseline, side by side with the V0.2 profile ---------
    baseline_manifest_dimension_count: int
    baseline_manifest_fields_populated: int
    baseline_manifest_fields_unpopulated: int
    baseline_declaration_present: bool
    baseline_toolkit_roles_resolved: int
    baseline_toolkit_capabilities_resolved: int
    adoption_changes: int
    adoption_changes_requiring_explicit_authority: int
    adoption_actions: tuple[str, ...]

    # -- conventions, by subject and by provenance kind ------------------------------
    conventions_discovered: int
    convention_subjects: tuple[str, ...]
    conventions_observed: int
    conventions_declared: int
    conventions_inferred: int
    conventions_normative: int
    conventions_structured: int

    # -- traversal truncation and boundary friction ----------------------------------
    entries_visited: int
    entries_skipped: int
    entries_skipped_ignored_dir: int
    entries_skipped_refused: int
    entries_skipped_unreadable: int
    entries_unobservable: int
    entry_limit_reached: bool
    depth_limit_reached: bool
    files_over_read_limit: int
    walk_path_exhaustive: bool
    walk_exhaustive: bool

    # -- readiness -------------------------------------------------------------------
    readiness_findings_total: int
    readiness_blockers: int
    readiness_blocker_dimensions: tuple[str, ...]

    # ---------------------------------------------------------------------------
    # Computed properties. These are derived from the fields above and never from a
    # target, so they inherit the same privacy shape.
    # ---------------------------------------------------------------------------

    @property
    def coverage_ratio(self) -> float:
        if self.dimensions_total == 0:
            return 0.0
        return self.dimensions_resolved / self.dimensions_total

    @property
    def classification_coverage_ratio(self) -> float:
        if self.classification_dimensions_present == 0:
            return 0.0
        return self.classification_dimensions_resolved / self.classification_dimensions_present

    @property
    def baseline_coverage_ratio(self) -> float:
        if self.baseline_manifest_dimension_count == 0:
            return 0.0
        return self.baseline_manifest_fields_populated / self.baseline_manifest_dimension_count

    @property
    def high_coverage(self) -> bool:
        return self.coverage_ratio >= HIGH_COVERAGE_SHARE

    @property
    def rejection_reasons(self) -> tuple[str, ...]:
        """Reasons this profile's coverage should not be taken at face value."""
        reasons: list[EvidenceRejection] = []

        if (
            self.classification_dimensions_resolved >= 2
            and self.classification_dimensions_declared_only
            == self.classification_dimensions_resolved
            and self.classification_declaration_sources <= 1
        ):
            reasons.append(EvidenceRejection.SINGLE_SOURCE_CLASSIFICATION)

        if (
            self.authority_dimensions_resolved > 0
            and self.authority_dimensions_declared_only == self.authority_dimensions_resolved
        ):
            reasons.append(EvidenceRejection.UNCORROBORATED_AUTHORITY_DECLARATION)

        if self.conventions_discovered > 0 and self.conventions_structured == 0:
            reasons.append(EvidenceRejection.CONVENTIONS_WITHOUT_STRUCTURED_DECLARATION)

        if not self.walk_exhaustive and self.coverage_ratio >= INCOMPLETE_WALK_COVERAGE_SHARE:
            reasons.append(EvidenceRejection.COVERAGE_OVER_INCOMPLETE_WALK)

        if (
            self.dimensions_resolved > 0
            and self.distinct_evidence_sources * RESOLVED_DIMENSIONS_PER_EVIDENCE_SOURCE
            < self.dimensions_resolved
        ):
            reasons.append(EvidenceRejection.EVIDENCE_SPARSE_COVERAGE)

        return tuple(reason.value for reason in reasons)

    @property
    def coverage_is_supported(self) -> bool:
        """False when something about the evidence contradicts taking coverage at face
        value. A profile with no rejection reason is *not* thereby correct — completeness
        is never evidence of correctness — it is only a profile this survey found no
        reason to reject."""
        return not self.rejection_reasons

    @property
    def high_coverage_unsupported(self) -> bool:
        """The adversarial property in one flag: covered, and still not to be trusted."""
        return self.high_coverage and bool(self.rejection_reasons)


@dataclass
class RealSurveyResult:
    surveys: list[RealRepositorySurvey] = field(default_factory=list)
    failed: int = 0
    failure_types: tuple[str, ...] = ()


def _kind_counts(kinds: list[ProvenanceKind]) -> dict[ProvenanceKind, int]:
    counts = {kind: 0 for kind in ProvenanceKind}
    for kind in kinds:
        counts[kind] += 1
    return counts


def survey_repository(path: Path, *, repository_label: str = "") -> RealRepositorySurvey:
    """Inspect, profile and adoption-plan *path*, recording counts only.

    Strictly read-only with respect to *path*. `repository_label` is the operator's,
    never derived from anything inside the target.
    """
    intake = inspect_project(path)
    profile = synthesize_project_profile(intake)
    plan = plan_adoption(intake)
    manifest = plan.manifest
    _, lock = resolve_toolkit(manifest)

    stats = intake.traversal_stats
    unread_files = sum(1 for item in intake.observations if item.subject == "file-read-skipped")

    by_resolution: dict[ProfileResolution, list] = {
        resolution: [d for d in profile.dimensions if d.resolution is resolution]
        for resolution in ProfileResolution
    }
    resolved = by_resolution[ProfileResolution.RESOLVED]
    conflicted = by_resolution[ProfileResolution.CONFLICTED]
    unknown = by_resolution[ProfileResolution.UNKNOWN]

    classification = [d for d in profile.dimensions if d.dimension in CLASSIFICATION_DIMENSION_NAMES]
    classification_resolved = [d for d in classification if d.resolution is ProfileResolution.RESOLVED]
    declared_only = [
        d
        for d in classification_resolved
        if all(a.provenance.kind is ProvenanceKind.DECLARED for a in d.attributions)
    ]
    inferred_only = [
        d
        for d in classification_resolved
        if all(a.provenance.kind is ProvenanceKind.INFERRED for a in d.attributions)
    ]
    declaration_sources = {
        a.provenance.source_ref
        for d in declared_only
        for a in d.attributions
        if a.provenance.source_ref
    }

    authority = [d for d in profile.dimensions if d.dimension in AUTHORITY_BEARING_DIMENSIONS]
    authority_resolved = [d for d in authority if d.resolution is ProfileResolution.RESOLVED]
    authority_unknown = [d for d in authority if d.resolution is ProfileResolution.UNKNOWN]
    authority_declared_only = [
        d
        for d in authority_resolved
        if all(a.provenance.kind is ProvenanceKind.DECLARED for a in d.attributions)
    ]

    attributions = [a for d in profile.dimensions for a in d.attributions]
    attribution_kinds = _kind_counts([a.provenance.kind for a in attributions])
    with_refs = sum(1 for a in attributions if a.evidence_refs)

    # Distinct evidence *sources*, counted and never recorded: the union of every
    # provenance source_ref and every evidence_ref across the whole profile. This is the
    # breadth the profile actually rests on, which a resolved-count cannot show.
    evidence_sources: set[str] = set()
    for attribution in attributions:
        if attribution.provenance.source_ref:
            evidence_sources.add(attribution.provenance.source_ref)
        evidence_sources.update(attribution.evidence_refs)

    convention_kinds = _kind_counts([c.provenance.kind for c in intake.conventions])

    # The V0.1 usability proxy, computed exactly as `friction_survey.survey_repository`
    # computes it — by asking the manifest the same question, one field at a time.
    work_modes = manifest.project.work_modes
    populated = [
        manifest.project.intake_mode,
        manifest.project.name,
        work_modes.primary if work_modes else None,
        list(work_modes.secondary) if work_modes and work_modes.secondary else None,
        manifest.project.primary_artifact,
        manifest.state.persistence,
        manifest.state.temporal_mode,
        manifest.impact.external_effect,
        manifest.impact.reversibility,
        manifest.impact.consequence,
        manifest.execution.autonomy,
        manifest.execution.ambiguity,
        manifest.execution.concurrency,
        list(manifest.assurance.required) or None,
        manifest.access.sensitivity,
        list(manifest.authority.write_scope) or None,
    ]
    assert len(populated) == MANIFEST_DIMENSION_COUNT
    manifest_populated = sum(1 for value in populated if value not in (None, []))

    walk_path_exhaustive = (
        not stats.depth_limit_reached
        and not stats.entry_limit_reached
        and stats.entries_unobservable == 0
        and stats.entries_skipped_refused == 0
    )

    return RealRepositorySurvey(
        repository_label=repository_label,
        dimensions_total=len(profile.dimensions),
        dimensions_resolved=len(resolved),
        dimensions_conflicted=len(conflicted),
        dimensions_unknown=len(unknown),
        resolved_dimension_names=tuple(sorted(d.dimension for d in resolved)),
        conflicted_dimension_names=tuple(sorted(d.dimension for d in conflicted)),
        unknown_dimension_names=tuple(sorted(d.dimension for d in unknown)),
        classification_dimensions_present=len(classification),
        classification_dimensions_resolved=len(classification_resolved),
        classification_dimensions_conflicted=sum(
            1 for d in classification if d.resolution is ProfileResolution.CONFLICTED
        ),
        classification_dimensions_unknown=sum(
            1 for d in classification if d.resolution is ProfileResolution.UNKNOWN
        ),
        classification_dimensions_declared_only=len(declared_only),
        classification_dimensions_inferred_only=len(inferred_only),
        classification_declaration_sources=len(declaration_sources),
        # Derived from what the profile actually published, not from a list kept here:
        # `profile.synth` deliberately withholds `authority.write_scope`, and a future
        # withholding decision is counted the day it is made.
        classification_dimensions_withheld_from_profile=len(
            CLASSIFICATION_DIMENSION_NAMES - {d.dimension for d in profile.dimensions}
        ),
        authority_dimensions_total=len(authority),
        authority_dimensions_resolved=len(authority_resolved),
        authority_dimensions_unknown=len(authority_unknown),
        authority_dimensions_conflicted=sum(
            1 for d in authority if d.resolution is ProfileResolution.CONFLICTED
        ),
        authority_dimensions_declared_only=len(authority_declared_only),
        authority_dimension_names_unknown=tuple(sorted(d.dimension for d in authority_unknown)),
        attributions_total=len(attributions),
        attributions_observed=attribution_kinds[ProvenanceKind.OBSERVED],
        attributions_declared=attribution_kinds[ProvenanceKind.DECLARED],
        attributions_inferred=attribution_kinds[ProvenanceKind.INFERRED],
        attributions_normative=attribution_kinds[ProvenanceKind.NORMATIVE],
        attributions_with_evidence_refs=with_refs,
        attributions_without_evidence_refs=len(attributions) - with_refs,
        resolved_dimensions_with_evidence_refs=sum(
            1 for d in resolved if any(a.evidence_refs for a in d.attributions)
        ),
        resolved_dimensions_without_evidence_refs=sum(
            1 for d in resolved if not any(a.evidence_refs for a in d.attributions)
        ),
        resolved_dimensions_multi_attribution=sum(1 for d in resolved if len(d.attributions) > 1),
        distinct_evidence_sources=len(evidence_sources),
        baseline_manifest_dimension_count=MANIFEST_DIMENSION_COUNT,
        baseline_manifest_fields_populated=manifest_populated,
        baseline_manifest_fields_unpopulated=MANIFEST_DIMENSION_COUNT - manifest_populated,
        baseline_declaration_present=any(
            item.subject == "foundry-declaration" for item in intake.observations
        ),
        baseline_toolkit_roles_resolved=len(lock.role_ids),
        baseline_toolkit_capabilities_resolved=len(lock.capability_ids),
        adoption_changes=len(plan.change_set.changes),
        adoption_changes_requiring_explicit_authority=sum(
            1
            for change in plan.change_set.changes
            if change.authority_requirement is AuthorityRequirement.EXPLICIT_AUTHORITY
        ),
        adoption_actions=tuple(sorted({change.action.value for change in plan.change_set.changes})),
        conventions_discovered=len(intake.conventions),
        convention_subjects=tuple(sorted({c.subject for c in intake.conventions})),
        conventions_observed=convention_kinds[ProvenanceKind.OBSERVED],
        conventions_declared=convention_kinds[ProvenanceKind.DECLARED],
        conventions_inferred=convention_kinds[ProvenanceKind.INFERRED],
        conventions_normative=convention_kinds[ProvenanceKind.NORMATIVE],
        # "Structured" is `inspect/conventions.py`'s own bar, imported rather than
        # restated: a fact a real parser established, not a phrase spotted in prose.
        conventions_structured=sum(
            1
            for c in intake.conventions
            if c.confidence >= STRUCTURED_CONFIDENCE
            and c.provenance.kind is ProvenanceKind.DECLARED
        ),
        entries_visited=stats.entries_visited,
        entries_skipped=stats.entries_skipped,
        entries_skipped_ignored_dir=stats.entries_skipped_ignored_dir,
        entries_skipped_refused=stats.entries_skipped_refused,
        entries_skipped_unreadable=stats.entries_skipped_unreadable,
        entries_unobservable=stats.entries_unobservable,
        entry_limit_reached=stats.entry_limit_reached,
        depth_limit_reached=stats.depth_limit_reached,
        files_over_read_limit=unread_files,
        walk_path_exhaustive=walk_path_exhaustive,
        walk_exhaustive=walk_path_exhaustive and unread_files == 0,
        readiness_findings_total=len(intake.readiness_findings),
        readiness_blockers=sum(1 for item in intake.readiness_findings if item.blocker),
        readiness_blocker_dimensions=tuple(
            sorted({item.dimension for item in intake.readiness_findings if item.blocker})
        ),
    )


def survey(targets: list[tuple[str, Path]]) -> RealSurveyResult:
    """Survey each `(label, path)` pair. A failure is recorded by exception *type*.

    As in the two earlier surveys, the exception's message is never recorded: an
    inspection failure routinely quotes the path that failed. The label is not recorded
    for a failed target either — a failure row carries no identity it did not earn.
    """
    result = RealSurveyResult()
    failures: list[str] = []
    for label, path in targets:
        try:
            result.surveys.append(survey_repository(path, repository_label=label))
        except Exception as error:  # noqa: BLE001 - the type is the whole record
            result.failed += 1
            failures.append(type(error).__name__)
    result.failure_types = tuple(sorted(set(failures)))
    return result


def _name_counts(surveys: list[RealRepositorySurvey], attr: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in surveys:
        for name in getattr(item, attr):
            counts[name] = counts.get(name, 0) + 1
    return counts


def baseline_comparison_rows(result: RealSurveyResult) -> list[dict[str, object]]:
    """The V0.1-vs-V0.2 contrast, one row per repository, made directly readable.

    `baseline_manifest_fields_populated` of `baseline_manifest_dimension_count` is
    precisely V0.1's manifest-only usability proxy — the figure
    `tests/e2e/friction_survey.py` already produces. Set against
    `dimensions_resolved` of `dimensions_total`, that pair *is* the improvement claim,
    and `rejection_reasons` on the same row is what stops the right-hand number from
    being read as a score.
    """
    return [
        {
            "repository_label": item.repository_label,
            "v01_manifest_fields_populated": item.baseline_manifest_fields_populated,
            "v01_manifest_dimension_count": item.baseline_manifest_dimension_count,
            "v01_toolkit_roles_resolved": item.baseline_toolkit_roles_resolved,
            "v01_toolkit_capabilities_resolved": item.baseline_toolkit_capabilities_resolved,
            "v02_dimensions_resolved": item.dimensions_resolved,
            "v02_dimensions_total": item.dimensions_total,
            "v02_dimensions_unknown": item.dimensions_unknown,
            "v02_classification_dimensions_resolved": item.classification_dimensions_resolved,
            "v02_classification_dimensions_present": item.classification_dimensions_present,
            "authority_dimensions_unknown": item.authority_dimensions_unknown,
            "authority_dimensions_total": item.authority_dimensions_total,
            "conventions_discovered": item.conventions_discovered,
            "conventions_structured": item.conventions_structured,
            "distinct_evidence_sources": item.distinct_evidence_sources,
            "files_over_read_limit": item.files_over_read_limit,
            "entry_limit_reached": item.entry_limit_reached,
            "depth_limit_reached": item.depth_limit_reached,
            "readiness_blockers": item.readiness_blockers,
            "high_coverage": item.high_coverage,
            "rejection_reasons": list(item.rejection_reasons),
            "high_coverage_unsupported": item.high_coverage_unsupported,
        }
        for item in result.surveys
    ]


def aggregate(result: RealSurveyResult) -> dict[str, object]:
    """Counts, vocabulary terms, and the operator-supplied labels — nothing else."""
    surveys = result.surveys
    base: dict[str, object] = {
        "repositories": len(surveys),
        "failed": result.failed,
        "failure_types": list(result.failure_types),
    }
    if not surveys:
        return base

    resolved = [item.dimensions_resolved for item in surveys]
    baseline = [item.baseline_manifest_fields_populated for item in surveys]
    base.update(
        {
            # --- the headline before/after -------------------------------------
            "v01_manifest_dimension_count": MANIFEST_DIMENSION_COUNT,
            "v01_manifest_fields_populated_min": min(baseline),
            "v01_manifest_fields_populated_median": int(statistics.median(baseline)),
            "v01_manifest_fields_populated_max": max(baseline),
            "v01_repositories_with_declaration": sum(
                1 for item in surveys if item.baseline_declaration_present
            ),
            "v01_repositories_resolving_any_role": sum(
                1 for item in surveys if item.baseline_toolkit_roles_resolved
            ),
            "v01_repositories_resolving_any_capability": sum(
                1 for item in surveys if item.baseline_toolkit_capabilities_resolved
            ),
            "v01_repositories_with_empty_manifest_beyond_intake_mode": sum(
                1 for item in surveys if item.baseline_manifest_fields_populated <= 1
            ),
            "v02_dimensions_total_min": min(item.dimensions_total for item in surveys),
            "v02_dimensions_total_max": max(item.dimensions_total for item in surveys),
            "v02_dimensions_resolved_min": min(resolved),
            "v02_dimensions_resolved_median": int(statistics.median(resolved)),
            "v02_dimensions_resolved_max": max(resolved),
            "v02_dimensions_unknown_total": sum(item.dimensions_unknown for item in surveys),
            "v02_dimensions_conflicted_total": sum(item.dimensions_conflicted for item in surveys),
            # --- the substantive half, kept separate from the structural one ----
            "classification_dimensions_present": max(
                item.classification_dimensions_present for item in surveys
            ),
            "classification_dimensions_resolved_total": sum(
                item.classification_dimensions_resolved for item in surveys
            ),
            "classification_dimensions_unknown_total": sum(
                item.classification_dimensions_unknown for item in surveys
            ),
            "classification_dimensions_declared_only_total": sum(
                item.classification_dimensions_declared_only for item in surveys
            ),
            "classification_dimensions_inferred_only_total": sum(
                item.classification_dimensions_inferred_only for item in surveys
            ),
            "classification_dimensions_withheld_from_profile": max(
                item.classification_dimensions_withheld_from_profile for item in surveys
            ),
            # --- authority: recorded, never optimised ---------------------------
            "authority_dimensions_total": max(item.authority_dimensions_total for item in surveys),
            "authority_dimensions_unknown_total": sum(
                item.authority_dimensions_unknown for item in surveys
            ),
            "authority_dimensions_declared_only_total": sum(
                item.authority_dimensions_declared_only for item in surveys
            ),
            "repositories_with_all_authority_dimensions_unknown": sum(
                1
                for item in surveys
                if item.authority_dimensions_total
                and item.authority_dimensions_unknown == item.authority_dimensions_total
            ),
            # --- names ----------------------------------------------------------
            "resolved_dimension_counts": dict(
                sorted(_name_counts(surveys, "resolved_dimension_names").items())
            ),
            "unknown_dimension_counts": dict(
                sorted(_name_counts(surveys, "unknown_dimension_names").items())
            ),
            "conflicted_dimension_counts": dict(
                sorted(_name_counts(surveys, "conflicted_dimension_names").items())
            ),
            # --- attribution / evidence -----------------------------------------
            "attributions_total": sum(item.attributions_total for item in surveys),
            "attributions_observed": sum(item.attributions_observed for item in surveys),
            "attributions_declared": sum(item.attributions_declared for item in surveys),
            "attributions_inferred": sum(item.attributions_inferred for item in surveys),
            "attributions_normative": sum(item.attributions_normative for item in surveys),
            "attributions_with_evidence_refs": sum(
                item.attributions_with_evidence_refs for item in surveys
            ),
            "attributions_without_evidence_refs": sum(
                item.attributions_without_evidence_refs for item in surveys
            ),
            "resolved_dimensions_without_evidence_refs_total": sum(
                item.resolved_dimensions_without_evidence_refs for item in surveys
            ),
            "resolved_dimensions_multi_attribution_total": sum(
                item.resolved_dimensions_multi_attribution for item in surveys
            ),
            "distinct_evidence_sources_min": min(
                item.distinct_evidence_sources for item in surveys
            ),
            "distinct_evidence_sources_median": int(
                statistics.median(item.distinct_evidence_sources for item in surveys)
            ),
            "distinct_evidence_sources_max": max(
                item.distinct_evidence_sources for item in surveys
            ),
            # --- conventions ------------------------------------------------------
            "conventions_total": sum(item.conventions_discovered for item in surveys),
            "conventions_structured_total": sum(item.conventions_structured for item in surveys),
            "conventions_observed_total": sum(item.conventions_observed for item in surveys),
            "conventions_declared_total": sum(item.conventions_declared for item in surveys),
            "conventions_inferred_total": sum(item.conventions_inferred for item in surveys),
            "conventions_normative_total": sum(item.conventions_normative for item in surveys),
            "convention_subject_counts": dict(
                sorted(_name_counts(surveys, "convention_subjects").items())
            ),
            "repositories_with_conventions_but_none_structured": sum(
                1
                for item in surveys
                if item.conventions_discovered > 0 and item.conventions_structured == 0
            ),
            # --- traversal truncation / boundary friction -------------------------
            "entries_visited_median": int(
                statistics.median(item.entries_visited for item in surveys)
            ),
            "entries_visited_max": max(item.entries_visited for item in surveys),
            "entry_limit_reached": sum(1 for item in surveys if item.entry_limit_reached),
            "depth_limit_reached": sum(1 for item in surveys if item.depth_limit_reached),
            "repositories_with_unobservable_paths": sum(
                1 for item in surveys if item.entries_unobservable
            ),
            "repositories_with_refused_entries": sum(
                1 for item in surveys if item.entries_skipped_refused
            ),
            "files_over_read_limit_total": sum(item.files_over_read_limit for item in surveys),
            "files_over_read_limit_max": max(item.files_over_read_limit for item in surveys),
            "repositories_with_path_exhaustive_walk": sum(
                1 for item in surveys if item.walk_path_exhaustive
            ),
            "repositories_with_exhaustive_walk": sum(1 for item in surveys if item.walk_exhaustive),
            # --- readiness and manual work still required -------------------------
            "readiness_findings_total": sum(item.readiness_findings_total for item in surveys),
            "readiness_blockers_total": sum(item.readiness_blockers for item in surveys),
            "readiness_blocker_dimension_counts": dict(
                sorted(_name_counts(surveys, "readiness_blocker_dimensions").items())
            ),
            "adoption_changes_total": sum(item.adoption_changes for item in surveys),
            "adoption_changes_requiring_explicit_authority_total": sum(
                item.adoption_changes_requiring_explicit_authority for item in surveys
            ),
            "adoption_action_counts": dict(sorted(_name_counts(surveys, "adoption_actions").items())),
            "manifest_fields_still_unpopulated_total": sum(
                item.baseline_manifest_fields_unpopulated for item in surveys
            ),
            # --- the evidence-quality verdict ------------------------------------
            "repositories_with_high_coverage": sum(1 for item in surveys if item.high_coverage),
            "repositories_with_high_coverage_and_rejections": sum(
                1 for item in surveys if item.high_coverage_unsupported
            ),
            "repositories_with_no_rejection_reason": sum(
                1 for item in surveys if item.coverage_is_supported
            ),
            "rejection_reason_counts": dict(
                sorted(_name_counts(surveys, "rejection_reasons").items())
            ),
            "per_repository": baseline_comparison_rows(result),
        }
    )
    return base


# ---------------------------------------------------------------------------
# The adversarial construction: high coverage, poor evidence.
# ---------------------------------------------------------------------------

# A single owner declaration covering every characteristic the manifest has. Nothing
# corroborates any of it, and the tree around it holds no build marker, no CI file, no
# package metadata, and no structured test configuration — so a profile synthesized
# here resolves nearly every dimension while resting on three files.
_ADVERSARIAL_DECLARATION = """\
project:
  name: declared-everything
  intake_mode: brownfield
  primary_artifact: code
  work_modes:
    primary: build
    secondary:
      - analyze
state:
  persistence: local
  temporal_mode: batch
impact:
  external_effect: repository-write
  reversibility: versioned
  consequence: low
execution:
  autonomy: suggest
  ambiguity: procedural
  concurrency: single-writer
assurance:
  required:
    - deterministic-tests
access:
  sensitivity: internal
authority:
  write_scope:
    - src
"""

# A prose instruction surface that *mentions* a test runner and declares nothing. The
# convention discovered from it is an INFERRED mention, which `inspect/conventions.py`
# deliberately ranks below every structured fact.
_ADVERSARIAL_INSTRUCTIONS = """\
# Agent instructions

Run the tests with pytest before proposing anything.
Do not commit directly to the default branch.
"""


def build_adversarial_project(root: Path) -> Path:
    """Write the adversarial construction into the empty directory *root*.

    This is the one function in this module that writes anything, and it never touches
    a surveyed repository: it *builds* a target, and refuses to write into a directory
    that already holds something. `survey_repository` remains strictly read-only.

    The construction is generic. It contains no marker of any project type, states no
    language, and is not derived from any repository in any corpus — it is simply a
    complete declaration with nothing behind it.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise ValueError("build_adversarial_project requires an empty directory")
    (root / ".foundry").mkdir()
    (root / ".foundry" / "project.yaml").write_text(_ADVERSARIAL_DECLARATION, encoding="utf-8")
    (root / "AGENTS.md").write_text(_ADVERSARIAL_INSTRUCTIONS, encoding="utf-8")
    # Deliberately *not* also truncating the walk. A file past the read-size limit
    # would gate the content-derived dimensions to UNKNOWN and so lower the very
    # coverage this construction exists to demonstrate; the truncated-walk species of
    # poor evidence shows up on real repositories instead
    # (`COVERAGE_OVER_INCOMPLETE_WALK`). What is demonstrated here is the harder case:
    # a walk that left no hole at all, near-total coverage, and evidence that still
    # does not support it.
    return root


# ---------------------------------------------------------------------------
# Operator entry point
# ---------------------------------------------------------------------------

_USAGE = """\
usage: python -m tests.e2e.real_repository_survey [OPTIONS] [TARGET ...]

TARGET      a repository path, surveyed with a blank label
OPTIONS
  --under DIR         survey every git repository directly inside DIR
  --label NAME=PATH   survey PATH, recorded under the public label NAME
  --public-labels     label every otherwise-unlabelled target with its directory
                      name. Only for a corpus that is public: the label is the one
                      field of the record that can carry a name.
  --adversarial DIR   build the adversarial construction into the empty DIR and
                      survey it alongside the other targets

Prints a JSON aggregate: counts, Foundry's own vocabulary terms, and whatever labels
were supplied.
"""


def _parse_argv(argv: list[str]) -> tuple[list[tuple[str, Path]], bool]:
    targets: list[tuple[str, Path]] = []
    plain: list[Path] = []
    public_labels = False
    index = 0
    while index < len(argv):
        item = argv[index]
        if item == "--public-labels":
            public_labels = True
        elif item == "--under":
            index += 1
            plain.extend(discover_repositories([Path(argv[index])]))
        elif item == "--label":
            index += 1
            name, _, raw = argv[index].partition("=")
            if not raw:
                raise ValueError("--label expects NAME=PATH")
            targets.append((name, Path(raw)))
        elif item == "--adversarial":
            index += 1
            plain.append(build_adversarial_project(Path(argv[index])))
        elif item.startswith("-"):
            raise ValueError(f"unknown option {item!r}")
        else:
            plain.append(Path(item))
        index += 1
    for path in plain:
        targets.append((path.resolve().name if public_labels else "", path))
    return targets, public_labels


def main(argv: list[str]) -> int:  # pragma: no cover - operator entry point
    if not argv:
        print(_USAGE, file=sys.stderr)
        return 2
    try:
        targets, _ = _parse_argv(argv)
    except (ValueError, IndexError) as error:
        print(f"{error}\n\n{_USAGE}", file=sys.stderr)
        return 2
    if not targets:
        print(_USAGE, file=sys.stderr)
        return 2
    print(json.dumps(aggregate(survey(targets)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - operator entry point
    raise SystemExit(main(sys.argv[1:]))


__all__ = [
    "AUTHORITY_BEARING_DIMENSIONS",
    "CLASSIFICATION_DIMENSION_NAMES",
    "EvidenceRejection",
    "HIGH_COVERAGE_SHARE",
    "INCOMPLETE_WALK_COVERAGE_SHARE",
    "RESOLVED_DIMENSIONS_PER_EVIDENCE_SOURCE",
    "RealRepositorySurvey",
    "RealSurveyResult",
    "aggregate",
    "asdict",
    "baseline_comparison_rows",
    "build_adversarial_project",
    "survey",
    "survey_repository",
]
