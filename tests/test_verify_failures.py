"""Repeated-failure classification.

The honesty requirement drives every case here: a signal that does not structurally
support a category returns `UNKNOWN`, and so does a signal that supports two equally.
Narration is never classified.
"""

from __future__ import annotations

import pytest

from agent_foundry.models import FailureCategory, FailureSignal
from agent_foundry.verify import classify_failure, classify_repeated_failures
from agent_foundry.verify.failures import REPEAT_SUSPICION_THRESHOLD


def _signal(attempt: int = 1, run_id: str = "RUN-1", **fields: object) -> FailureSignal:
    return FailureSignal(run_id=run_id, attempt=attempt, **fields)


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"denied_capabilities": ["repository.write"]}, FailureCategory.PERMISSION),
        ({"missing_context_refs": ["docs/contracts/x.md"]}, FailureCategory.CONTEXT),
        ({"violated_contract_ids": ["WI-1#acceptance-2"]}, FailureCategory.CONTRACT),
        ({"failing_tool_ids": ["repository-edit"]}, FailureCategory.TOOL),
        ({"harness_markers": ["stale-bytecode"]}, FailureCategory.HARNESS),
    ],
)
def test_each_category_is_recognised_from_its_own_structured_field(fields, expected):
    classification = classify_failure(_signal(**fields))
    assert classification.category == expected
    assert classification.supporting_fields


def test_a_free_text_message_alone_is_not_classified():
    classification = classify_failure(
        _signal(message="the tool seemed to be missing permissions, probably")
    )
    assert classification.category == FailureCategory.UNKNOWN
    assert classification.supporting_fields == []
    assert "not classified" in classification.rationale


def test_equally_supported_categories_return_unknown_with_both_candidates():
    classification = classify_failure(
        _signal(denied_capabilities=["repository.write"], failing_tool_ids=["repository-edit"])
    )
    assert classification.category == FailureCategory.UNKNOWN
    assert set(classification.candidate_categories) == {
        FailureCategory.PERMISSION,
        FailureCategory.TOOL,
    }
    assert "does not discriminate" in classification.rationale


def test_the_strongest_evidence_wins_when_it_is_unambiguous():
    classification = classify_failure(
        _signal(
            denied_capabilities=["repository.write", "work.write"],
            failing_tool_ids=["repository-edit"],
        )
    )
    assert classification.category == FailureCategory.PERMISSION
    assert FailureCategory.TOOL in classification.candidate_categories


def test_two_failures_in_one_class_shift_suspicion_to_the_harness_or_contract():
    signals = [
        _signal(attempt=1, run_id="RUN-1", harness_markers=["stale-bytecode"]),
        _signal(attempt=2, run_id="RUN-2", harness_markers=["stale-bytecode"]),
    ]
    assessment = classify_repeated_failures(signals)
    assert assessment.category == FailureCategory.HARNESS
    assert assessment.occurrences >= REPEAT_SUSPICION_THRESHOLD
    assert assessment.suspect_harness_or_contract is True
    assert assessment.escalate is True


def test_one_failure_is_not_yet_a_structural_cause():
    assessment = classify_repeated_failures(
        [_signal(violated_contract_ids=["WI-1#acceptance-2"])]
    )
    assert assessment.category == FailureCategory.CONTRACT
    assert assessment.occurrences == 1
    assert assessment.suspect_harness_or_contract is False
    assert assessment.escalate is False


def test_repeated_unclassifiable_failures_escalate_without_inventing_a_category():
    assessment = classify_repeated_failures(
        [
            _signal(attempt=1, run_id="RUN-1", message="it did not work"),
            _signal(attempt=2, run_id="RUN-2", message="it still did not work"),
        ]
    )
    assert assessment.category == FailureCategory.UNKNOWN
    assert assessment.escalate is True
    assert "not a repair plan" in assessment.rationale


def test_a_tie_across_attempts_does_not_pick_a_winner():
    assessment = classify_repeated_failures(
        [
            _signal(attempt=1, run_id="RUN-1", denied_capabilities=["repository.write"]),
            _signal(attempt=2, run_id="RUN-2", missing_context_refs=["docs/x.md"]),
        ]
    )
    assert assessment.category == FailureCategory.UNKNOWN
    assert assessment.escalate is True
    assert "equally often" in assessment.rationale


def test_no_signals_classifies_to_unknown_without_escalating():
    assessment = classify_repeated_failures([])
    assert assessment.category == FailureCategory.UNKNOWN
    assert assessment.occurrences == 0
    assert assessment.escalate is False


def test_classification_records_every_attempt_it_considered():
    signals = [
        _signal(attempt=1, run_id="RUN-1", failing_tool_ids=["repository-edit"]),
        _signal(attempt=2, run_id="RUN-2", failing_tool_ids=["repository-edit"]),
        _signal(attempt=3, run_id="RUN-3", message="unclear"),
    ]
    assessment = classify_repeated_failures(signals)
    assert len(assessment.classifications) == 3
    assert assessment.run_ids == ["RUN-1", "RUN-2", "RUN-3"]
    assert assessment.category == FailureCategory.TOOL
