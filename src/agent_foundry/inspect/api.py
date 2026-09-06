"""Read-only project inspection API."""

from __future__ import annotations

from pathlib import Path

from agent_foundry.models.base import FOUNDRY_SCHEMA_VERSION
from agent_foundry.models.common import Provenance, ProvenanceKind
from agent_foundry.models.project import ProjectIntake, ProjectObservation, TraversalLimits, TraversalStats
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
    load_nested_project_overrides,
    resolve_nested_project_boundaries,
    walk_repository,
)
from agent_foundry.inspect.traversal import NestedProjectOverrideDecision, NestedProjectOverrides


def _override_decision_observations(
    decisions: list[NestedProjectOverrideDecision],
) -> list[ProjectObservation]:
    """Render every override decision through the existing `nested-project` subject.

    An override outcome is a fact about the same dimension the default heuristic
    already reports on — which subtrees are excluded, and why — not a new kind
    of thing to observe, so it is recorded through the same subject rather than
    a new one. `collect_nested_project_observations` covers the default-heuristic
    half of this evidence; this covers the override half. A malformed override
    is reported with `ProvenanceKind.OBSERVED` (a fact Foundry noticed about the
    declaration, not one the owner successfully declared); an override that did
    parse — applied or not — is `ProvenanceKind.DECLARED`, since it originates in
    the owner's own file.
    """
    observations: list[ProjectObservation] = []
    for decision in decisions:
        kind = (
            ProvenanceKind.OBSERVED
            if decision.action == "malformed"
            else ProvenanceKind.DECLARED
        )
        status = "applied" if decision.applied else "not applied"
        observations.append(
            ProjectObservation(
                subject="nested-project",
                content=(
                    f"override {decision.action} on {decision.path}: {status} — {decision.reason}"
                ),
                provenance=Provenance(kind=kind, confidence=1.0, source_ref=decision.path),
            )
        )
    return observations


def inspect_project(
    project_path: str | Path,
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_entries: int = DEFAULT_MAX_ENTRIES,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    nested_project_overrides: NestedProjectOverrides | None = None,
) -> ProjectIntake:
    """Inspect a local repository path and return typed, provenance-bearing evidence.

    `nested_project_overrides` lets a caller supply the owner's nested-project
    override directly instead of having it read from `.foundry/project.yaml`
    (the default, `None`, path every normal caller takes — the declaration
    surface Foundry already owns). Passing an explicit value is for callers
    that already have one in hand (tests, or a caller composing overrides from
    elsewhere); it is used verbatim, including a deliberately-constructed
    malformed one, which still fails closed to the default heuristic.
    """
    root = Path(project_path).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"project path is not a directory: {project_path}")

    traversal = walk_repository(root, max_depth=max_depth, max_entries=max_entries)
    revision = git_head_revision(root)

    # One target, one project. A directory below the root carrying its own project
    # manifest belongs to somebody else, and every collector below reads `owned`
    # rather than the full walk so that its files are not attributed here. The
    # default boundaries are a heuristic; an owner-declared override (read from
    # `.foundry/project.yaml` unless supplied directly) may re-include or add to
    # them, and either way the outcome is recorded, so every exclusion — and
    # every override decision, applied or not — is a stated fact rather than an
    # absence.
    overrides = (
        nested_project_overrides
        if nested_project_overrides is not None
        else load_nested_project_overrides(root, traversal.entries, max_file_bytes=max_file_bytes)
    )
    boundaries, override_decisions = resolve_nested_project_boundaries(
        root, traversal.entries, overrides
    )
    owned = entries_outside(traversal.entries, boundaries)

    observations: list = []
    observations.extend(collect_structure_observations(root, owned))
    observations.extend(collect_revision_observation(root, revision))
    owner_declared_boundaries = frozenset(
        decision.path
        for decision in override_decisions
        if decision.action == "exclude" and decision.applied
    )
    observations.extend(
        collect_nested_project_observations(
            boundaries, owner_declared=owner_declared_boundaries
        )
    )
    observations.extend(_override_decision_observations(override_decisions))
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

    # Readiness is assessed after the traversal statistics exist, and is given them.
    # Without `stats` it can only see the two hole kinds that happen to travel as
    # observations (`path-unobservable`, `file-read-skipped`); a depth or entry limit
    # and a containment refusal are recorded nowhere else, so absence would read as
    # settled on a walk that never reached the evidence.
    readiness_findings = assess_readiness(root, observations, conventions, stats=stats)

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
