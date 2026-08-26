"""Measure adoption friction across many repositories, emitting counts and nothing else.

The V0.1 readiness report quotes aggregate figures over local repositories that are not
part of this branch and cannot be. This module is the method behind those figures, kept
here so the *measurement* is reproducible even where the *targets* are not: anyone can
point it at their own directories and get a comparably-shaped result.

    python -m tests.e2e.friction_survey ~/code ~/work

Privacy is structural, not a promise. `RepositorySurvey` holds integers and booleans;
the only string-valued field is a convention *subject*, which comes from Foundry's own
fixed vocabulary rather than from any repository. There is no field a path, a project
name, or a file's contents could be written into, so a leak would have to be a change to
this file rather than an oversight in using it — and `test_e2e_friction_survey.py`
checks that shape holds.
"""

from __future__ import annotations

import json
import statistics
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from agent_foundry.adopt import plan_adoption
from agent_foundry.inspect import inspect_project
from agent_foundry.toolkit import resolve_toolkit

# Every manifest characteristic an owner can declare. The count of populated ones is
# the headline friction number: what inspection alone can supply is one of these.
MANIFEST_DIMENSION_COUNT = 16


@dataclass(frozen=True)
class RepositorySurvey:
    """Counts for one repository. No field can hold a path, a name, or content."""

    entries_visited: int
    entry_limit_reached: bool
    depth_limit_reached: bool
    entries_unobservable: int
    files_over_read_limit: int
    revision_resolved: bool
    declaration_present: bool
    manifest_fields_populated: int
    conventions_discovered: int
    convention_subjects: tuple[str, ...]
    readiness_blockers: int
    adoption_changes: int
    adoption_actions: tuple[str, ...]
    roles_resolved: int
    capabilities_resolved: int


@dataclass
class SurveyResult:
    """Aggregate over every repository surveyed, plus a count of those that failed."""

    surveys: list[RepositorySurvey] = field(default_factory=list)
    failed: int = 0
    failure_types: tuple[str, ...] = ()


def survey_repository(path: Path) -> RepositorySurvey:
    intake = inspect_project(path)
    plan = plan_adoption(intake)
    manifest = plan.manifest
    _, lock = resolve_toolkit(manifest)

    work_modes = manifest.project.work_modes
    # One entry per member of `CLASSIFICATION_DIMENSIONS`, in the same order, so
    # "n of MANIFEST_DIMENSION_COUNT" means what it says. A test pins the two lengths
    # together.
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

    return RepositorySurvey(
        entries_visited=intake.traversal_stats.entries_visited,
        entry_limit_reached=intake.traversal_stats.entry_limit_reached,
        depth_limit_reached=intake.traversal_stats.depth_limit_reached,
        entries_unobservable=intake.traversal_stats.entries_unobservable,
        files_over_read_limit=sum(
            1 for item in intake.observations if item.subject == "file-read-skipped"
        ),
        revision_resolved=intake.repository_revision is not None,
        declaration_present=any(
            item.subject == "foundry-declaration" for item in intake.observations
        ),
        manifest_fields_populated=sum(1 for value in populated if value not in (None, [])),
        conventions_discovered=len(intake.conventions),
        convention_subjects=tuple(sorted({item.subject for item in intake.conventions})),
        readiness_blockers=sum(1 for item in intake.readiness_findings if item.blocker),
        adoption_changes=len(plan.change_set.changes),
        adoption_actions=tuple(
            sorted({change.action.value for change in plan.change_set.changes})
        ),
        roles_resolved=len(lock.role_ids),
        capabilities_resolved=len(lock.capability_ids),
    )


def discover_repositories(roots: list[Path]) -> list[Path]:
    """Immediate children of *roots* that are git repositories, in a stable order."""
    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if child.name.startswith((".", "_")):
                continue
            if child.is_dir() and (child / ".git").exists():
                found.append(child)
    return found


def survey(paths: list[Path]) -> SurveyResult:
    result = SurveyResult()
    failures: list[str] = []
    for path in paths:
        try:
            result.surveys.append(survey_repository(path))
        except Exception as error:  # noqa: BLE001 - the type is the whole record
            # The exception *type* is recorded and its message is not: a message from a
            # failed inspection routinely quotes the path that failed.
            result.failed += 1
            failures.append(type(error).__name__)
    result.failure_types = tuple(sorted(set(failures)))
    return result


def aggregate(result: SurveyResult) -> dict[str, object]:
    """Counts only. Every value here is a number, a boolean, or a vocabulary term."""
    surveys = result.surveys
    if not surveys:
        return {"repositories": 0, "failed": result.failed, "failure_types": list(result.failure_types)}

    action_counts: dict[str, int] = {}
    for item in surveys:
        for action in item.adoption_actions:
            action_counts[action] = action_counts.get(action, 0) + 1
    subject_counts: dict[str, int] = {}
    for item in surveys:
        for subject in item.convention_subjects:
            subject_counts[subject] = subject_counts.get(subject, 0) + 1

    populated = [item.manifest_fields_populated for item in surveys]
    return {
        "repositories": len(surveys),
        "failed": result.failed,
        "failure_types": list(result.failure_types),
        "manifest_dimension_count": MANIFEST_DIMENSION_COUNT,
        "entry_limit_reached": sum(1 for item in surveys if item.entry_limit_reached),
        "depth_limit_reached": sum(1 for item in surveys if item.depth_limit_reached),
        "entries_visited_median": int(statistics.median(item.entries_visited for item in surveys)),
        "repositories_with_unobservable_paths": sum(
            1 for item in surveys if item.entries_unobservable
        ),
        "files_over_read_limit_total": sum(item.files_over_read_limit for item in surveys),
        "files_over_read_limit_max": max(item.files_over_read_limit for item in surveys),
        "revision_resolved": sum(1 for item in surveys if item.revision_resolved),
        "declaration_present": sum(1 for item in surveys if item.declaration_present),
        "manifest_fields_populated_min": min(populated),
        "manifest_fields_populated_median": int(statistics.median(populated)),
        "manifest_fields_populated_max": max(populated),
        "conventions_total": sum(item.conventions_discovered for item in surveys),
        "conventions_median": int(statistics.median(item.conventions_discovered for item in surveys)),
        "conventions_max": max(item.conventions_discovered for item in surveys),
        "convention_subjects": dict(sorted(subject_counts.items())),
        "readiness_blockers_total": sum(item.readiness_blockers for item in surveys),
        "adoption_changes_median": int(
            statistics.median(item.adoption_changes for item in surveys)
        ),
        "adoption_actions": dict(sorted(action_counts.items())),
        "repositories_resolving_any_role": sum(1 for item in surveys if item.roles_resolved),
        "repositories_resolving_any_capability": sum(
            1 for item in surveys if item.capabilities_resolved
        ),
    }


def main(argv: list[str]) -> int:  # pragma: no cover - operator entry point
    if not argv:
        print(
            "usage: python -m tests.e2e.friction_survey DIR [DIR ...]\n"
            "Surveys every git repository directly inside each DIR and prints counts.",
            file=sys.stderr,
        )
        return 2
    targets = discover_repositories([Path(item) for item in argv])
    print(json.dumps(aggregate(survey(targets)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - operator entry point
    raise SystemExit(main(sys.argv[1:]))


__all__ = [
    "MANIFEST_DIMENSION_COUNT",
    "RepositorySurvey",
    "SurveyResult",
    "aggregate",
    "asdict",
    "discover_repositories",
    "survey",
    "survey_repository",
]
