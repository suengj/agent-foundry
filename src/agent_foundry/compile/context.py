"""Progressive disclosure for conventions and observations."""

from __future__ import annotations

import re

from agent_foundry.models.execution import BundleProvenanceRecord
from agent_foundry.models.project import ConventionSpec, ProjectObservation
from agent_foundry.models.toolkit import ResolutionSource
from agent_foundry.models.work import WorkItemContract

_MAX_CONTEXT_ITEMS = 5
# Provenance answers "why is this in the bundle" for everything that competed for a
# slot. Material that scored zero never competed, so it is summarized in a single
# record rather than itemized — otherwise the bundle would grow linearly with
# project material the work item has nothing to do with.
_MAX_REJECTED_PROVENANCE_ITEMS = 10
_TOKEN_SPLIT = re.compile(r"[\s/._:-]+")


def _tokenize(*texts: str) -> set[str]:
    tokens: set[str] = set()
    for text in texts:
        tokens.update(token for token in _TOKEN_SPLIT.split(text.lower()) if token)
    return tokens


def _work_item_token_sources(work_item: WorkItemContract) -> dict[str, set[str]]:
    """Tokens per originating Work Item field, so provenance can name the real cause.

    Selection draws on scope, objective, and title alike. Reporting all three as
    "scope overlap" would be a false rationale, so the field each matching token came
    from is kept separate all the way through to the provenance record.
    """
    return {
        "scope": _tokenize(*work_item.scope),
        "objective": _tokenize(work_item.objective),
        "title": _tokenize(work_item.title),
    }


def _scope_tokens(work_item: WorkItemContract) -> set[str]:
    tokens: set[str] = set()
    for source_tokens in _work_item_token_sources(work_item).values():
        tokens |= source_tokens
    return tokens


def _matching_work_item_fields(
    token_sources: dict[str, set[str]], *texts: str
) -> list[str]:
    """Which Work Item fields actually supplied a token this candidate matched."""
    candidate_tokens = _tokenize(*texts)
    return [
        field
        for field in ("scope", "objective", "title")
        if token_sources.get(field, set()) & candidate_tokens
    ]


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
    work_item_fields: list[str],
    selection_score: float,
) -> str:
    if selected:
        fields = ", ".join(matching_fields) if matching_fields else "none"
        origin = ", ".join(work_item_fields) if work_item_fields else "none"
        return (
            f"{component_kind} selected because its {fields} shares tokens with the "
            f"work item {origin} (selection score={selection_score:.2f})"
        )
    return (
        f"{component_kind} shares no token with the work item scope, objective, or "
        f"title (selection score={selection_score:.2f})"
    )


def _rejected_summary_record(
    *,
    component_kind: str,
    unscored_ids: list[str],
    unlisted_scored: list[tuple[float, str]],
) -> BundleProvenanceRecord | None:
    """One record standing in for candidates not itemized above.

    Itemized provenance covers every selected component plus the highest-scoring
    near-misses — the information needed to answer "why this and not that". Everything
    further down the ranking is counted, not enumerated, so an ExecutionBundle stays
    bounded no matter how much material the project holds.
    """
    if not unscored_ids and not unlisted_scored:
        return None

    parts: list[str] = []
    if unlisted_scored:
        top = max(score for score, _ in unlisted_scored)
        parts.append(
            f"{len(unlisted_scored)} scored candidate(s) ranked below the itemized "
            f"near-misses (highest unlisted selection score={top:.2f})"
        )
    if unscored_ids:
        parts.append(
            f"{len(unscored_ids)} candidate(s) shared no token with the work item scope, "
            f"objective, or title and never competed for a slot"
        )

    sample = [name for _, name in unlisted_scored[:_MAX_REJECTED_PROVENANCE_ITEMS]]
    sample.extend(unscored_ids[: max(0, _MAX_REJECTED_PROVENANCE_ITEMS - len(sample))])
    remainder = (len(unlisted_scored) + len(unscored_ids)) - len(sample)
    listed = ", ".join(sample)
    if remainder > 0:
        listed = f"{listed}, +{remainder} more"

    return BundleProvenanceRecord(
        component_kind=f"{component_kind}-not-selected",
        component_id=f"{component_kind}:remainder",
        selected=False,
        rationale=f"{component_kind} candidates not selected: " + "; ".join(parts),
        source=ResolutionSource.PROJECT_FACT,
        project_fact=(
            f"unlisted_scored={len(unlisted_scored)}; unscored={len(unscored_ids)}; "
            f"sample=[{listed}]"
        ),
        evidence_refs=[],
    )


def select_relevant_conventions(
    work_item: WorkItemContract,
    conventions: list[ConventionSpec],
) -> tuple[list[ConventionSpec], list[BundleProvenanceRecord]]:
    """Select conventions relevant to the work item — bounded, not full project tree."""
    token_sources = _work_item_token_sources(work_item)
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

    # Itemize the selected items and the highest-scoring near-misses; count the rest.
    itemized_limit = _MAX_CONTEXT_ITEMS + _MAX_REJECTED_PROVENANCE_ITEMS
    itemized = scored[:itemized_limit]
    unlisted_scored = [(score, item.subject) for score, item in scored[itemized_limit:]]
    scored_subjects = {item.subject for _, item in scored}
    unscored_ids = sorted(
        convention.subject
        for convention in conventions
        if convention.subject not in scored_subjects
    )

    for selection_score, convention in itemized:
        matching_fields = _matching_fields(
            tokens,
            subject=convention.subject,
            pattern=convention.pattern,
            evidence=convention.evidence,
        )
        work_item_fields = _matching_work_item_fields(
            token_sources, convention.subject, convention.pattern, convention.evidence
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
                    work_item_fields=work_item_fields,
                    selection_score=selection_score,
                ),
                source=ResolutionSource.PROJECT_FACT,
                project_fact=(
                    f"matching_fields={matching_fields or ['none']}; "
                    f"work_item_fields={work_item_fields or ['none']}; "
                    f"selection_score={selection_score:.2f}"
                ),
                evidence_refs=[convention.source_ref],
            )
        )

    summary = _rejected_summary_record(
        component_kind="convention",
        unscored_ids=unscored_ids,
        unlisted_scored=unlisted_scored,
    )
    if summary is not None:
        provenance.append(summary)
    return selected, provenance


def select_relevant_observations(
    work_item: WorkItemContract,
    observations: list[ProjectObservation],
) -> tuple[list[ProjectObservation], list[BundleProvenanceRecord]]:
    """Select observations relevant to the work item."""
    token_sources = _work_item_token_sources(work_item)
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

    itemized_limit = _MAX_CONTEXT_ITEMS + _MAX_REJECTED_PROVENANCE_ITEMS
    itemized = scored[:itemized_limit]
    unlisted_scored = [(score, item.subject) for score, item in scored[itemized_limit:]]
    scored_subjects = {item.subject for _, item in scored}
    unscored_ids = sorted(
        observation.subject
        for observation in observations
        if observation.subject not in scored_subjects
    )

    for selection_score, observation in itemized:
        matching_fields = _matching_fields(
            tokens,
            subject=observation.subject,
            evidence=observation.content,
        )
        work_item_fields = _matching_work_item_fields(
            token_sources, observation.subject, observation.content
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
                    work_item_fields=work_item_fields,
                    selection_score=selection_score,
                ),
                source=ResolutionSource.PROJECT_FACT,
                project_fact=(
                    f"matching_fields={matching_fields or ['none']}; "
                    f"work_item_fields={work_item_fields or ['none']}; "
                    f"selection_score={selection_score:.2f}"
                ),
                evidence_refs=[observation.provenance.source_ref or observation.subject],
            )
        )

    summary = _rejected_summary_record(
        component_kind="observation",
        unscored_ids=unscored_ids,
        unlisted_scored=unlisted_scored,
    )
    if summary is not None:
        provenance.append(summary)
    return selected, provenance
