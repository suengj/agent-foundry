"""Repeated-failure classification (docs/foundry/06 §10).

Classification reads structured fields only. The free-text `message` on a
`FailureSignal` is never consulted: a model's account of why it failed is exactly
the kind of self-report that must not decide whether to retry. When the structure
supports nothing, the answer is `UNKNOWN`, and when it supports two categories
equally the answer is also `UNKNOWN` — with both candidates recorded, so a human
sees the ambiguity rather than a coin toss.
"""

from __future__ import annotations

from collections import Counter

from agent_foundry.models.common import FailureCategory
from agent_foundry.models.verification import (
    FailureClassification,
    FailureSignal,
    RepeatedFailureAssessment,
)

# Each category is evidenced by exactly one structured field. Keeping the mapping
# one-to-one is what makes "the signal does not support a category" a decidable
# question rather than a judgement call.
_CATEGORY_FIELDS: tuple[tuple[FailureCategory, str], ...] = (
    (FailureCategory.PERMISSION, "denied_capabilities"),
    (FailureCategory.CONTEXT, "missing_context_refs"),
    (FailureCategory.CONTRACT, "violated_contract_ids"),
    (FailureCategory.TOOL, "failing_tool_ids"),
    (FailureCategory.HARNESS, "harness_markers"),
)

REPEAT_SUSPICION_THRESHOLD = 2
"""Two failures in one class stop being bad luck.

docs/foundry/06 §10: at that point suspicion shifts to the harness or the contract
rather than to the model, and unlimited retries are the wrong response.
"""


def classify_failure(signal: FailureSignal) -> FailureClassification:
    """Classify one failed attempt from its structured evidence alone."""
    supported: list[tuple[FailureCategory, str, int]] = []
    for category, field in _CATEGORY_FIELDS:
        values = getattr(signal, field)
        if values:
            supported.append((category, field, len(values)))

    if not supported:
        return FailureClassification(
            run_id=signal.run_id,
            attempt=signal.attempt,
            category=FailureCategory.UNKNOWN,
            supporting_fields=[],
            candidate_categories=[],
            rationale=(
                "no structured field evidences a category; a free-text failure "
                "message is not classified"
            ),
        )

    strongest = max(count for _, _, count in supported)
    leaders = sorted(
        (category for category, _, count in supported if count == strongest),
        key=lambda item: item.value,
    )
    fields = sorted(field for _, field, _ in supported)

    if len(leaders) > 1:
        return FailureClassification(
            run_id=signal.run_id,
            attempt=signal.attempt,
            category=FailureCategory.UNKNOWN,
            supporting_fields=fields,
            candidate_categories=leaders,
            rationale=(
                "structured evidence supports "
                + ", ".join(category.value for category in leaders)
                + " equally; the signal does not discriminate between them"
            ),
        )

    chosen = leaders[0]
    others = sorted(
        (category for category, _, _ in supported if category != chosen),
        key=lambda item: item.value,
    )
    return FailureClassification(
        run_id=signal.run_id,
        attempt=signal.attempt,
        category=chosen,
        supporting_fields=fields,
        candidate_categories=[chosen, *others],
        rationale=(
            f"{chosen.value} is evidenced by the most specific structured field "
            f"({dict((c, f) for c, f in _CATEGORY_FIELDS)[chosen]})"
        ),
    )


def classify_repeated_failures(signals: list[FailureSignal]) -> RepeatedFailureAssessment:
    """Assess a run of failures for a dominant, repeating class."""
    classifications = [classify_failure(signal) for signal in signals]
    run_ids = sorted({signal.run_id for signal in signals})

    if not classifications:
        return RepeatedFailureAssessment(
            category=FailureCategory.UNKNOWN,
            occurrences=0,
            run_ids=[],
            classifications=[],
            suspect_harness_or_contract=False,
            escalate=False,
            rationale="no failure signals supplied",
        )

    known = [
        item.category for item in classifications if item.category != FailureCategory.UNKNOWN
    ]
    if not known:
        return RepeatedFailureAssessment(
            category=FailureCategory.UNKNOWN,
            occurrences=len(classifications),
            run_ids=run_ids,
            classifications=classifications,
            suspect_harness_or_contract=False,
            escalate=len(classifications) >= REPEAT_SUSPICION_THRESHOLD,
            rationale=(
                f"{len(classifications)} attempt(s) failed without structured evidence "
                "of a category; repeating an unclassified failure is not a repair plan"
            ),
        )

    counts = Counter(known)
    top = max(counts.values())
    leaders = sorted((category for category, count in counts.items() if count == top),
                     key=lambda item: item.value)
    if len(leaders) > 1:
        return RepeatedFailureAssessment(
            category=FailureCategory.UNKNOWN,
            occurrences=len(classifications),
            run_ids=run_ids,
            classifications=classifications,
            suspect_harness_or_contract=False,
            escalate=True,
            rationale=(
                "attempts failed in "
                + ", ".join(category.value for category in leaders)
                + " equally often; no single class dominates"
            ),
        )

    dominant = leaders[0]
    repeated = top >= REPEAT_SUSPICION_THRESHOLD
    return RepeatedFailureAssessment(
        category=dominant,
        occurrences=top,
        run_ids=run_ids,
        classifications=classifications,
        suspect_harness_or_contract=repeated,
        escalate=repeated,
        rationale=(
            f"{top} attempt(s) failed in class {dominant.value}"
            + (
                "; two or more in one class shifts suspicion to the harness or the "
                "work contract rather than the implementation"
                if repeated
                else "; a single occurrence does not yet indicate a structural cause"
            )
        ),
    )
