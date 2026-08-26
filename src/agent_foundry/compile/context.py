"""Progressive disclosure for conventions and observations."""

from __future__ import annotations

import re

from agent_foundry.models.execution import BundleProvenanceRecord
from agent_foundry.models.project import ConventionSpec, ProjectObservation
from agent_foundry.models.toolkit import ResolutionSource
from agent_foundry.models.work import WorkItemContract

_MAX_CONTEXT_ITEMS = 5
_TOKEN_SPLIT = re.compile(r"[\s/._:-]+")


def _scope_tokens(work_item: WorkItemContract) -> set[str]:
    tokens: set[str] = set()
    for text in [*work_item.scope, work_item.objective, work_item.title]:
        tokens.update(token for token in _TOKEN_SPLIT.split(text.lower()) if token)
    return tokens


def _relevance_score(tokens: set[str], *texts: str) -> float:
    if not tokens:
        return 0.0
    haystack_tokens: set[str] = set()
    for text in texts:
        haystack_tokens.update(token for token in _TOKEN_SPLIT.split(text.lower()) if token)
    if not haystack_tokens:
        return 0.0
    overlap = tokens & haystack_tokens
    return len(overlap) / max(len(tokens), 1)


def select_relevant_conventions(
    work_item: WorkItemContract,
    conventions: list[ConventionSpec],
) -> tuple[list[ConventionSpec], list[BundleProvenanceRecord]]:
    """Select conventions relevant to the work item — bounded, not full project tree."""
    tokens = _scope_tokens(work_item)
    scored: list[tuple[float, ConventionSpec]] = []
    for convention in conventions:
        score = _relevance_score(
            tokens,
            convention.subject,
            convention.pattern,
            convention.evidence,
        )
        if score > 0:
            scored.append((score * convention.confidence, convention))
    scored.sort(key=lambda item: (-item[0], item[1].subject, item[1].source_ref))

    selected = [convention for _, convention in scored[:_MAX_CONTEXT_ITEMS]]
    provenance: list[BundleProvenanceRecord] = []
    selected_subjects = {item.subject for item in selected}

    for convention in sorted(conventions, key=lambda item: item.subject):
        is_selected = convention.subject in selected_subjects
        if is_selected:
            rationale = "convention subject overlaps work item scope"
        else:
            rationale = "convention not relevant to work item scope"
        provenance.append(
            BundleProvenanceRecord(
                component_kind="convention",
                component_id=convention.subject,
                selected=is_selected,
                rationale=rationale,
                source=ResolutionSource.PROJECT_FACT,
                project_fact=f"work_item.scope overlap score={_relevance_score(tokens, convention.subject):.2f}",
                evidence_refs=[convention.source_ref],
            )
        )
    return selected, provenance


def select_relevant_observations(
    work_item: WorkItemContract,
    observations: list[ProjectObservation],
) -> tuple[list[ProjectObservation], list[BundleProvenanceRecord]]:
    """Select observations relevant to the work item."""
    tokens = _scope_tokens(work_item)
    scored: list[tuple[float, ProjectObservation]] = []
    for observation in observations:
        score = _relevance_score(tokens, observation.subject, observation.content)
        if score > 0:
            scored.append((score, observation))
    scored.sort(key=lambda item: (-item[0], item[1].subject))

    selected = [observation for _, observation in scored[:_MAX_CONTEXT_ITEMS]]
    provenance: list[BundleProvenanceRecord] = []
    selected_subjects = {item.subject for item in selected}

    for observation in sorted(observations, key=lambda item: item.subject):
        is_selected = observation.subject in selected_subjects
        provenance.append(
            BundleProvenanceRecord(
                component_kind="observation",
                component_id=observation.subject,
                selected=is_selected,
                rationale=(
                    "observation subject overlaps work item scope"
                    if is_selected
                    else "observation not relevant to work item scope"
                ),
                source=ResolutionSource.PROJECT_FACT,
                project_fact=f"work_item.scope overlap score={_relevance_score(tokens, observation.subject):.2f}",
                evidence_refs=[observation.provenance.source_ref or observation.subject],
            )
        )
    return selected, provenance
