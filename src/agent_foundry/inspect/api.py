"""Read-only project inspection API."""

from __future__ import annotations

from pathlib import Path

from agent_foundry.models.base import FOUNDRY_SCHEMA_VERSION
from agent_foundry.models.project import ProjectIntake, TraversalLimits, TraversalStats
from agent_foundry.inspect.classification import propose_classification_findings
from agent_foundry.inspect.collectors import (
    collect_agent_rule_observations,
    collect_nested_project_observations,
    collect_config_schema_observations,
    collect_foundry_observations,
    collect_integration_observations,
    collect_metadata_observations,
    collect_revision_observation,
    collect_runtime_deploy_observations,
    collect_structure_observations,
    collect_test_lint_ci_observations,
    collect_unobservable_observations,
    collect_unread_file_observations,
)
from agent_foundry.inspect.conventions import discover_conventions
from agent_foundry.inspect.readiness import assess_readiness
from agent_foundry.inspect.traversal import (
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_ENTRIES,
    DEFAULT_MAX_FILE_BYTES,
    SKIP_DIR_NAMES,
    entries_outside,
    git_head_revision,
    nested_project_roots,
    walk_repository,
)


def inspect_project(
    project_path: str | Path,
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_entries: int = DEFAULT_MAX_ENTRIES,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> ProjectIntake:
    """Inspect a local repository path and return typed, provenance-bearing evidence."""
    root = Path(project_path).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"project path is not a directory: {project_path}")

    traversal = walk_repository(root, max_depth=max_depth, max_entries=max_entries)
    revision = git_head_revision(root)

    # One target, one project. A directory below the root carrying its own project
    # manifest belongs to somebody else, and every collector below reads `owned`
    # rather than the full walk so that its files are not attributed here. The
    # boundaries themselves are recorded, so the exclusion is a stated fact rather
    # than an absence.
    boundaries = nested_project_roots(root, traversal.entries)
    owned = entries_outside(traversal.entries, boundaries)

    observations: list = []
    observations.extend(collect_structure_observations(root, owned))
    observations.extend(collect_revision_observation(root, revision))
    observations.extend(collect_nested_project_observations(boundaries))
    observations.extend(collect_metadata_observations(root, owned))
    observations.extend(collect_agent_rule_observations(root, owned))
    observations.extend(
        collect_test_lint_ci_observations(
            root,
            owned,
            max_file_bytes=max_file_bytes,
        )
    )
    observations.extend(collect_config_schema_observations(root, owned))
    observations.extend(collect_runtime_deploy_observations(root, owned))
    observations.extend(collect_integration_observations(root, owned))
    observations.extend(
        collect_foundry_observations(
            root,
            owned,
            max_file_bytes=max_file_bytes,
        )
    )
    observations.extend(
        collect_unread_file_observations(
            owned,
            max_file_bytes=max_file_bytes,
        )
    )
    observations.extend(collect_unobservable_observations(traversal.unobservable))

    observations.sort(key=lambda o: (o.subject, o.content, o.provenance.source_ref or ""))

    classification_findings = propose_classification_findings(
        root,
        owned,
        observations,
        max_file_bytes=max_file_bytes,
    )
    conventions = discover_conventions(
        root,
        owned,
        observations,
        max_file_bytes=max_file_bytes,
    )
    readiness_findings = assess_readiness(root, observations, conventions)

    limits = TraversalLimits(
        max_depth=max_depth,
        max_entries=max_entries,
        max_file_bytes=max_file_bytes,
        skipped_dir_names=sorted(SKIP_DIR_NAMES),
    )
    stats = TraversalStats(
        entries_visited=traversal.entries_visited,
        entries_skipped=traversal.entries_skipped,
        entries_skipped_ignored_dir=traversal.entries_skipped_ignored_dir,
        entries_skipped_refused=traversal.entries_skipped_refused,
        entries_skipped_unreadable=traversal.entries_skipped_unreadable,
        entries_unobservable=len(traversal.unobservable),
        depth_limit_reached=traversal.depth_limit_reached,
        entry_limit_reached=traversal.entry_limit_reached,
        limits=limits,
    )

    return ProjectIntake(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        project_root=".",
        repository_revision=revision,
        observations=observations,
        classification_findings=classification_findings,
        conventions=conventions,
        readiness_findings=readiness_findings,
        traversal_stats=stats,
    )
