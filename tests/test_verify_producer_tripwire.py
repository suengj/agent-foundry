"""Behavioral guard: no validator may call a producer-owned rule, by any route.

The AST guard in `test_verify_independence.py` reads source. That is useful — it is
fast and it catches the ordinary regression — but it is structurally incapable of
being complete, because a call can be assembled at runtime:

    getattr(__import__("agent_foundry.models.interaction",
                       fromlist=["evidence_state_partition_violations"]),
            "evidence_state_partition_violations")(...)

That expression restores the exact false-PASS coupling AF7 was blocked for, and no
syntactic scan sees it. Enumerating dynamic spellings is a losing arms race, so this
file checks *what happens* instead of what the source looks like: each producer rule
is wrapped in a tripwire, every validator is then run over real artifacts, and the
tripwire raises if validation logic reaches for the rule.

Two guards, different mechanisms — the same principle the rest of this Work Item
rests on. The AST guard gives cheap feedback; this one is the complete answer.

**Legitimate versus coupled.** A producer rule is *supposed* to run when pydantic
constructs a model — including models that verify builds for its own results, such
as a `ValidationFinding`. So the tripwire does not ask "was a verify module on the
stack"; it asks which came first walking outward: a pydantic frame (model
construction asked for this rule) or a verify frame (validation logic asked for it
directly).
"""

from __future__ import annotations

import inspect
import os
from pathlib import Path

import pytest

from agent_foundry.models import EvidenceState, IntegrationHealthState
from agent_foundry.verify import (
    build_decision_trace,
    classify_repeated_failures,
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
from agent_foundry.verify.receipt import receipt_artifacts
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

VERIFY_DIR = (
    Path(__file__).resolve().parents[1] / "src" / "agent_foundry" / "verify"
).resolve()
MODELS_DIR = (
    Path(__file__).resolve().parents[1] / "src" / "agent_foundry" / "models"
).resolve()

# Explicit registry: the module-level helpers in `models/` that a pydantic validator
# uses to decide whether an artifact may be constructed. Written out rather than only
# discovered, so that adding a producer rule is a deliberate act — and cross-checked
# against AST discovery below, so the list cannot silently fall behind the code.
PRODUCER_VALIDATION_RULES: tuple[tuple[str, str], ...] = (
    ("agent_foundry.models._producer_rules", "disposition_obligation_violations"),
    ("agent_foundry.models._producer_rules", "evidence_state_partition_violations"),
    ("agent_foundry.models.interaction", "_parse_optional_datetime"),
    ("agent_foundry.models.base", "validate_schema_compatibility"),
    ("agent_foundry.models.compat", "migrate_contract_payload"),
    ("agent_foundry.models.base", "lint_no_raw_secrets"),
    ("agent_foundry.models.integrations", "_parse_secret_ref_string"),
)


class ProducerRuleCalledFromValidation(AssertionError):
    """A validator reached for a rule that gates artifact construction."""


def _classify_caller(frame_files: list[str]) -> str:
    """Who asked for this rule: model construction, or validation logic?

    Takes filenames rather than live frames so the decision itself is unit-testable.
    Walking outward from the rule, whichever boundary is met first decides:

    * a pydantic frame first  → a model is being constructed; the rule is doing its
      job, including when the model being built is one of verify's own result types;
    * a verify frame first    → validation logic called the rule directly, which is
      the coupling this guard exists to forbid.
    """
    for filename in frame_files:
        resolved = str(Path(filename).resolve()) if filename else ""
        if f"{os.sep}pydantic{os.sep}" in resolved:
            return "model-construction"
        if resolved.startswith(str(VERIFY_DIR) + os.sep):
            return "validation-logic"
    return "other"


def _tripwire(module_name: str, attribute: str, original):
    def guarded(*args, **kwargs):
        frame_files = [frame.filename for frame in inspect.stack()[1:]]
        if _classify_caller(frame_files) == "validation-logic":
            raise ProducerRuleCalledFromValidation(
                f"{module_name}.{attribute} was called from validation logic. "
                "A model validator's helper decides whether an artifact may exist; "
                "re-derive the rule in verify/independent.py instead."
            )
        return original(*args, **kwargs)

    return guarded


@pytest.fixture
def producer_tripwires(monkeypatch):
    """Wrap every registered producer rule for the duration of one test."""
    import importlib

    for module_name, attribute in PRODUCER_VALIDATION_RULES:
        module = importlib.import_module(module_name)
        original = getattr(module, attribute)
        monkeypatch.setattr(module, attribute, _tripwire(module_name, attribute, original))
    yield


def _exercise_every_validator(fixtures: dict) -> int:
    """Run the whole validation surface over prepared artifacts.

    Inputs are built *before* the tripwires go up, so fixture construction — which
    legitimately runs the producer rules — is outside the window under test. Forged
    inputs are included so the rejection paths run too: those are the branches most
    likely to reach for a producer's rule.
    """
    artifacts = fixtures["artifacts"]
    reports = [
        validate_contract_schema_compatibility(
            [("work-item", artifacts["work_item"]), ("lock", artifacts["lock"])]
        ),
        validate_work_dependency_graph([artifacts["work_item"]]),
        validate_toolkit_coherence(
            artifacts["task_toolkit"], artifacts["lock"], artifacts["registry"]
        ),
        validate_authority_ceiling(
            artifacts["bundle"].authority,
            work_item=artifacts["work_item"],
            manifest=artifacts["manifest"],
            task_toolkit=artifacts["task_toolkit"],
            role=artifacts["role"],
            permission_profile=artifacts["permission_profile"],
            registry=artifacts["registry"],
        ),
        validate_write_scope_containment(
            artifacts["bundle"].authority,
            work_item=artifacts["work_item"],
            role=artifacts["role"],
        ),
        validate_role_separation(
            [artifacts["bundle"]], review_decisions=[fixtures["review"]]
        ),
        validate_integration_preflight(
            [fixtures["integration"]],
            required_ids=["work-tracker"],
            observed_health=[health("work-tracker", IntegrationHealthState.AUTHORIZED)],
        ),
        validate_integration_preflight([], required_ids=["work-tracker"]),
        validate_required_evidence(artifacts["work_item"], fixtures["evidence"]),
        validate_required_evidence(artifacts["work_item"], fixtures["forged_evidence"]),
        validate_evidence_bundle_completeness(fixtures["evidence"]),
        validate_evidence_bundle_completeness(fixtures["forged_evidence"]),
        validate_provenance_completeness(artifacts["bundle"]),
        validate_execution_bundle_completeness(artifacts["bundle"]),
        validate_lifecycle_separation(
            fixtures["receipt"], required_evidence_states=[EvidenceState.VALIDATED]
        ),
        validate_lifecycle_separation(fixtures["forged_receipt"]),
        validate_receipt_completeness(
            fixtures["receipt"], artifacts=fixtures["receipt_artifacts"]
        ),
        validate_receipt_completeness(fixtures["forged_receipt"]),
        validate_decision_explainability(
            artifacts["bundle"],
            manifest=artifacts["manifest"],
            receipt=fixtures["receipt"],
        ),
    ]
    build_decision_trace(artifacts["bundle"], manifest=artifacts["manifest"])
    classify_repeated_failures([])
    reports.append(
        reconcile_work_item(
            work_item=artifacts["work_item"],
            tracker=fixtures["tracker"],
            repository=fixtures["repository"],
            runtime=fixtures["runtime"],
        )
    )
    assert all(report.findings for report in reports)
    return len(reports)


@pytest.fixture
def validation_fixtures():
    """Artifacts built before any tripwire is installed."""
    artifacts = compiled()
    receipt, _ = complete_receipt()
    evidence = full_evidence_bundle()
    forged_receipt = type(receipt).model_construct(
        **{**receipt.__dict__, "attained_evidence_states": [], "not_required_evidence_states": []}
    )
    forged_evidence = type(evidence).model_construct(
        **{**evidence.__dict__, "identity": None, "items": []}
    )
    return {
        "artifacts": artifacts,
        "receipt": receipt,
        "forged_receipt": forged_receipt,
        "evidence": evidence,
        "forged_evidence": forged_evidence,
        "review": approving_review(),
        "integration": integration_spec(),
        "tracker": tracker(),
        "repository": repository(),
        "runtime": runtime(),
        "receipt_artifacts": receipt_artifacts(
            artifacts["bundle"],
            project_lock=artifacts["lock"],
            registry=artifacts["registry"],
        ),
    }


def test_no_validator_calls_a_producer_rule_by_any_route(
    validation_fixtures, producer_tripwires
):
    """The complete guard: every validator, every producer rule, actual behavior."""
    exercised = _exercise_every_validator(validation_fixtures)
    assert exercised >= 15, exercised


def test_the_tripwire_catches_a_getattr_bypass_the_ast_guard_cannot_see(
    validation_fixtures, producer_tripwires
):
    """Prove it bites, against the exact dynamic route the reviewer demonstrated.

    A module is compiled with a filename inside `verify/`, so it is indistinguishable
    from validation logic to the classifier, and it assembles the call at runtime.
    The AST guard reads real files and never sees this; the tripwire does.
    """
    source = (
        "def bypass():\n"
        "    return getattr(\n"
        "        __import__(\n"
        "            'agent_foundry.models._producer_rules',\n"
        "            fromlist=['evidence_state_partition_violations'],\n"
        "        ),\n"
        "        'evidence_state_partition_violations',\n"
        "    )(attained=[], not_required=[])\n"
    )
    namespace: dict = {}
    exec(compile(source, str(VERIFY_DIR / "synthetic_bypass.py"), "exec"), namespace)

    with pytest.raises(ProducerRuleCalledFromValidation, match="validation logic"):
        namespace["bypass"]()


def test_the_tripwire_allows_legitimate_model_construction(
    validation_fixtures, producer_tripwires
):
    """Guard the guard from the other side: it must not fire on ordinary use.

    Constructing a model runs the producer rules by design, and verify constructs its
    own result models. A tripwire that fired on those would be unusable, and would be
    quietly disabled by the next person to hit it.
    """
    from agent_foundry.models import RunFinding, ValidationFinding, ValidationOutcome
    from agent_foundry.models.interaction import ReceiptContractError

    finding = ValidationFinding(
        validator_id="x", outcome=ValidationOutcome.PASS, subject="s", message="m"
    )
    assert finding.subject == "s"

    # And the producer rule still does its job while wrapped.
    with pytest.raises(ReceiptContractError, match="RESIDUAL requires follow_up_work_ref"):
        RunFinding.model_validate(
            {"id": "F", "disposition": "RESIDUAL", "summary": "s"}
        )


@pytest.mark.parametrize(
    ("frames", "expected"),
    [
        ([f"{VERIFY_DIR}/validators.py", "/x/pydantic/main.py"], "validation-logic"),
        ([f"{MODELS_DIR}/interaction.py", "/x/pydantic/main.py"], "model-construction"),
        (
            [
                f"{MODELS_DIR}/base.py",
                "/x/pydantic/main.py",
                f"{VERIFY_DIR}/reconcile.py",
            ],
            "model-construction",
        ),
        ([f"{MODELS_DIR}/interaction.py", "/x/other.py"], "other"),
    ],
)
def test_the_caller_classifier_decides_on_whichever_boundary_comes_first(frames, expected):
    """The third case is the one that matters: verify built a result model.

    The verify frame is present, but below the pydantic frame, so the rule was
    invoked by model construction and not by validation logic.
    """
    assert _classify_caller(frames) == expected


# --- the registry stays in step with the code ------------------------------------


def _ast_discovered_rules() -> set[str]:
    """Same discovery the AST guard uses, so drift between the two is visible."""
    from test_verify_independence import producer_validation_rules

    return set(producer_validation_rules())


def test_every_discovered_producer_rule_is_registered_for_tripwiring():
    registered = {attribute for _module, attribute in PRODUCER_VALIDATION_RULES}
    missing = sorted(_ast_discovered_rules() - registered)
    assert missing == [], (
        f"producer rule(s) {missing} are enforced by a model validator but are not "
        "tripwired; add them to PRODUCER_VALIDATION_RULES"
    )


def test_every_registered_rule_actually_exists():
    import importlib

    for module_name, attribute in PRODUCER_VALIDATION_RULES:
        module = importlib.import_module(module_name)
        assert callable(getattr(module, attribute)), f"{module_name}.{attribute}"


def test_the_registry_covers_the_two_rules_this_guard_was_written_for():
    registered = {attribute for _module, attribute in PRODUCER_VALIDATION_RULES}
    assert "evidence_state_partition_violations" in registered
    assert "disposition_obligation_violations" in registered
