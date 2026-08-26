"""Mechanical audit: every enum position on every validator input, forged.

Round 2 of review carried a hand-written claim to have audited all vocabulary and
ladder checks in `verify/`. It had not: a manual sweep found the list asymmetries and
missed three lifecycle vocabulary fields and the integration-health ladder. An
inaccurate audit claim is worse than a narrow one, so the claim is replaced by this.

For every validator, for every model argument it takes, for every field typed with an
enum, the field is forged with a value from no vocabulary and the validator is called.
Two properties must hold, and they are the two failure modes the review found:

* **it must not raise** — an exception is not a fail-closed verdict. It returns no
  report, so the caller learns nothing about why the artifact was rejected, and
  reconciliation is aborted rather than recorded;
* **it must not accept** — a `PASS` for an artifact carrying a state nobody
  recognises is unsafe acceptance of a malformed positive claim.

The enumeration is derived from `model_fields` annotations, so a field added to a
contract tomorrow is swept the day it is added. Nothing here is a hand-maintained
list of known-bad cases.
"""

from __future__ import annotations

import enum
import typing

import pytest

from agent_foundry.models import IntegrationHealthState, ValidationOutcome
from agent_foundry.verify import (
    reconcile_work_item,
    validate_authority_ceiling,
    validate_contract_schema_compatibility,
    validate_decision_explainability,
    validate_evidence_bundle_completeness,
    validate_execution_bundle_completeness,
    validate_integration_preflight,
    validate_lifecycle_separation,
    validate_provenance_completeness,
    validate_receipt_completeness,
    validate_required_evidence,
    validate_role_separation,
    validate_toolkit_coherence,
    validate_work_dependency_graph,
    validate_write_scope_containment,
)
from verify_support import (
    approving_review,
    compiled,
    complete_receipt,
    full_evidence_bundle,
    health,
    integration_spec,
    repository,
    runtime,
    tracker,
)

# A value that is a plausible-looking string and a member of nothing.
OFF_VOCABULARY = "SOMEDAY"

pytestmark = pytest.mark.filterwarnings("ignore:Pydantic serializer warnings:UserWarning")

_ARTIFACTS = compiled()
_RECEIPT, _ = complete_receipt()


def _is_model(value) -> bool:
    return getattr(type(value), "model_fields", None) is not None


def _enum_positions(model, prefix: str = "", depth: int = 0) -> list[tuple[str, bool]]:
    """Every enum-typed position reachable from this model, as a dotted path.

    Recurses into nested models and into the first element of a list of models, so
    `bundle.authority.external_effect` and `bundle.provenance[0].source` are swept
    too — the compiled artifacts carry most of their vocabulary below the top level,
    and a top-level-only sweep would have missed all of it.
    """
    if depth > 3:
        return []
    positions: list[tuple[str, bool]] = []
    for name, field in type(model).model_fields.items():
        value = getattr(model, name, None)
        if value is None:
            continue
        where = f"{prefix}.{name}" if prefix else name

        stack, mentions_enum = [field.annotation], False
        while stack:
            annotation = stack.pop()
            if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
                mentions_enum = True
            stack.extend(typing.get_args(annotation) or [])
        if mentions_enum:
            positions.append((where, isinstance(value, list)))
            continue

        if _is_model(value):
            positions.extend(_enum_positions(value, where, depth + 1))
        elif isinstance(value, list) and value and _is_model(value[0]):
            positions.extend(_enum_positions(value[0], f"{where}[0]", depth + 1))
    return positions


def _rebuild(model, name: str, replacement):
    return type(model).model_construct(**{**model.__dict__, name: replacement})


def _forge(model, path: str, is_list: bool):
    """Bypass validation the way a payload from a file or another process does."""
    head, _, rest = path.partition(".")
    index = None
    if head.endswith("]"):
        head, _, raw_index = head[:-1].partition("[")
        index = int(raw_index)

    if not rest:
        return _rebuild(model, head, [OFF_VOCABULARY] if is_list else OFF_VOCABULARY)

    inner = getattr(model, head)
    if index is None:
        return _rebuild(model, head, _forge(inner, rest, is_list))
    forged_items = list(inner)
    forged_items[index] = _forge(inner[index], rest, is_list)
    return _rebuild(model, head, forged_items)


# Each entry: a label, the model argument to forge, and how the validator is called
# with that argument substituted. Every validator appears at least once per model
# argument that carries an enum-typed field.
PROBES = [
    ("lifecycle-separation/receipt", _RECEIPT, lambda m: validate_lifecycle_separation(m)),
    ("receipt-completeness/receipt", _RECEIPT, lambda m: validate_receipt_completeness(m)),
    (
        "evidence-bundle-completeness/bundle",
        full_evidence_bundle(),
        lambda m: validate_evidence_bundle_completeness(m),
    ),
    (
        "required-evidence/bundle",
        full_evidence_bundle(),
        lambda m: validate_required_evidence(_ARTIFACTS["work_item"], m),
    ),
    (
        "required-evidence/work-item",
        _ARTIFACTS["work_item"],
        lambda m: validate_required_evidence(m, full_evidence_bundle()),
    ),
    (
        "execution-bundle-completeness/bundle",
        _ARTIFACTS["bundle"],
        lambda m: validate_execution_bundle_completeness(m),
    ),
    (
        "provenance-completeness/bundle",
        _ARTIFACTS["bundle"],
        lambda m: validate_provenance_completeness(m),
    ),
    (
        "contract-schema-compatibility/work-item",
        _ARTIFACTS["work_item"],
        lambda m: validate_contract_schema_compatibility([("work-item", m)]),
    ),
    (
        "work-dependency-graph/work-item",
        _ARTIFACTS["work_item"],
        lambda m: validate_work_dependency_graph([m]),
    ),
    (
        "write-scope-containment/authority",
        _ARTIFACTS["bundle"].authority,
        lambda m: validate_write_scope_containment(
            m, work_item=_ARTIFACTS["work_item"], role=_ARTIFACTS["role"]
        ),
    ),
    (
        "write-scope-containment/work-item",
        _ARTIFACTS["work_item"],
        lambda m: validate_write_scope_containment(
            _ARTIFACTS["bundle"].authority, work_item=m, role=_ARTIFACTS["role"]
        ),
    ),
    (
        "authority-ceiling/authority",
        _ARTIFACTS["bundle"].authority,
        lambda m: validate_authority_ceiling(
            m,
            work_item=_ARTIFACTS["work_item"],
            manifest=_ARTIFACTS["manifest"],
            task_toolkit=_ARTIFACTS["task_toolkit"],
            role=_ARTIFACTS["role"],
            permission_profile=_ARTIFACTS["permission_profile"],
            registry=_ARTIFACTS["registry"],
        ),
    ),
    (
        "authority-ceiling/work-item",
        _ARTIFACTS["work_item"],
        lambda m: validate_authority_ceiling(
            _ARTIFACTS["bundle"].authority,
            work_item=m,
            manifest=_ARTIFACTS["manifest"],
            task_toolkit=_ARTIFACTS["task_toolkit"],
            role=_ARTIFACTS["role"],
            permission_profile=_ARTIFACTS["permission_profile"],
            registry=_ARTIFACTS["registry"],
        ),
    ),
    (
        "authority-ceiling/permission-profile",
        _ARTIFACTS["permission_profile"],
        lambda m: validate_authority_ceiling(
            _ARTIFACTS["bundle"].authority,
            work_item=_ARTIFACTS["work_item"],
            manifest=_ARTIFACTS["manifest"],
            task_toolkit=_ARTIFACTS["task_toolkit"],
            role=_ARTIFACTS["role"],
            permission_profile=m,
            registry=_ARTIFACTS["registry"],
        ),
    ),
    (
        "authority-ceiling/manifest",
        _ARTIFACTS["manifest"],
        lambda m: validate_authority_ceiling(
            _ARTIFACTS["bundle"].authority,
            work_item=_ARTIFACTS["work_item"],
            manifest=m,
            task_toolkit=_ARTIFACTS["task_toolkit"],
            role=_ARTIFACTS["role"],
            permission_profile=_ARTIFACTS["permission_profile"],
            registry=_ARTIFACTS["registry"],
        ),
    ),
    ("role-separation/bundle", _ARTIFACTS["bundle"], lambda m: validate_role_separation([m])),
    (
        "role-separation/review",
        approving_review(),
        lambda m: validate_role_separation([_ARTIFACTS["bundle"]], review_decisions=[m]),
    ),
    (
        "toolkit-coherence/task-toolkit",
        _ARTIFACTS["task_toolkit"],
        lambda m: validate_toolkit_coherence(m, _ARTIFACTS["lock"], _ARTIFACTS["registry"]),
    ),
    (
        "toolkit-coherence/lock",
        _ARTIFACTS["lock"],
        lambda m: validate_toolkit_coherence(
            _ARTIFACTS["task_toolkit"], m, _ARTIFACTS["registry"]
        ),
    ),
    (
        "integration-preflight/health",
        health("work-tracker", IntegrationHealthState.AUTHORIZED),
        lambda m: validate_integration_preflight(
            [integration_spec()], required_ids=["work-tracker"], observed_health=[m]
        ),
    ),
    (
        "integration-preflight/spec",
        integration_spec(),
        lambda m: validate_integration_preflight(
            [m],
            required_ids=["work-tracker"],
            observed_health=[health("work-tracker", IntegrationHealthState.AUTHORIZED)],
        ),
    ),
    (
        "decision-explainability/bundle",
        _ARTIFACTS["bundle"],
        lambda m: validate_decision_explainability(
            m, manifest=_ARTIFACTS["manifest"], receipt=_RECEIPT
        ),
    ),
    (
        "decision-explainability/manifest",
        _ARTIFACTS["manifest"],
        lambda m: validate_decision_explainability(
            _ARTIFACTS["bundle"], manifest=m, receipt=_RECEIPT
        ),
    ),
    (
        "reconcile/tracker",
        tracker(),
        lambda m: reconcile_work_item(
            work_item=_ARTIFACTS["work_item"], tracker=m, repository=repository()
        ),
    ),
    (
        "reconcile/repository",
        repository(),
        lambda m: reconcile_work_item(
            work_item=_ARTIFACTS["work_item"], tracker=tracker(), repository=m
        ),
    ),
    (
        "reconcile/runtime",
        runtime(),
        lambda m: reconcile_work_item(
            work_item=_ARTIFACTS["work_item"],
            tracker=tracker(),
            repository=repository(),
            runtime=m,
        ),
    ),
    (
        "reconcile/work-item",
        _ARTIFACTS["work_item"],
        lambda m: reconcile_work_item(
            work_item=m, tracker=tracker(), repository=repository()
        ),
    ),
]

CASES = [
    (f"{label}.{path}", model, path, is_list, call)
    for label, model, call in PROBES
    for path, is_list in _enum_positions(model)
]


def _accepting(report) -> bool:
    if hasattr(report, "accepted"):
        return report.accepted()
    return all(
        finding.outcome in (ValidationOutcome.PASS, ValidationOutcome.NOT_REQUIRED)
        for finding in report.findings
    )


@pytest.mark.parametrize(
    ("case_id", "model", "path", "is_list", "call"), CASES, ids=[case[0] for case in CASES]
)
def test_an_off_vocabulary_value_is_rejected_without_raising(
    case_id, model, path, is_list, call
):
    forged = _forge(model, path, is_list)
    try:
        report = call(forged)
    except Exception as exc:  # noqa: BLE001 - the point is that nothing escapes
        pytest.fail(
            f"{case_id}: raised {type(exc).__name__}: {exc}. An exception is not a "
            "fail-closed verdict — it records nothing about why the artifact was "
            "rejected and aborts the caller."
        )
    assert report.findings, f"{case_id}: returned an empty report"
    assert not _accepting(report), (
        f"{case_id}: accepted an artifact carrying {OFF_VOCABULARY!r}, which names no "
        "value in that field's vocabulary"
    )


def test_the_sweep_actually_covers_something():
    """A sweep that enumerated nothing would pass silently."""
    assert len(CASES) >= 90, len(CASES)
    covered = {case_id.rsplit("/", 1)[0] for case_id, *_ in CASES}
    for validator in (
        "lifecycle-separation",
        "receipt-completeness",
        "evidence-bundle-completeness",
        "required-evidence",
        "execution-bundle-completeness",
        "provenance-completeness",
        "contract-schema-compatibility",
        "work-dependency-graph",
        "write-scope-containment",
        "authority-ceiling",
        "role-separation",
        "toolkit-coherence",
        "integration-preflight",
        "decision-explainability",
        "reconcile",
    ):
        assert validator in covered, validator


def test_the_clean_artifacts_carry_no_vocabulary_violations():
    """Otherwise every case above would pass for the wrong reason."""
    from agent_foundry.verify.independent import vocabulary_violations

    for label, model, _call in PROBES:
        assert vocabulary_violations(model) == [], label
