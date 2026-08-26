"""Every sequence parameter is read once, and only a real sequence is accepted.

Round 4 added parameter vocabulary checking and introduced this class of bug with it:
the guard iterated the caller's iterable to check it, then handed the same exhausted
iterator to the real logic. Symptoms differed by entry point and none of them was
obviously a bug —

* `required_evidence_states` → BLOCKED a valid generator (visible false positive);
* `bundles` → TypeError;
* `work_items` → "0 work item(s) form an acyclic graph", a clean PASS over nothing;
* `review_decisions` → the independence finding silently vanished;
* `observed_health` → MISSING, which reads like a legitimate verdict.

The last three are the dangerous ones: a validator that rejects valid input at least
announces itself. So this file checks the *property*, not the symptoms:

1. **A generator must give the same answer as the equivalent list.** One pass, one
   materialized copy, used by the guard and by the logic alike.
2. **A bare string is not a sequence.** `str` is iterable, so passing one where a
   list belongs would be read character by character. Validators return BLOCKED; the
   non-validator entry points, which have no report type, are covered separately.
3. **Nothing raises.** A caller error must still produce a verdict.

The parameter list is derived from signatures, so a sequence parameter added tomorrow
must be registered here or fail `test_every_sequence_parameter_is_covered`.
"""

from __future__ import annotations

import inspect
import typing

import pytest

from agent_foundry.models import (
    ClassificationFinding,
    EvidenceState,
    FailureSignal,
    IntegrationHealthState,
    Provenance,
    ProvenanceKind,
    ValidationOutcome,
    WorkLifecycleState,
)
import agent_foundry.verify as verify_api
from agent_foundry.verify import (
    assess_inferred_fact_tightening,
    build_decision_trace,
    classify_repeated_failures,
    validate_contract_schema_compatibility,
    validate_decision_explainability,
    validate_integration_preflight,
    validate_lifecycle_separation,
    validate_role_separation,
    validate_work_dependency_graph,
)
from verify_support import (
    approving_review,
    compiled,
    complete_receipt,
    health,
    integration_spec,
)

pytestmark = pytest.mark.filterwarnings("ignore:Pydantic serializer warnings:UserWarning")

_ARTIFACTS = compiled()
_RECEIPT, _ = complete_receipt()

# A receipt whose lifecycle claims closure. The required-states parameter is only
# *read* on the terminal-lifecycle path, so a case built on an in-review receipt
# exercises nothing: the first version of this file had exactly that vacuous case, and
# the mutation that reverted the normalization failed no test at all.
_CLOSED_RECEIPT, _ = complete_receipt(lifecycle=WorkLifecycleState.DONE)
_SPEC = integration_spec()
_HEALTH = health("work-tracker", IntegrationHealthState.AUTHORIZED)
_CLASSIFICATION = [
    ClassificationFinding(
        dimension="impact.external_effect",
        value="repository-write",
        provenance=Provenance(kind=ProvenanceKind.DECLARED, source_ref="intake.yaml"),
    )
]
_SIGNALS = [
    FailureSignal(run_id="RUN-1", attempt=1, harness_markers=["stale-bytecode"]),
    FailureSignal(run_id="RUN-2", attempt=2, harness_markers=["stale-bytecode"]),
]


def _report_shape(report) -> object:
    """A comparable summary of a validation result."""
    return (
        report.outcome().value,
        tuple(sorted(finding.message for finding in report.findings)),
    )


# (case id, is_validator, good value, call, comparable)
SEQUENCE_CASES: list[tuple[str, bool, list, object, object]] = [
    (
        "validate_lifecycle_separation.required_evidence_states",
        True,
        # MERGED_INTEGRATED is neither attained nor exempt on this receipt, so a
        # lifecycle claiming closure must be BLOCKED. Read the parameter twice and it
        # arrives empty, nothing is unmet, and the same receipt reports PASS.
        [EvidenceState.MERGED_INTEGRATED],
        lambda v: validate_lifecycle_separation(
            _CLOSED_RECEIPT, required_evidence_states=v
        ),
        _report_shape,
    ),
    (
        "validate_work_dependency_graph.work_items",
        True,
        [_ARTIFACTS["work_item"]],
        lambda v: validate_work_dependency_graph(v),
        _report_shape,
    ),
    (
        "validate_role_separation.bundles",
        True,
        [_ARTIFACTS["bundle"]],
        lambda v: validate_role_separation(v),
        _report_shape,
    ),
    (
        "validate_role_separation.review_decisions",
        True,
        [approving_review().model_copy(update={"implementing_role_id": None})],
        lambda v: validate_role_separation([_ARTIFACTS["bundle"]], review_decisions=v),
        _report_shape,
    ),
    (
        "validate_role_separation.review_only_role_ids",
        True,
        ["reviewer"],
        lambda v: validate_role_separation(
            [_ARTIFACTS["bundle"]], review_only_role_ids=v
        ),
        _report_shape,
    ),
    (
        "validate_integration_preflight.integrations",
        True,
        [_SPEC],
        lambda v: validate_integration_preflight(
            v, required_ids=["work-tracker"], observed_health=[_HEALTH]
        ),
        _report_shape,
    ),
    (
        "validate_integration_preflight.observed_health",
        True,
        [_HEALTH],
        lambda v: validate_integration_preflight(
            [_SPEC], required_ids=["work-tracker"], observed_health=v
        ),
        _report_shape,
    ),
    (
        "validate_integration_preflight.required_ids",
        True,
        ["work-tracker"],
        lambda v: validate_integration_preflight(
            [_SPEC], required_ids=v, observed_health=[_HEALTH]
        ),
        _report_shape,
    ),
    (
        "validate_contract_schema_compatibility.contracts",
        True,
        [("work-item", _ARTIFACTS["work_item"])],
        lambda v: validate_contract_schema_compatibility(v),
        _report_shape,
    ),
    (
        "validate_decision_explainability.classification_findings",
        True,
        _CLASSIFICATION,
        lambda v: validate_decision_explainability(
            _ARTIFACTS["bundle"],
            manifest=_ARTIFACTS["manifest"],
            receipt=_RECEIPT,
            classification_findings=v,
        ),
        _report_shape,
    ),
    (
        "assess_inferred_fact_tightening.classification_findings",
        False,
        _CLASSIFICATION,
        lambda v: assess_inferred_fact_tightening(_ARTIFACTS["manifest"], v),
        lambda r: tuple((item.axis, item.declared_only, item.widened) for item in r),
    ),
    (
        "build_decision_trace.classification_findings",
        False,
        _CLASSIFICATION,
        lambda v: build_decision_trace(
            _ARTIFACTS["bundle"], manifest=_ARTIFACTS["manifest"], classification_findings=v
        ),
        lambda r: (len(r.classification_provenance), len(r.authority_tightening)),
    ),
    (
        "classify_repeated_failures.signals",
        False,
        _SIGNALS,
        lambda v: classify_repeated_failures(v),
        lambda r: (r.category.value, r.occurrences, tuple(r.run_ids)),
    ),
]

CASE_IDS = [case[0] for case in SEQUENCE_CASES]

# Producers have no ValidationReport to return. Where the return type can express an
# honest "unknown", it does; where it cannot, the producer raises rather than treating
# a malformed argument as an empty sequence.
PRODUCERS_RAISE = frozenset(
    {
        "assess_inferred_fact_tightening.classification_findings",
        "build_decision_trace.classification_findings",
    }
)
PRODUCER_RETURNS_UNKNOWN = frozenset({"classify_repeated_failures.signals"})


@pytest.mark.parametrize(
    ("case_id", "is_validator", "good", "call", "comparable"),
    SEQUENCE_CASES,
    ids=CASE_IDS,
)
def test_a_generator_gives_the_same_answer_as_the_equivalent_list(
    case_id, is_validator, good, call, comparable
):
    """The false-positive direction: valid input must not be rejected or emptied."""
    from_list = comparable(call(list(good)))
    from_generator = comparable(call(item for item in good))
    assert from_generator == from_list, (
        f"{case_id}: a generator produced {from_generator!r} but the equivalent list "
        f"produced {from_list!r}. The caller's iterable is being read twice — the "
        "guard consumes it and the logic sees an exhausted iterator."
    )


@pytest.mark.parametrize(
    ("case_id", "is_validator", "good", "call", "comparable"),
    SEQUENCE_CASES,
    ids=CASE_IDS,
)
def test_a_bare_string_is_rejected_rather_than_read_character_by_character(
    case_id, is_validator, good, call, comparable
):
    if case_id in PRODUCERS_RAISE:
        # A producer has no report in which to record a caller error, and silently
        # treating a bare string as empty is the worse answer: "no findings" is
        # exactly what makes an inference look like authority widening. So it fails
        # loudly and typed, the same contract `build_execution_receipt` has.
        with pytest.raises(ValueError, match="not a sequence of values"):
            call("VALIDATED")
        return

    try:
        result = call("VALIDATED")
    except Exception as exc:  # noqa: BLE001 - the point is that nothing escapes
        pytest.fail(f"{case_id}: raised {type(exc).__name__}: {exc}")

    assert is_validator or case_id in PRODUCER_RETURNS_UNKNOWN, (
        f"{case_id}: a producer with no report type should have raised; see "
        "PRODUCERS_RAISE"
    )
    if is_validator:
        assert result.outcome() == ValidationOutcome.BLOCKED, case_id
        assert "not a sequence of values" in " | ".join(
            finding.message for finding in result.findings
        ), case_id
    else:
        # `classify_repeated_failures` returns a type that can express "unknown", so
        # it says so rather than raising.
        assert comparable(result)[0] == "unknown", case_id


@pytest.mark.parametrize(
    ("case_id", "is_validator", "good", "call", "comparable"),
    SEQUENCE_CASES,
    ids=CASE_IDS,
)
def test_a_valid_sequence_is_still_accepted(case_id, is_validator, good, call, comparable):
    """Guard against fixing the false positive by rejecting everything."""
    result = call(list(good))
    if is_validator:
        assert result.findings
        messages = " | ".join(finding.message for finding in result.findings)
        # A valid sequence may still yield findings about the artifact; what it must
        # never yield is a complaint about the parameter's shape or vocabulary.
        assert "not a sequence of values" not in messages, case_id
        assert "names no EvidenceState value" not in messages, case_id
        assert "is not iterable" not in messages, case_id
    else:
        assert result is not None


# --- the parameter list cannot go stale ------------------------------------------

# Parameters that take a sequence but are deliberately not registered above, each with
# the reason. `build_execution_receipt` is a producer: it materializes its inputs and
# fails with a typed ValidationError, which is a builder's contract, not a validator's.
UNREGISTERED: dict[str, str] = {
    "build_execution_receipt.attained_evidence_states": "producer; materialized then typed-validated by pydantic",
    "build_execution_receipt.not_required_evidence_states": "producer; same",
    "build_execution_receipt.findings": "producer; same",
    "build_execution_receipt.limitations": "producer; same",
    "classify_repeated_failures.signals": "registered above",
}


def _sequence_parameters() -> list[str]:
    """Every public entry point parameter annotated as a list/sequence/iterable."""
    found: list[str] = []
    for name in sorted(verify_api.__all__):
        fn = getattr(verify_api, name)
        if not callable(fn) or isinstance(fn, type):
            continue
        try:
            signature = inspect.signature(fn)
            hints = typing.get_type_hints(fn)
        except (ValueError, TypeError):  # pragma: no cover
            continue
        for parameter in signature.parameters:
            annotation = hints.get(parameter, signature.parameters[parameter].annotation)
            origin_names = {
                getattr(part, "__name__", "")
                for part in (annotation, typing.get_origin(annotation))
            }
            text = str(annotation)
            if any(
                marker in text
                for marker in ("list[", "Sequence[", "Iterable[", "frozenset[", "set[")
            ) or origin_names & {"list", "frozenset", "set"}:
                found.append(f"{name}.{parameter}")
    return found


def test_every_sequence_parameter_is_covered():
    """A sequence parameter added tomorrow must be registered or explained here."""
    registered = set(CASE_IDS) | set(UNREGISTERED)
    missing = sorted(set(_sequence_parameters()) - registered)
    assert missing == [], (
        f"sequence parameter(s) {missing} are neither covered by a shape case nor "
        "recorded in UNREGISTERED with a reason"
    )


def test_the_sweep_covers_the_parameters_that_actually_broke():
    for case_id in (
        "validate_lifecycle_separation.required_evidence_states",
        "validate_work_dependency_graph.work_items",
        "validate_role_separation.bundles",
        "validate_role_separation.review_decisions",
        "validate_integration_preflight.integrations",
        "validate_integration_preflight.observed_health",
        "build_decision_trace.classification_findings",
        "classify_repeated_failures.signals",
    ):
        assert case_id in CASE_IDS, case_id


def test_the_receipt_builder_materializes_its_sequences():
    """The producer path reads each list once too, even without a report to return."""
    from datetime import datetime, timezone

    from agent_foundry.models import ExecutionState, WorkLifecycleState
    from agent_foundry.verify import build_execution_receipt

    receipt = build_execution_receipt(
        bundle=_ARTIFACTS["bundle"],
        started_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        work_lifecycle_state=WorkLifecycleState.IN_REVIEW,
        execution_state=ExecutionState.STOPPED,
        attained_evidence_states=(s for s in [EvidenceState.IMPLEMENTED, EvidenceState.VALIDATED]),
        not_required_evidence_states=(s for s in [EvidenceState.USER_ACCEPTED]),
    )
    assert receipt.attained_evidence_states == [
        EvidenceState.IMPLEMENTED,
        EvidenceState.VALIDATED,
    ]
    assert receipt.not_required_evidence_states == [EvidenceState.USER_ACCEPTED]
    assert receipt.evidence_state == EvidenceState.VALIDATED
