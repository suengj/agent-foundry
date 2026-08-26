"""Mechanical audit of the *parameter* surface of every public verify entry point.

`test_verify_vocabulary_sweep.py` forges vocabulary positions carried on the
artifact. This file forges the other entry point: values that arrive as *arguments*.

That distinction is why one instance survived three rounds of review. The policy —
validate vocabulary membership before any membership test, rank lookup, or
dereference — was applied to artifact fields and not to parameters, so
`validate_lifecycle_separation(receipt, required_evidence_states=["SOMEDAY"])` raised
`AttributeError` instead of returning a verdict. Same rule, different door.

Both surfaces are now enumerated from introspection rather than from a list:

* enum-typed parameters are found by reading each function's type hints;
* model-typed parameters are forged through their own enum fields.

A parameter added to a validator tomorrow is therefore swept the day it is added,
and this audit cannot go stale the way the two hand-written ones did.
"""

from __future__ import annotations

import enum
import inspect
import typing

import pytest

from agent_foundry.models import ValidationOutcome
from agent_foundry.models.base import FoundryModel
import agent_foundry.verify as verify_api

OFF_VOCABULARY = "SOMEDAY"

pytestmark = pytest.mark.filterwarnings("ignore:Pydantic serializer warnings:UserWarning")


def _annotation_kinds(annotation) -> tuple[list[type], bool]:
    """Enum types and whether a model type appears anywhere in an annotation."""
    enums: list[type] = []
    has_model = False
    stack = [annotation]
    while stack:
        item = stack.pop()
        if isinstance(item, type) and issubclass(item, enum.Enum):
            enums.append(item)
        elif isinstance(item, type) and issubclass(item, FoundryModel):
            has_model = True
        stack.extend(typing.get_args(item) or [])
    return enums, has_model


def _public_entry_points() -> list[tuple[str, object]]:
    entries = []
    for name in sorted(verify_api.__all__):
        value = getattr(verify_api, name)
        if callable(value) and not isinstance(value, type):
            entries.append((name, value))
    return entries


def _parameter_kinds(fn) -> dict[str, tuple[list[type], bool]]:
    try:
        signature = inspect.signature(fn)
        hints = typing.get_type_hints(fn)
    except (ValueError, TypeError):  # pragma: no cover - builtins only
        return {}
    kinds: dict[str, tuple[list[type], bool]] = {}
    for name, parameter in signature.parameters.items():
        enums, has_model = _annotation_kinds(hints.get(name, parameter.annotation))
        if enums or has_model:
            kinds[name] = (enums, has_model)
    return kinds


# Every public entry point that takes a vocabulary or model argument, and how to call
# it. `None` marks entry points deliberately not swept here, with the reason.
ENUM_PARAMETER_CASES: list[tuple[str, str, type, object]] = []
_UNSWEPT: dict[str, str] = {}


def _register_cases():
    from agent_foundry.models import EvidenceState
    from agent_foundry.verify import validate_lifecycle_separation
    from verify_support import complete_receipt

    receipt, _ = complete_receipt()
    ENUM_PARAMETER_CASES.append(
        (
            "validate_lifecycle_separation.required_evidence_states",
            "required_evidence_states",
            EvidenceState,
            lambda value: validate_lifecycle_separation(
                receipt, required_evidence_states=value
            ),
        )
    )
    # `build_execution_receipt` takes four enum parameters and is a *producer*, not a
    # validator: it has no ValidationReport to return, so it must fail loudly and
    # typed rather than yield a verdict. Covered by its own test below.
    _UNSWEPT["build_execution_receipt"] = (
        "producer, not validator — raises a typed ValidationError instead of "
        "returning a report; see test_the_receipt_builder_refuses_an_off_vocabulary_state"
    )


_register_cases()


@pytest.mark.parametrize(
    ("case_id", "parameter", "enum_type", "call"),
    ENUM_PARAMETER_CASES,
    ids=[case[0] for case in ENUM_PARAMETER_CASES],
)
@pytest.mark.parametrize("shape", ["sequence", "bare"])
def test_an_off_vocabulary_argument_is_rejected_without_raising(
    case_id, parameter, enum_type, call, shape
):
    """A caller-supplied value naming nothing must be BLOCKED, not raised, not passed."""
    value = [OFF_VOCABULARY] if shape == "sequence" else OFF_VOCABULARY
    try:
        report = call(value)
    except Exception as exc:  # noqa: BLE001 - the point is that nothing escapes
        pytest.fail(
            f"{case_id} ({shape}): raised {type(exc).__name__}: {exc}. An exception is "
            "not a fail-closed verdict — it records nothing about why the argument was "
            "rejected and aborts the caller."
        )
    assert report.findings
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert not report.accepted()
    assert parameter in " | ".join(finding.message for finding in report.findings)


def test_every_enum_typed_parameter_is_either_swept_or_explained():
    """The audit claim is mechanical: nothing may be silently out of scope.

    Reads the type hints of every public entry point. An enum-typed parameter must
    either have a sweep case above or a recorded reason in `_UNSWEPT`. This is what
    replaces a third hand-written "I checked everything" claim.
    """
    swept = {case_id.rsplit(".", 1)[0] + "." + parameter for case_id, parameter, _e, _c in ENUM_PARAMETER_CASES}
    missing: list[str] = []
    for name, fn in _public_entry_points():
        if name in _UNSWEPT:
            continue
        for parameter, (enums, _has_model) in _parameter_kinds(fn).items():
            if not enums:
                continue
            if f"{name}.{parameter}" not in swept:
                missing.append(f"{name}.{parameter}")
    assert missing == [], (
        f"enum-typed parameter(s) {missing} are neither swept nor explained; add a "
        "case above or record why the entry point is out of scope"
    )


VALIDATOR_SOURCES = ("validators.py", "explain.py")


def _gate_region(source: str, function_name: str) -> str:
    """The text of a validator's vocabulary gate, and nothing else.

    Deliberately excludes the signature. An earlier version of this test sliced from
    `def name(` and so found the parameter in its own annotation — it would have
    passed with the parameter removed from the gate, which is exactly the mutation it
    exists to catch.
    """
    start = source.index(f"def {function_name}(")
    body_end = source.find("\ndef ", start + 1)
    body = source[start : body_end if body_end != -1 else len(source)]
    for opener in ("malformed_vocabulary_report(", "vocabulary_findings("):
        if opener in body:
            gate_start = body.index(opener)
            closer = body.find("if malformed", gate_start)
            return body[gate_start : closer if closer != -1 else len(body)]
    return ""


def _validator_source(name: str) -> str | None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "agent_foundry" / "verify"
    for filename in VALIDATOR_SOURCES:
        source = (root / filename).read_text(encoding="utf-8")
        if f"def {name}(" in source:
            return source
    return None


def test_every_model_typed_parameter_reaches_a_vocabulary_scan():
    """Every model argument a validator takes must pass through its own gate.

    Derived from signatures, not from a list, so a validator added tomorrow with an
    unscanned model parameter fails here. `registry` and the `artifacts` mapping were
    both missed the first time: they are read but not obviously "examined", and
    neither appeared in the artifact sweep's probe table.
    """
    missing: list[str] = []
    for name, fn in _public_entry_points():
        if not name.startswith("validate_"):
            continue
        source = _validator_source(name)
        if source is None:  # pragma: no cover - every validator lives in verify/
            missing.append(f"{name}: source not found")
            continue
        gate = _gate_region(source, name)
        assert gate, f"{name} has no vocabulary gate at all"
        for parameter, (_enums, has_model) in _parameter_kinds(fn).items():
            if not has_model:
                continue
            if parameter not in gate:
                missing.append(f"{name}.{parameter}")
    assert missing == [], (
        f"model argument(s) {missing} never reach their validator's vocabulary gate; "
        "an argument a validator reads must be scanned like the artifact itself"
    )


def test_the_receipt_builder_refuses_an_off_vocabulary_state():
    """The producer's contract differs from a validator's, and that is deliberate.

    `build_execution_receipt` constructs an artifact; it has no report to return. The
    right failure is a loud typed one at construction, which is what pydantic gives —
    not a silently mis-built receipt.
    """
    from datetime import datetime, timezone

    from pydantic import ValidationError

    from agent_foundry.models import EvidenceState, ExecutionState, WorkLifecycleState
    from agent_foundry.verify import build_execution_receipt
    from verify_support import compiled

    artifacts = compiled()
    base = dict(
        bundle=artifacts["bundle"],
        started_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        work_lifecycle_state=WorkLifecycleState.IN_REVIEW,
        execution_state=ExecutionState.STOPPED,
        attained_evidence_states=[EvidenceState.VALIDATED],
        not_required_evidence_states=[],
    )
    for field in (
        "work_lifecycle_state",
        "execution_state",
        "attained_evidence_states",
        "not_required_evidence_states",
    ):
        kwargs = dict(base)
        kwargs[field] = [OFF_VOCABULARY] if field.endswith("states") else OFF_VOCABULARY
        with pytest.raises(ValidationError):
            build_execution_receipt(**kwargs)


def test_the_shared_parameter_helper_accepts_both_shapes():
    """A caller may hand a bare value or a sequence; both are checked."""
    from agent_foundry.models import EvidenceState
    from agent_foundry.verify.independent import enum_value_violations

    assert enum_value_violations(None, EvidenceState, label="x") == []
    assert enum_value_violations([], EvidenceState, label="x") == []
    assert enum_value_violations(
        [EvidenceState.VALIDATED], EvidenceState, label="x"
    ) == []
    assert enum_value_violations(["VALIDATED"], EvidenceState, label="x") == []
    assert enum_value_violations(OFF_VOCABULARY, EvidenceState, label="x")
    assert enum_value_violations([OFF_VOCABULARY], EvidenceState, label="x")


# --- behavioral cover for the model-typed parameters that were being missed -------
#
# `registry` and the `artifacts` mapping are read by their validators but never
# "examined" in the way the artifact under review is, which is why neither appeared in
# the artifact sweep's probe table and both went unchecked. Each gets a named test, so
# removing the scan fails something specific rather than only a structural assertion.


def _forge_registry(registry):
    capabilities = [
        type(item).model_construct(**{**item.__dict__, "min_external_effect": OFF_VOCABULARY})
        for item in registry.capabilities
    ]
    return type(registry).model_construct(**{**registry.__dict__, "capabilities": capabilities})


def test_authority_ceiling_blocks_a_registry_carrying_an_off_vocabulary_effect():
    from agent_foundry.verify import validate_authority_ceiling
    from verify_support import compiled

    artifacts = compiled()
    report = validate_authority_ceiling(
        artifacts["bundle"].authority,
        work_item=artifacts["work_item"],
        manifest=artifacts["manifest"],
        task_toolkit=artifacts["task_toolkit"],
        role=artifacts["role"],
        permission_profile=artifacts["permission_profile"],
        registry=_forge_registry(artifacts["registry"]),
    )
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "registry." in " | ".join(finding.message for finding in report.findings)


def test_toolkit_coherence_blocks_a_registry_carrying_an_off_vocabulary_effect():
    from agent_foundry.verify import validate_toolkit_coherence
    from verify_support import compiled

    artifacts = compiled()
    report = validate_toolkit_coherence(
        artifacts["task_toolkit"], artifacts["lock"], _forge_registry(artifacts["registry"])
    )
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "registry." in " | ".join(finding.message for finding in report.findings)


def test_receipt_completeness_blocks_a_comparison_artifact_with_a_bad_vocabulary():
    """Without this, a malformed comparison artifact reports a digest mismatch.

    Fail-closed by accident is not the same as fail-closed: the finding would say the
    receipt names the wrong artifact, when what is actually wrong is the artifact it
    was handed.
    """
    from agent_foundry.verify import validate_receipt_completeness
    from verify_support import compiled, complete_receipt

    artifacts = compiled()
    receipt, _ = complete_receipt()
    bundle = artifacts["bundle"]
    forged = type(bundle).model_construct(
        **{
            **bundle.__dict__,
            "authority": type(bundle.authority).model_construct(
                **{**bundle.authority.__dict__, "external_effect": OFF_VOCABULARY}
            ),
        }
    )
    report = validate_receipt_completeness(receipt, artifacts={"execution-bundle": forged})
    assert report.outcome() == ValidationOutcome.BLOCKED
    messages = " | ".join(finding.message for finding in report.findings)
    assert "artifacts[execution-bundle]." in messages
    assert "digests to" not in messages


# --- loosely typed parameters: not a vocabulary, but the same "must not raise" rule --


@pytest.mark.parametrize(
    ("label", "call"),
    [
        (
            "contract-schema-compatibility/contracts",
            lambda value: __import__(
                "agent_foundry.verify", fromlist=["validate_contract_schema_compatibility"]
            ).validate_contract_schema_compatibility([("x", value)]),
        ),
        (
            "provenance-completeness/subject",
            lambda value: __import__(
                "agent_foundry.verify", fromlist=["validate_provenance_completeness"]
            ).validate_provenance_completeness(value),
        ),
    ],
)
def test_a_parameter_that_is_not_a_contract_is_blocked_not_raised(label, call):
    """`Iterable[tuple[str, Any]]` and a bare model annotation both admit non-models.

    Reading one raises `AttributeError`, which returns no report and tells the caller
    nothing. These two entry points now say what is wrong instead.
    """
    report = call(object())
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "is not a contract payload" in " | ".join(
        finding.message for finding in report.findings
    )


def test_a_mapping_payload_is_still_accepted():
    """The guard must not narrow what these entry points legitimately take."""
    from agent_foundry.verify import validate_contract_schema_compatibility

    report = validate_contract_schema_compatibility([("x", {"schema_version": "0.1"})])
    assert report.accepted()
