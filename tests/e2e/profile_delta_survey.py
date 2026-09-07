"""Before/after ProjectProfile comparison across repositories, counts only.

`tests/e2e/friction_survey.py` measures inspection and adoption *friction*: how much a
manifest gets populated, how much a toolkit resolves. It says nothing about the
**ProjectProfile** contract itself, and it has no notion of *before* and *after* — it
takes one snapshot of one code version. This module adds both, following the same
method rather than inventing a parallel one:

    python -m tests.e2e.profile_delta_survey snapshot REPO [REPO ...] > before.json
    # ... check out a different ref, or run from a different worktree ...
    python -m tests.e2e.profile_delta_survey snapshot REPO [REPO ...] > after.json
    python -m tests.e2e.profile_delta_survey compare before.json after.json

Two versions of the library are never imported into one process. Each `snapshot` call
runs against whatever code is on `sys.path` for that invocation; `compare` only ever
reads back two already-written JSON payloads and subtracts them.

Privacy is structural, not a promise, exactly as in `friction_survey.py`. Every
`ProfileSurvey` field is an `int`, a `bool`, or a tuple of terms drawn from Foundry's
own fixed vocabulary — never a value read out of a target repository. In particular: a
`ProfileDimension`'s *value* (the actual attributed string — a file path, a tool name, a
declared project name, prose) is never recorded anywhere in this module. Only the
dimension *name* is retained, and every dimension name that ever reaches a
`ProjectProfile` is a string literal fixed in `agent_foundry.profile.synth`'s source
(reused from the public `CLASSIFICATION_DIMENSIONS` vocabulary for the classification
half, and a small fixed set of structural dimension names for the rest) — it is never
built from, or copied out of, anything a target repository contains. That is a
stronger guarantee than "belongs to a closed enum": it is "cannot vary with repository
content at all". `test_e2e_profile_delta_survey.py` proves both the field-shape
property and, directly, that no fixture's own name or path ever appears in a recorded
dimension name or in any aggregate/comparison payload.

The `compare()` output is public-safe by the same argument, one level up: it is
computed by subtracting two payloads that are themselves already public-safe, so it can
only ever contain numbers and the same fixed vocabulary terms its inputs did.
"""

from __future__ import annotations

import json
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path

from agent_foundry.inspect import inspect_project
from agent_foundry.models import ProfileResolution, ProvenanceKind
from agent_foundry.profile import synthesize_project_profile

# Confidence is a float in [0, 1] or unstated. Recording the raw float risks recording
# something closer to content than a count; three fixed buckets plus "unstated" give a
# distribution without ever writing a target-derived number that isn't already just a
# count.
_CONFIDENCE_HIGH = 0.75
_CONFIDENCE_LOW = 0.25


@dataclass(frozen=True)
class ProfileSurvey:
    """Counts for one repository's ProjectProfile. No field can hold a value, a path,
    or repository content — only dimension *names*, which are fixed by code, never by
    what a repository contains (see the module docstring)."""

    dimensions_total: int
    dimensions_resolved: int
    dimensions_conflicted: int
    dimensions_unknown: int
    resolved_dimension_names: tuple[str, ...]
    conflicted_dimension_names: tuple[str, ...]
    unknown_dimension_names: tuple[str, ...]
    attributions_total: int
    attributions_observed: int
    attributions_declared: int
    attributions_inferred: int
    attributions_normative: int
    attributions_with_confidence: int
    attributions_confidence_high: int
    attributions_confidence_mid: int
    attributions_confidence_low: int
    attributions_with_evidence_refs: int
    attributions_without_evidence_refs: int
    readiness_findings_total: int
    readiness_blockers: int
    walk_exhaustive: bool
    project_name_present: bool


@dataclass
class ProfileSurveyResult:
    """Aggregate over every repository profiled, plus a count of those that failed."""

    surveys: list[ProfileSurvey] = field(default_factory=list)
    failed: int = 0
    failure_types: tuple[str, ...] = ()


def _confidence_bucket(confidence: float) -> str:
    if confidence >= _CONFIDENCE_HIGH:
        return "high"
    if confidence < _CONFIDENCE_LOW:
        return "low"
    return "mid"


def survey_repository_profile(path: Path) -> ProfileSurvey:
    intake = inspect_project(path)
    profile = synthesize_project_profile(intake)
    stats = intake.traversal_stats
    unread_files = sum(1 for item in intake.observations if item.subject == "file-read-skipped")

    resolved = [d for d in profile.dimensions if d.resolution is ProfileResolution.RESOLVED]
    conflicted = [d for d in profile.dimensions if d.resolution is ProfileResolution.CONFLICTED]
    unknown = [d for d in profile.dimensions if d.resolution is ProfileResolution.UNKNOWN]

    attributions = [a for d in profile.dimensions for a in d.attributions]
    kind_counts = {kind: 0 for kind in ProvenanceKind}
    for attribution in attributions:
        kind_counts[attribution.provenance.kind] += 1

    with_confidence = [a for a in attributions if a.provenance.confidence is not None]
    buckets = {"high": 0, "mid": 0, "low": 0}
    for attribution in with_confidence:
        buckets[_confidence_bucket(attribution.provenance.confidence)] += 1

    with_evidence = sum(1 for a in attributions if a.evidence_refs)

    # Mirrors `_traversal_exhaustive` in `agent_foundry.profile.synth`: a walk that hit
    # a depth/entry limit, left a path unobservable, refused a containment escape, or
    # skipped a file for size is not exhaustive, and any "absence" reading from it is
    # not confirmed absence — only reported absence over an incomplete walk. This is
    # recomputed here from the same public `TraversalStats` fields `friction_survey.py`
    # already reads, rather than importing that module's private helper.
    walk_exhaustive = (
        not stats.depth_limit_reached
        and not stats.entry_limit_reached
        and stats.entries_unobservable == 0
        and stats.entries_skipped_refused == 0
        and unread_files == 0
    )

    return ProfileSurvey(
        dimensions_total=len(profile.dimensions),
        dimensions_resolved=len(resolved),
        dimensions_conflicted=len(conflicted),
        dimensions_unknown=len(unknown),
        resolved_dimension_names=tuple(sorted(d.dimension for d in resolved)),
        conflicted_dimension_names=tuple(sorted(d.dimension for d in conflicted)),
        unknown_dimension_names=tuple(sorted(d.dimension for d in unknown)),
        attributions_total=len(attributions),
        attributions_observed=kind_counts[ProvenanceKind.OBSERVED],
        attributions_declared=kind_counts[ProvenanceKind.DECLARED],
        attributions_inferred=kind_counts[ProvenanceKind.INFERRED],
        attributions_normative=kind_counts[ProvenanceKind.NORMATIVE],
        attributions_with_confidence=len(with_confidence),
        attributions_confidence_high=buckets["high"],
        attributions_confidence_mid=buckets["mid"],
        attributions_confidence_low=buckets["low"],
        attributions_with_evidence_refs=with_evidence,
        attributions_without_evidence_refs=len(attributions) - with_evidence,
        readiness_findings_total=len(intake.readiness_findings),
        readiness_blockers=sum(1 for item in intake.readiness_findings if item.blocker),
        walk_exhaustive=walk_exhaustive,
        project_name_present=profile.project_name is not None,
    )


def survey_profiles(paths: list[Path]) -> ProfileSurveyResult:
    result = ProfileSurveyResult()
    failures: list[str] = []
    for path in paths:
        try:
            result.surveys.append(survey_repository_profile(path))
        except Exception as error:  # noqa: BLE001 - the type is the whole record
            # As in friction_survey.py: the exception *type* is recorded, never its
            # message — an inspection failure routinely quotes the path that failed.
            result.failed += 1
            failures.append(type(error).__name__)
    result.failure_types = tuple(sorted(set(failures)))
    return result


def _name_counts(surveys: list[ProfileSurvey], attr: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in surveys:
        for name in getattr(item, attr):
            counts[name] = counts.get(name, 0) + 1
    return counts


def aggregate_profile(result: ProfileSurveyResult) -> dict[str, object]:
    """Counts only. Every value here is a number, a boolean, or a vocabulary term."""
    surveys = result.surveys
    if not surveys:
        return {
            "repositories": 0,
            "failed": result.failed,
            "failure_types": list(result.failure_types),
        }

    dims = [item.dimensions_total for item in surveys]
    resolved = [item.dimensions_resolved for item in surveys]
    return {
        "repositories": len(surveys),
        "failed": result.failed,
        "failure_types": list(result.failure_types),
        "dimensions_total_min": min(dims),
        "dimensions_total_median": int(statistics.median(dims)),
        "dimensions_total_max": max(dims),
        "dimensions_resolved_min": min(resolved),
        "dimensions_resolved_median": int(statistics.median(resolved)),
        "dimensions_resolved_max": max(resolved),
        "dimensions_conflicted_total": sum(item.dimensions_conflicted for item in surveys),
        "dimensions_unknown_total": sum(item.dimensions_unknown for item in surveys),
        "resolved_dimension_counts": dict(sorted(_name_counts(surveys, "resolved_dimension_names").items())),
        "conflicted_dimension_counts": dict(
            sorted(_name_counts(surveys, "conflicted_dimension_names").items())
        ),
        "unknown_dimension_counts": dict(sorted(_name_counts(surveys, "unknown_dimension_names").items())),
        "attributions_total": sum(item.attributions_total for item in surveys),
        "attributions_observed": sum(item.attributions_observed for item in surveys),
        "attributions_declared": sum(item.attributions_declared for item in surveys),
        "attributions_inferred": sum(item.attributions_inferred for item in surveys),
        "attributions_normative": sum(item.attributions_normative for item in surveys),
        "attributions_with_confidence": sum(item.attributions_with_confidence for item in surveys),
        "attributions_confidence_high": sum(item.attributions_confidence_high for item in surveys),
        "attributions_confidence_mid": sum(item.attributions_confidence_mid for item in surveys),
        "attributions_confidence_low": sum(item.attributions_confidence_low for item in surveys),
        "attributions_with_evidence_refs": sum(item.attributions_with_evidence_refs for item in surveys),
        "attributions_without_evidence_refs": sum(
            item.attributions_without_evidence_refs for item in surveys
        ),
        "readiness_findings_total": sum(item.readiness_findings_total for item in surveys),
        "readiness_blockers_total": sum(item.readiness_blockers for item in surveys),
        "repositories_with_exhaustive_walk": sum(1 for item in surveys if item.walk_exhaustive),
        "repositories_with_incomplete_walk_and_any_unknown_dimension": sum(
            1 for item in surveys if not item.walk_exhaustive and item.dimensions_unknown > 0
        ),
        "repositories_with_project_name": sum(1 for item in surveys if item.project_name_present),
    }


def _numeric_delta(before: dict[str, object], after: dict[str, object], key: str) -> int | None:
    before_val, after_val = before.get(key), after.get(key)
    if isinstance(before_val, bool) or isinstance(after_val, bool):
        return None
    if isinstance(before_val, (int, float)) and isinstance(after_val, (int, float)):
        return after_val - before_val
    return None


def compare(before: dict[str, object], after: dict[str, object]) -> dict[str, object]:
    """Delta between two `aggregate_profile()` payloads. Numbers and vocabulary only.

    Public-safe by construction: it never reads anything but the two already
    public-safe payloads it is handed, and every value it produces is either an
    integer delta or a delta over a fixed-vocabulary-keyed count dict.
    """
    delta: dict[str, object] = {}
    all_keys = sorted(set(before) | set(after))
    for key in all_keys:
        before_val, after_val = before.get(key), after.get(key)
        if isinstance(before_val, dict) or isinstance(after_val, dict):
            before_dict = before_val if isinstance(before_val, dict) else {}
            after_dict = after_val if isinstance(after_val, dict) else {}
            names = sorted(set(before_dict) | set(after_dict))
            delta[key] = {
                name: after_dict.get(name, 0) - before_dict.get(name, 0)
                for name in names
                if after_dict.get(name, 0) - before_dict.get(name, 0) != 0
            }
            continue
        numeric = _numeric_delta(before, after, key)
        if numeric is not None:
            if numeric != 0:
                delta[key] = numeric
            continue
        # Anything left over (e.g. `failure_types`, a list of vocabulary terms) is
        # reported as an unordered set-difference of terms, never as raw before/after
        # text — this is the one place a genuinely non-numeric field can appear, and
        # it is still only ever fixed-vocabulary terms.
        before_set = set(before_val) if isinstance(before_val, (list, tuple)) else set()
        after_set = set(after_val) if isinstance(after_val, (list, tuple)) else set()
        added = sorted(after_set - before_set)
        removed = sorted(before_set - after_set)
        if added or removed:
            delta[key] = {"added": added, "removed": removed}
    return delta


def main(argv: list[str]) -> int:  # pragma: no cover - operator entry point
    usage = (
        "usage:\n"
        "  python -m tests.e2e.profile_delta_survey snapshot REPO [REPO ...]\n"
        "  python -m tests.e2e.profile_delta_survey compare BEFORE.json AFTER.json\n"
        "snapshot profiles each REPO with the code on sys.path for *this* invocation "
        "and prints the aggregate. compare reads back two such payloads and prints "
        "their delta. Run snapshot once per code version (a separate checkout or "
        "worktree per ref) to build a before/after pair."
    )
    if not argv:
        print(usage, file=sys.stderr)
        return 2
    mode, rest = argv[0], argv[1:]
    if mode == "snapshot":
        targets = [Path(item) for item in rest] or [Path(".")]
        result = survey_profiles(targets)
        print(json.dumps(aggregate_profile(result), indent=2, sort_keys=True))
        return 0
    if mode == "compare":
        if len(rest) != 2:
            print(usage, file=sys.stderr)
            return 2
        before = json.loads(Path(rest[0]).read_text())
        after = json.loads(Path(rest[1]).read_text())
        print(json.dumps(compare(before, after), indent=2, sort_keys=True))
        return 0
    print(usage, file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover - operator entry point
    raise SystemExit(main(sys.argv[1:]))


__all__ = [
    "ProfileSurvey",
    "ProfileSurveyResult",
    "aggregate_profile",
    "compare",
    "survey_profiles",
    "survey_repository_profile",
]
