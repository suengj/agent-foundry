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


def _matching_fields(tokens: set[str], *, subject: str, pattern: str = "", evidence: str = "") -> list[str]:
    fields: list[str] = []
    if _relevance_score(tokens, subject) > 0:
        fields.append("subject")
    if pattern and _relevance_score(tokens, pattern) > 0:
        fields.append("pattern")
    if evidence and _relevance_score(tokens, evidence) > 0:
        fields.append("evidence")
    return fields


def _convention_selection_score(tokens: set[str], convention: ConventionSpec) -> float:
    return _relevance_score(
        tokens,
        convention.subject,
        convention.pattern,
        convention.evidence,
    ) * convention.confidence


def _observation_selection_score(tokens: set[str], observation: ProjectObservation) -> float:
    return _relevance_score(tokens, observation.subject, observation.content)


def _selection_rationale(
    *,
    component_kind: str,
    selected: bool,
    matching_fields: list[str],
    selection_score: float,
) -> str:
    if selected:
        fields = ", ".join(matching_fields) if matching_fields else "none"
        return (
            f"{component_kind} selected by work item scope overlap on {fields} "
            f"(selection score={selection_score:.2f})"
        )
    return f"{component_kind} not relevant to work item scope (selection score={selection_score:.2f})"


def select_relevant_conventions(
    work_item: WorkItemContract,
    conventions: list[ConventionSpec],
) -> tuple[list[ConventionSpec], list[BundleProvenanceRecord]]:
    """Select conventions relevant to the work item — bounded, not full project tree."""
    tokens = _scope_tokens(work_item)
    scored: list[tuple[float, ConventionSpec]] = []
    for convention in conventions:
        score = _convention_selection_score(tokens, convention)
        if score > 0:
            scored.append((score, convention))
    scored.sort(key=lambda item: (-item[0], item[1].subject, item[1].source_ref))

    selected = [convention for _, convention in scored[:_MAX_CONTEXT_ITEMS]]
    provenance: list[BundleProvenanceRecord] = []
    selected_subjects = {item.subject for item in selected}

    for convention in sorted(conventions, key=lambda item: item.subject):
        selection_score = _convention_selection_score(tokens, convention)
        matching_fields = _matching_fields(
            tokens,
            subject=convention.subject,
            pattern=convention.pattern,
            evidence=convention.evidence,
        )
        is_selected = convention.subject in selected_subjects
        provenance.append(
            BundleProvenanceRecord(
                component_kind="convention",
                component_id=convention.subject,
                selected=is_selected,
                rationale=_selection_rationale(
                    component_kind="convention",
                    selected=is_selected,
                    matching_fields=matching_fields,
                    selection_score=selection_score,
                ),
                source=ResolutionSource.PROJECT_FACT,
                project_fact=(
                    f"matching_fields={matching_fields or ['none']}; "
                    f"selection_score={selection_score:.2f}"
                ),
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
        score = _observation_selection_score(tokens, observation)
        if score > 0:
            scored.append((score, observation))
    scored.sort(key=lambda item: (-item[0], item[1].subject))

    selected = [observation for _, observation in scored[:_MAX_CONTEXT_ITEMS]]
    provenance: list[BundleProvenanceRecord] = []
    selected_subjects = {item.subject for item in selected}

    for observation in sorted(observations, key=lambda item: item.subject):
        selection_score = _observation_selection_score(tokens, observation)
        matching_fields = _matching_fields(
            tokens,
            subject=observation.subject,
            evidence=observation.content,
        )
        is_selected = observation.subject in selected_subjects
        provenance.append(
            BundleProvenanceRecord(
                component_kind="observation",
                component_id=observation.subject,
                selected=is_selected,
                rationale=_selection_rationale(
                    component_kind="observation",
                    selected=is_selected,
                    matching_fields=matching_fields,
                    selection_score=selection_score,
                ),
                source=ResolutionSource.PROJECT_FACT,
                project_fact=(
                    f"matching_fields={matching_fields or ['none']}; "
                    f"selection_score={selection_score:.2f}"
                ),
                evidence_refs=[observation.provenance.source_ref or observation.subject],
            )
        )
    return selected, provenance
