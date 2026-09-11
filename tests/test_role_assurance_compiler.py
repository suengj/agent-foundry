"""SUE-583 golden compilation and anti-vacuity tests."""

from __future__ import annotations

import pytest

from agent_foundry.compile import compile_role_assurance
from agent_foundry.models import (
    ApprovalClass,
    Ambiguity,
    AssuranceProfile,
    AssuranceMode,
    AssuranceRequirement,
    Autonomy,
    AuthorityCeiling,
    BlastRadius,
    CapabilityDeclaration,
    CompilationCause,
    CompilationCauseConsequence,
    CompilationInputLocator,
    CompilationInputPath,
    CompilationPredicate,
    CompilationPredicateOperator,
    ConsequenceClass,
    CorrectnessObservability,
    ControlCondition,
    ControlTrigger,
    DecisionRights,
    ExternalEffectClass,
    FOUNDRY_SCHEMA_VERSION,
    EvidenceClass,
    EvidenceStrength,
    OperatingConstraints,
    OperatingModel,
    ProjectProfile,
    Reversibility,
    RoleContract,
    SkillRoleConstraint,
    RoleAssuranceCompilation,
    TaskToolkit,
    ToolkitLock,
    ToolkitResolutionError,
    WorkItemContract,
    WorkCharacteristics,
    dump_json,
    validate_compilation_explainability,
)
from agent_foundry.toolkit import (
    resolve_task_toolkit_for_compilation,
    resolve_task_toolkit_for_work_item,
)
from agent_foundry.toolkit.ceiling import validate_task_toolkit_against_ceiling
from agent_foundry.toolkit.builtin_registry import (
    build_default_registry,
    build_default_registry_budget_profiles,
    build_default_registry_permission_profiles,
)


def _profile() -> ProjectProfile:
    return ProjectProfile(schema_version=FOUNDRY_SCHEMA_VERSION, project_name="synthetic")


def _operating_model() -> OperatingModel:
    rights = DecisionRights(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        authority_ceilings=[
            AuthorityCeiling(
                consequence=ConsequenceClass.LOW,
                max_external_effect=ExternalEffectClass.REPOSITORY_WRITE,
                max_autonomy=Autonomy.BOUNDED_EXTERNAL_WRITE,
                approval_class=ApprovalClass.AUTOMATIC,
            ),
            AuthorityCeiling(
                consequence=ConsequenceClass.MEDIUM,
                max_external_effect=ExternalEffectClass.REPOSITORY_WRITE,
                max_autonomy=Autonomy.BOUNDED_EXTERNAL_WRITE,
                approval_class=ApprovalClass.APPROVAL_REQUIRED,
            ),
            AuthorityCeiling(
                consequence=ConsequenceClass.HIGH,
                max_external_effect=ExternalEffectClass.SHARED_SERVICE_WRITE,
                max_autonomy=Autonomy.APPROVED_APPLY,
                approval_class=ApprovalClass.APPROVAL_REQUIRED,
                policy_evidence_refs=["policy:high-floor"],
            ),
            AuthorityCeiling(
                consequence=ConsequenceClass.CRITICAL,
                max_external_effect=ExternalEffectClass.PUBLICATION,
                max_autonomy=Autonomy.APPROVED_APPLY,
                approval_class=ApprovalClass.APPROVAL_REQUIRED,
                policy_evidence_refs=["policy:critical-floor"],
            ),
        ],
    )
    return OperatingModel(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        id="synthetic-operating-model",
        description="synthetic SUE-583 policy",
        constraints=OperatingConstraints(
            max_external_effect=ExternalEffectClass.PUBLICATION,
            max_autonomy=Autonomy.APPROVED_APPLY,
        ),
        decision_rights=rights,
        assurance=AssuranceProfile(
            default_requirement=AssuranceRequirement(
                blast_radius=BlastRadius(
                    consequence=ConsequenceClass.LOW,
                    uncertainty=Ambiguity.PROCEDURAL,
                    coupling="low",
                    reversibility=Reversibility.TRIVIAL,
                    observability=CorrectnessObservability.HIGH,
                ),
                minimum_evidence_strength=EvidenceStrength.MODERATE,
                required_evidence=(EvidenceClass.DETERMINISTIC_TEST,),
                required_modes=(AssuranceMode.DETERMINISTIC_TESTS,),
            )
        ),
    )


def _work(**overrides: object) -> WorkCharacteristics:
    values: dict[str, object] = {
        "workflow_kind": "behaviour-preserving-refactor",
        "external_effect": ExternalEffectClass.REPOSITORY_WRITE,
        "consequence": ConsequenceClass.LOW,
        "capability_declarations": tuple(
            CapabilityDeclaration(
                capability_id=capability_id,
                available=True,
                verified=True,
            )
            for capability_id in (
                "repository.read",
                "repository.write",
                "validation.test",
                "validation.review",
                "inspection.read",
                "work.read",
                "work.write",
                "runtime.verify",
            )
        ),
    }
    values.update(overrides)
    return WorkCharacteristics(**values)


def _compile(work: WorkCharacteristics) -> RoleAssuranceCompilation:
    return compile_role_assurance(_profile(), _operating_model(), work)


@pytest.mark.parametrize(
    ("case_id", "work", "selected", "excluded", "gates"),
    [
        pytest.param(
            "docs-only",
            _work(workflow_kind="docs-only"),
            {"builder", "validator"},
            {"manager", "reviewer", "runtime-verifier"},
            {"deterministic-validation"},
            id="docs-only",
        ),
        pytest.param(
            "read-only-exact-sha-review",
            _work(
                workflow_kind="read-only-exact-sha-review",
                external_effect=ExternalEffectClass.READ_ONLY,
                required_assurance_modes=(AssuranceMode.INDEPENDENT_REVIEW,),
                required_evidence=(EvidenceClass.INDEPENDENT_REVIEW,),
            ),
            {"validator", "reviewer"},
            {"builder", "manager", "runtime-verifier"},
            {"deterministic-validation", "independent-review"},
            id="read-only-exact-sha-review",
        ),
        pytest.param(
            "behaviour-preserving-refactor",
            _work(workflow_kind="behaviour-preserving-refactor"),
            {"builder", "validator"},
            {"manager", "reviewer", "runtime-verifier"},
            {"deterministic-validation"},
            id="behaviour-preserving-refactor",
        ),
        pytest.param(
            "cross-component-sit",
            _work(
                workflow_kind="cross-component-change",
                requires_sit=True,
                coupling="high",
            ),
            {"builder", "validator", "runtime-verifier"},
            {"manager", "reviewer"},
            {"deterministic-validation", "runtime-readback", "sit"},
            id="cross-component-sit",
        ),
        pytest.param(
            "source-change-resume",
            _work(workflow_kind="source-change-resume"),
            {"builder", "validator"},
            {"manager", "reviewer", "runtime-verifier"},
            {"deterministic-validation"},
            id="source-change-resume",
        ),
        pytest.param(
            "apply-preview-reserved-authority",
            _work(
                workflow_kind="apply-preview",
                external_effect=ExternalEffectClass.SHARED_SERVICE_WRITE,
                consequence=ConsequenceClass.HIGH,
                reserved_authority=True,
            ),
            {"manager", "builder", "validator", "reviewer", "integrator"},
            {"explorer", "runtime-verifier"},
            {"deterministic-validation", "independent-review"},
            id="apply-preview-reserved-authority",
        ),
    ],
)
def test_golden_matrix_compiles_minimum_topology(case_id, work, selected, excluded, gates):
    result = _compile(work)
    assert set(result.selected_roles) == selected, case_id
    assert excluded <= set(result.excluded_roles), case_id
    assert set(result.required_gates) == gates, case_id
    assert result.topology.writer_role == ("builder" if "builder" in selected else None)
    assert result.topology.single_writer
    assert result.unresolved_prerequisites == (), case_id
    assert validate_compilation_explainability(result).accepted(), case_id


def test_no_over_refusal_across_six_work_items_and_consequence_variants():
    work_items = (
        _work(workflow_kind="docs-only"),
        _work(
            workflow_kind="read-only-exact-sha-review",
            external_effect=ExternalEffectClass.READ_ONLY,
            required_assurance_modes=(AssuranceMode.INDEPENDENT_REVIEW,),
            required_evidence=(EvidenceClass.INDEPENDENT_REVIEW,),
        ),
        _work(workflow_kind="behaviour-preserving-refactor"),
        _work(
            workflow_kind="cross-component-change",
            requires_sit=True,
            coupling="high",
        ),
        _work(workflow_kind="source-change-resume"),
        _work(
            workflow_kind="apply-preview",
            external_effect=ExternalEffectClass.SHARED_SERVICE_WRITE,
            reserved_authority=True,
        ),
    )
    checked = 0
    for work in work_items:
        for consequence in ConsequenceClass:
            result = _compile(work.model_copy(update={"consequence": consequence}))
            assert validate_compilation_explainability(result).accepted(), (
                work.workflow_kind,
                consequence,
            )
            checked += 1
    assert checked == 24


def test_compilation_is_byte_deterministic_for_identical_inputs():
    work = _work(workflow_kind="cross-component-change", requires_sit=True, coupling="high")
    assert dump_json(_compile(work)) == dump_json(_compile(work))


def test_high_consequence_floor_catches_removal_of_assurance_rule():
    """Mutation target: removing the compiler high-consequence rule must fail here."""
    result = _compile(
        _work(
            workflow_kind="behaviour-preserving-refactor",
            consequence=ConsequenceClass.HIGH,
        )
    )
    assert "reviewer" in result.selected_roles
    assert result.assurance_requirement.independent_review
    assert AssuranceMode.INDEPENDENT_REVIEW in result.assurance_requirement.required_modes


def test_smaller_prompt_cannot_omit_mandatory_high_consequence_gate():
    result = _compile(
        _work(
            workflow_kind="behaviour-preserving-refactor",
            consequence=ConsequenceClass.HIGH,
            required_assurance_modes=(),
        )
    )
    assert "independent-review" in result.required_gates
    assert "reviewer" in result.selected_roles


def test_explainability_rejects_persisted_assurance_blast_radius_relabel():
    result = _compile(_work(consequence=ConsequenceClass.HIGH))
    payload = result.model_dump(mode="json")
    payload["assurance_requirement"]["blast_radius"]["consequence"] = ConsequenceClass.LOW.value

    forged = RoleAssuranceCompilation.model_validate(payload)
    report = validate_compilation_explainability(forged)

    assert not report.accepted()
    assert any("assurance blast radius" in finding for finding in report.findings)


def test_explainability_rejects_coherent_high_assurance_floor_downgrade():
    result = _compile(_work(consequence=ConsequenceClass.HIGH))
    payload = result.model_dump(mode="json")
    independent_mode = AssuranceMode.INDEPENDENT_REVIEW.value
    independent_evidence = EvidenceClass.INDEPENDENT_REVIEW.value
    payload["assurance_requirement"]["required_modes"] = [
        item
        for item in payload["assurance_requirement"]["required_modes"]
        if item != independent_mode
    ]
    payload["assurance_requirement"]["required_evidence"] = [
        item
        for item in payload["assurance_requirement"]["required_evidence"]
        if item != independent_evidence
    ]
    payload["assurance_requirement"]["independent_review"] = False
    payload["assurance_requirement"]["minimum_distinct_actors"] = 1
    payload["required_gates"] = [
        gate for gate in payload["required_gates"] if gate != "independent-review"
    ]
    payload["topology"]["selected_roles"].remove("reviewer")
    payload["topology"]["excluded_roles"].append("reviewer")
    payload["topology"]["required_roles"].remove("reviewer")
    excluded_reviewer_cause = {
        "locator": {
            "path": CompilationInputPath.ASSURANCE_INDEPENDENT_REVIEW.value,
        },
        "predicate": {
            "operator": CompilationPredicateOperator.IS.value,
            "value": False,
        },
        "evaluated": True,
        "consequence": CompilationCauseConsequence.EXCLUDED.value,
    }
    for decision in payload["role_decisions"]:
        if decision["role_id"] == "reviewer":
            decision["selected"] = False
            decision["causes"] = [excluded_reviewer_cause]
    for entry in payload["explanation_trace"]:
        if entry["component"] == "role" and entry["component_id"] == "reviewer":
            entry["selected"] = False
            entry["causes"] = [excluded_reviewer_cause]
    for decision in payload["assurance_decisions"]:
        if decision["component"] == "assurance-mode" and decision["component_id"] == independent_mode:
            decision["selected"] = False
            decision["causes"] = [
                {
                    "locator": {
                        "path": CompilationInputPath.ASSURANCE_REQUIRED_MODES.value,
                        "item": independent_mode,
                    },
                    "predicate": {
                        "operator": CompilationPredicateOperator.CONTAINS.value,
                        "value": independent_mode,
                    },
                    "evaluated": False,
                    "consequence": CompilationCauseConsequence.EXCLUDED.value,
                }
            ]
        if decision["component"] == "assurance-evidence" and decision["component_id"] == independent_evidence:
            decision["selected"] = False
            decision["causes"] = [
                {
                    "locator": {
                        "path": CompilationInputPath.ASSURANCE_REQUIRED_EVIDENCE.value,
                        "item": independent_evidence,
                    },
                    "predicate": {
                        "operator": CompilationPredicateOperator.CONTAINS.value,
                        "value": independent_evidence,
                    },
                    "evaluated": False,
                    "consequence": CompilationCauseConsequence.EXCLUDED.value,
                }
            ]
    for entry in payload["explanation_trace"]:
        if entry["component"] == "assurance-mode" and entry["component_id"] == independent_mode:
            entry["selected"] = False
            entry["causes"] = payload["assurance_decisions"][
                next(
                    index
                    for index, decision in enumerate(payload["assurance_decisions"])
                    if decision["component"] == "assurance-mode"
                    and decision["component_id"] == independent_mode
                )
            ]["causes"]
        if entry["component"] == "assurance-evidence" and entry["component_id"] == independent_evidence:
            entry["selected"] = False
            entry["causes"] = payload["assurance_decisions"][
                next(
                    index
                    for index, decision in enumerate(payload["assurance_decisions"])
                    if decision["component"] == "assurance-evidence"
                    and decision["component_id"] == independent_evidence
                )
            ]["causes"]
    payload["escalations"] = [
        item for item in payload["escalations"] if item["id"] != "review-failure"
    ]

    forged = RoleAssuranceCompilation.model_validate(payload)
    report = validate_compilation_explainability(forged)

    assert not report.accepted()
    assert any("assurance floor" in finding for finding in report.findings)
    assert any("required_gates" in finding for finding in report.findings)
    assert any("role topology" in finding for finding in report.findings)
    assert any("canonical assurance decision" in finding for finding in report.findings)


def test_explainability_rejects_deleted_required_assurance_gate():
    result = _compile(_work(consequence=ConsequenceClass.HIGH))
    payload = result.model_dump(mode="json")
    payload["required_gates"] = [
        gate for gate in payload["required_gates"] if gate != "independent-review"
    ]

    forged = RoleAssuranceCompilation.model_validate(payload)
    report = validate_compilation_explainability(forged)

    assert not report.accepted()
    assert any("required_gates" in finding for finding in report.findings)


def test_explainability_rejects_false_unresolved_prerequisite_and_escalation_cause():
    result = _compile(
        _work(
            external_effect=ExternalEffectClass.READ_ONLY,
            required_capabilities=("repository.write",),
            capability_declarations=(
                CapabilityDeclaration(
                    capability_id="repository.write",
                    available=True,
                    verified=True,
                ),
            ),
        )
    )
    payload = result.model_dump(mode="json")
    false_cause = {
        "locator": {
            "path": CompilationInputPath.WORK_RESERVED_AUTHORITY.value,
        },
        "predicate": {
            "operator": CompilationPredicateOperator.IS.value,
            "value": True,
        },
        "evaluated": True,
        "consequence": CompilationCauseConsequence.SELECTED.value,
    }
    assert false_cause["evaluated"] is True
    for item in payload["unresolved_prerequisites"]:
        if item["id"] == "capability-authority:repository.write":
            item["causes"] = [false_cause]
    for item in payload["escalations"]:
        if item["id"] == "escalate:capability-authority:repository.write":
            item["causes"] = [false_cause]

    forged = RoleAssuranceCompilation.model_validate(payload)
    report = validate_compilation_explainability(forged)

    assert not report.accepted()
    assert any("unresolved prerequisite" in finding for finding in report.findings)
    assert any("unrelated input" in finding for finding in report.findings)


def test_explainability_rejects_authority_cause_consequence_inversion_and_linked_escalation():
    result = _compile(
        _work(
            external_effect=ExternalEffectClass.READ_ONLY,
            required_capabilities=("repository.write",),
            capability_declarations=(
                CapabilityDeclaration(
                    capability_id="repository.write",
                    available=True,
                    verified=True,
                ),
            ),
        )
    )
    payload = result.model_dump(mode="json")
    prerequisite = next(
        item
        for item in payload["unresolved_prerequisites"]
        if item["id"] == "capability-authority:repository.write"
    )
    ceiling_cause = next(
        cause
        for cause in prerequisite["causes"]
        if cause["locator"]["path"] == CompilationInputPath.CAPABILITY_MIN_EXTERNAL_EFFECT.value
    )
    assert ceiling_cause["evaluated"] is False
    ceiling_cause["consequence"] = CompilationCauseConsequence.SELECTED.value
    escalation = next(
        item
        for item in payload["escalations"]
        if item["id"] == "escalate:capability-authority:repository.write"
    )
    escalation["causes"] = list(prerequisite["causes"])

    forged = RoleAssuranceCompilation.model_validate(payload)
    report = validate_compilation_explainability(forged)

    assert not report.accepted()
    assert any("consequence" in finding for finding in report.findings)


@pytest.mark.parametrize(
    "edges",
    [
        ("builder->reviewer",),
        ("validator->validator",),
        (),
    ],
    ids=("excluded-role", "self-loop", "missing-edge"),
)
def test_explainability_rejects_forged_topology_edges(edges):
    result = _compile(_work())
    payload = result.model_dump(mode="json")
    payload["topology"]["edges"] = list(edges)

    forged = RoleAssuranceCompilation.model_validate(payload)
    report = validate_compilation_explainability(forged)

    assert not report.accepted()
    assert any("topology edges" in finding for finding in report.findings)


def test_compiler_emits_natural_topology_edges_in_selected_order():
    result = _compile(_work())

    assert result.topology.edges == ("builder->validator",)
    assert validate_compilation_explainability(result).accepted()


def test_explainability_rejects_role_decision_cause_not_matching_trace():
    result = _compile(_work())
    payload = result.model_dump(mode="json")
    false_cause = {
        "locator": {"path": CompilationInputPath.WORK_RESERVED_AUTHORITY.value},
        "predicate": {
            "operator": CompilationPredicateOperator.IS.value,
            "value": True,
        },
        "evaluated": True,
        "consequence": CompilationCauseConsequence.SELECTED.value,
    }
    next(item for item in payload["role_decisions"] if item["role_id"] == "builder")[
        "causes"
    ] = [false_cause]

    forged = RoleAssuranceCompilation.model_validate(payload)
    report = validate_compilation_explainability(forged)

    assert not report.accepted()
    assert any("role decision 'builder' causes" in finding for finding in report.findings)


def test_explainability_rejects_assurance_decision_cause_not_matching_trace():
    result = _compile(_work())
    payload = result.model_dump(mode="json")
    false_cause = {
        "locator": {"path": CompilationInputPath.WORK_RESERVED_AUTHORITY.value},
        "predicate": {
            "operator": CompilationPredicateOperator.IS.value,
            "value": True,
        },
        "evaluated": True,
        "consequence": CompilationCauseConsequence.SELECTED.value,
    }
    next(
        item
        for item in payload["assurance_decisions"]
        if item["component"] == "assurance-mode"
        and item["component_id"] == AssuranceMode.DETERMINISTIC_TESTS.value
    )["causes"] = [false_cause]

    forged = RoleAssuranceCompilation.model_validate(payload)
    report = validate_compilation_explainability(forged)

    assert not report.accepted()
    assert any("assurance decision" in finding and "causes" in finding for finding in report.findings)


def test_explainability_rejects_capability_requirement_cause_not_matching_trace():
    result = _compile(_work())
    payload = result.model_dump(mode="json")
    false_cause = {
        "locator": {"path": CompilationInputPath.WORK_RESERVED_AUTHORITY.value},
        "predicate": {
            "operator": CompilationPredicateOperator.IS.value,
            "value": True,
        },
        "evaluated": True,
        "consequence": CompilationCauseConsequence.SELECTED.value,
    }
    next(
        item
        for item in payload["capability_requirements"]
        if item["capability_id"] == "repository.read"
    )["causes"] = [false_cause]

    forged = RoleAssuranceCompilation.model_validate(payload)
    report = validate_compilation_explainability(forged)

    assert not report.accepted()
    assert any("capability requirement 'repository.read' causes" in finding for finding in report.findings)


def test_explainability_rejects_forged_authority_policy_evidence_refs():
    result = _compile(_work())
    payload = result.model_dump(mode="json")
    payload["authority_ceiling"]["policy_evidence_refs"] = ["forged:authority-proof"]

    forged = RoleAssuranceCompilation.model_validate(payload)
    report = validate_compilation_explainability(forged)

    assert not report.accepted()
    assert any("policy_evidence_refs" in finding for finding in report.findings)


def test_explainability_rejects_forged_builtin_escalation_reason_and_action():
    result = _compile(_work())
    payload = result.model_dump(mode="json")
    escalation = next(
        item
        for item in payload["escalations"]
        if item["id"] == "required-evidence-missing"
    )
    escalation["reason"] = "there is no required evidence"
    escalation["action"] = "continue without evidence"

    forged = RoleAssuranceCompilation.model_validate(payload)
    report = validate_compilation_explainability(forged)

    assert not report.accepted()
    assert sum("deterministic" in finding for finding in report.findings) >= 2


def test_explainability_rejects_forged_prerequisite_and_linked_escalation_reasons():
    result = _compile(
        _work(
            external_effect=ExternalEffectClass.READ_ONLY,
            required_capabilities=("repository.write",),
            capability_declarations=(
                CapabilityDeclaration(
                    capability_id="repository.write",
                    available=True,
                    verified=True,
                ),
            ),
        )
    )
    payload = result.model_dump(mode="json")
    prerequisite = next(
        item
        for item in payload["unresolved_prerequisites"]
        if item["id"] == "capability-authority:repository.write"
    )
    prerequisite["reason"] = "capability is within the ceiling"
    escalation = next(
        item
        for item in payload["escalations"]
        if item["id"] == "escalate:capability-authority:repository.write"
    )
    escalation["reason"] = "capability is within the ceiling"
    escalation["action"] = "continue"

    forged = RoleAssuranceCompilation.model_validate(payload)
    report = validate_compilation_explainability(forged)

    assert not report.accepted()
    assert any("deterministic" in finding for finding in report.findings)
    assert any("deterministic action" in finding for finding in report.findings)


def test_explainability_rejects_forged_retained_custom_escalation_reason():
    condition = ControlCondition(
        id="synthetic-policy-conflict",
        trigger=ControlTrigger.POLICY_CONFLICT,
        reason="retained canonical reason",
    )
    operating_model = _operating_model().model_copy(
        update={"escalation_conditions": (condition,)}
    )
    result = compile_role_assurance(_profile(), operating_model, _work())
    payload = result.model_dump(mode="json")
    next(
        item
        for item in payload["escalations"]
        if item["id"] == condition.id
    )["reason"] = "there is no policy conflict"

    forged = RoleAssuranceCompilation.model_validate(payload)
    report = validate_compilation_explainability(forged)

    assert not report.accepted()
    assert any("retained ControlCondition reason" in finding for finding in report.findings)


def test_explainability_accepts_retained_operating_model_escalation_condition():
    condition = ControlCondition(
        id="synthetic-policy-conflict",
        trigger=ControlTrigger.POLICY_CONFLICT,
        reason="synthetic policy conflict requires escalation",
    )
    operating_model = _operating_model().model_copy(
        update={"escalation_conditions": (condition,)}
    )
    result = compile_role_assurance(_profile(), operating_model, _work())

    assert any(item.id == condition.id for item in result.escalations)
    assert validate_compilation_explainability(result).accepted()


def test_tool_availability_is_not_permission():
    result = _compile(
        _work(
            workflow_kind="read-only-exact-sha-review",
            external_effect=ExternalEffectClass.READ_ONLY,
            required_capabilities=("repository.write",),
            capability_declarations=(
                CapabilityDeclaration(
                    capability_id="repository.write",
                    available=True,
                    verified=True,
                ),
            ),
        )
    )
    requirement = next(
        item for item in result.capability_requirements if item.capability_id == "repository.write"
    )
    assert requirement.available is True
    assert requirement.authorized is False
    assert any(item.id == "capability-authority:repository.write" for item in result.unresolved_prerequisites)


def test_task_toolkit_cannot_select_capability_above_compiled_ceiling():
    work = WorkItemContract(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        id="WI-COMPILED-CEILING",
        title="bounded source change",
        work_class="capability",
        objective="exercise compiled ceiling",
        current_facts=("synthetic",),
        scope=("src",),
        out_of_scope=("runtime",),
        acceptance_criteria=("tests",),
        authority_class=ExternalEffectClass.REPOSITORY_WRITE,
        consequence_class=ConsequenceClass.LOW,
        required_evidence=("deterministic-test",),
        stop_conditions=("ceiling mismatch",),
    )
    lock = ToolkitLock(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        project_name="synthetic",
        capability_ids=["repository.read", "repository.write", "validation.test"],
        skill_ids=["bounded-change", "deterministic-test"],
        workflow_ids=["single-worker-validation"],
        role_ids=["builder", "validator"],
        permission_profile_ids=["repository-write-bounded"],
        budget_profile_ids=["default"],
    )
    ceiling = AuthorityCeiling(
        consequence=ConsequenceClass.LOW,
        max_external_effect=ExternalEffectClass.READ_ONLY,
        max_autonomy=Autonomy.SUGGEST,
        approval_class=ApprovalClass.AUTOMATIC,
    )
    with pytest.raises(ToolkitResolutionError, match="repository.write.*exceeds task ceiling"):
        resolve_task_toolkit_for_work_item(
            work,
            lock,
            registry=build_default_registry(),
            permission_profiles=build_default_registry_permission_profiles(),
            budget_profiles=build_default_registry_budget_profiles(),
            compiled_ceiling=ceiling,
        )


def test_finished_task_rejects_selected_role_capability_above_compiled_ceiling():
    base_registry = build_default_registry()
    write_manager = next(item for item in base_registry.roles if item.id == "manager").model_copy(
        update={"allowed_capabilities": ["repository.write"]}
    )
    registry = base_registry.model_copy(
        update={
            "roles": [
                write_manager if item.id == write_manager.id else item
                for item in base_registry.roles
            ]
        }
    )
    lock = _bridge_lock().model_copy(
        update={"role_ids": ["builder", "validator", "reviewer", "manager"]}
    )
    task = TaskToolkit(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        work_item_id="WI-READONLY-ROLE-CAPABILITY",
        capability_ids=["repository.read"],
        skill_ids=[],
        workflow_id="single-worker-validation",
        role_ids=["manager"],
        permission_profile_ids=["read-only"],
        budget_profile_ids=["default"],
    )
    work_item = _bridge_work_item(
        id="WI-READONLY-ROLE-CAPABILITY",
        authority_class=ExternalEffectClass.READ_ONLY,
    )
    ceiling = AuthorityCeiling(
        consequence=ConsequenceClass.LOW,
        max_external_effect=ExternalEffectClass.READ_ONLY,
        max_autonomy=Autonomy.SUGGEST,
        approval_class=ApprovalClass.AUTOMATIC,
    )
    with pytest.raises(ToolkitResolutionError, match="task role 'manager'.*above task ceiling"):
        validate_task_toolkit_against_ceiling(
            task,
            lock,
            registry,
            work_item,
            build_default_registry_permission_profiles(),
            compiled_ceiling=ceiling,
        )


def test_explanation_fixture_covers_manager_reviewer_validator_selection_and_nonselection():
    low = _compile(_work(workflow_kind="docs-only"))
    high = _compile(
        _work(
            workflow_kind="apply-preview",
            external_effect=ExternalEffectClass.SHARED_SERVICE_WRITE,
            consequence=ConsequenceClass.HIGH,
            reserved_authority=True,
        )
    )
    for result in (low, high):
        report = validate_compilation_explainability(result)
        assert report.accepted(), report.findings
        by_role = {item.role_id: item for item in result.role_decisions}
        assert by_role["manager"].causes
        assert by_role["reviewer"].causes
        assert by_role["validator"].causes
    assert not next(item for item in low.role_decisions if item.role_id == "manager").selected
    assert next(item for item in high.role_decisions if item.role_id == "manager").selected
    assert not next(item for item in low.role_decisions if item.role_id == "reviewer").selected
    assert next(item for item in high.role_decisions if item.role_id == "reviewer").selected


def test_profile_dimensions_are_descriptive_and_cannot_change_compiler_policy():
    profile = ProjectProfile(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        project_name="synthetic",
        dimensions=[
            {
                "dimension": "role.forbidden",
                "resolution": "resolved",
                "attributions": [{"value": "reviewer", "provenance": {"kind": "declared"}}],
            },
            {
                "dimension": "capability.required",
                "resolution": "resolved",
                "attributions": [{"value": "not-in-registry", "provenance": {"kind": "declared"}}],
            },
        ],
    )
    result = compile_role_assurance(
        profile,
        _operating_model(),
        _work(
            consequence=ConsequenceClass.HIGH,
            required_assurance_modes=(AssuranceMode.INDEPENDENT_REVIEW,),
        ),
    )
    assert "reviewer" in result.selected_roles
    assert not any(
        item.id == "capability-availability:not-in-registry"
        for item in result.unresolved_prerequisites
    )


def test_missing_capability_availability_stays_unknown_and_unresolved():
    result = compile_role_assurance(
        _profile(),
        _operating_model(),
        _work(
            required_capabilities=("repository.write",),
            capability_declarations=(),
        ),
    )
    requirement = next(
        item
        for item in result.capability_requirements
        if item.capability_id == "repository.write"
    )
    assert requirement.available is None
    assert any(
        item.id == "capability-availability:repository.write"
        for item in result.unresolved_prerequisites
    )


def test_workflow_names_do_not_infer_roles_or_gates():
    for workflow_kind in ("apply-api-analysis", "safety-sensitive-change"):
        result = _compile(
            _work(
                workflow_kind=workflow_kind,
                external_effect=ExternalEffectClass.READ_ONLY,
            )
        )
        assert set(result.selected_roles) == {"validator"}
        assert set(result.required_gates) == {"deterministic-validation"}


def test_empty_assurance_profile_uses_canonical_fail_closed_floor():
    model = _operating_model().model_copy(update={"assurance": AssuranceProfile()})
    work = _work(
        consequence=ConsequenceClass.CRITICAL,
        coupling="unknown",
        observability="unknown",
        capability_declarations=tuple(
            CapabilityDeclaration(
                capability_id=capability_id,
                available=True,
                verified=True,
            )
            for capability_id in (
                "repository.read",
                "repository.write",
                "validation.test",
                "validation.review",
                "work.read",
                "work.write",
                "runtime.verify",
            )
        ),
    )
    result = compile_role_assurance(_profile(), model, work)
    expected = model.assurance.for_blast_radius(
        BlastRadius(
            consequence=ConsequenceClass.CRITICAL,
            uncertainty=work.uncertainty,
            coupling=work.coupling,
            reversibility=work.reversibility,
            observability=work.observability,
        )
    )
    assert result.assurance_requirement == expected
    assert result.assurance_requirement.minimum_evidence_strength is EvidenceStrength.DECISIVE
    assert result.assurance_requirement.human_required


def _bridge_work_item(**overrides: object) -> WorkItemContract:
    values: dict[str, object] = {
        "schema_version": FOUNDRY_SCHEMA_VERSION,
        "id": "WI-BRIDGE-583",
        "title": "Compile a bounded capability change",
        "work_class": "capability",
        "objective": "Exercise the compiled toolkit bridge",
        "current_facts": ("synthetic repository",),
        "scope": ("src",),
        "out_of_scope": ("runtime",),
        "acceptance_criteria": ("deterministic validation",),
        "authority_class": ExternalEffectClass.REPOSITORY_WRITE,
        "consequence_class": ConsequenceClass.LOW,
        "required_evidence": ("deterministic-test",),
        "stop_conditions": ("compiled contract mismatch",),
    }
    values.update(overrides)
    return WorkItemContract(**values)


def _bridge_compilation(
    *, registry=None, **overrides: object
) -> RoleAssuranceCompilation:
    values: dict[str, object] = {
        "workflow_kind": "capability",
        "external_effect": ExternalEffectClass.REPOSITORY_WRITE,
        "consequence": ConsequenceClass.LOW,
        "required_evidence": (EvidenceClass.DETERMINISTIC_TEST,),
        "capability_declarations": tuple(
            CapabilityDeclaration(
                capability_id=capability_id,
                available=True,
                verified=True,
            )
            for capability_id in (
                "repository.read",
                "repository.write",
                "validation.test",
            )
        ),
    }
    values.update(overrides)
    return compile_role_assurance(
        _profile(),
        _operating_model(),
        WorkCharacteristics(**values),
        registry=registry,
    )


def _bridge_lock(*, include_reviewer: bool = True) -> ToolkitLock:
    return ToolkitLock(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        project_name="synthetic",
        capability_ids=[
            "repository.read",
            "repository.write",
            "validation.test",
            *( ["validation.review"] if include_reviewer else []),
        ],
        skill_ids=[
            "bounded-change",
            "deterministic-test",
            *( ["independent-review"] if include_reviewer else []),
        ],
        workflow_ids=["single-worker-validation"],
        role_ids=["builder", "validator", *( ["reviewer"] if include_reviewer else [])],
        permission_profile_ids=["repository-write-bounded"],
        budget_profile_ids=["default"],
    )


def test_compilation_bridge_refuses_unresolved_prerequisites():
    work_item = _bridge_work_item()
    compilation = _bridge_compilation(capability_declarations=())
    with pytest.raises(ToolkitResolutionError, match="prerequisites remain unresolved"):
        resolve_task_toolkit_for_compilation(
            work_item,
            _bridge_lock(),
            compilation,
            registry=build_default_registry(),
            permission_profiles=build_default_registry_permission_profiles(),
            budget_profiles=build_default_registry_budget_profiles(),
        )


def test_compilation_bridge_refuses_a_missing_compiled_reviewer():
    work_item = _bridge_work_item(consequence_class=ConsequenceClass.HIGH)
    compilation = _bridge_compilation(
        consequence=ConsequenceClass.HIGH,
        required_evidence=(EvidenceClass.DETERMINISTIC_TEST,),
        capability_declarations=tuple(
            CapabilityDeclaration(
                capability_id=capability_id,
                available=True,
                verified=True,
            )
            for capability_id in (
                "repository.read",
                "repository.write",
                "validation.test",
                "validation.review",
            )
        ),
    )
    with pytest.raises(ToolkitResolutionError, match="compiled roles.*reviewer"):
        resolve_task_toolkit_for_compilation(
            work_item,
            _bridge_lock(include_reviewer=False),
            compilation,
            registry=build_default_registry(),
            permission_profiles=build_default_registry_permission_profiles(),
            budget_profiles=build_default_registry_budget_profiles(),
        )


def test_compilation_bridge_rejects_mismatched_work_item_identity():
    work_item = _bridge_work_item()
    compilation = _bridge_compilation().model_copy(update={"work_item_id": "WI-OTHER"})
    with pytest.raises(ToolkitResolutionError, match="identity does not match"):
        resolve_task_toolkit_for_compilation(
            work_item,
            _bridge_lock(),
            compilation,
            registry=build_default_registry(),
            permission_profiles=build_default_registry_permission_profiles(),
            budget_profiles=build_default_registry_budget_profiles(),
        )


def test_explainability_requires_structured_input_predicates_for_inclusions_and_exclusions():
    result = _compile(_work(workflow_kind="plain-name"))
    report = validate_compilation_explainability(result)
    assert report.accepted(), report.findings
    for entry in result.explanation_trace:
        assert entry.causes
        assert all(
            isinstance(cause.locator, CompilationInputLocator)
            and isinstance(cause.locator.path, CompilationInputPath)
            and isinstance(cause.predicate, CompilationPredicate)
            and isinstance(cause.predicate.operator, CompilationPredicateOperator)
            and isinstance(cause.evaluated, bool)
            for cause in entry.causes
        )


def test_explainability_rejects_arbitrary_semantic_void_causes():
    result = _compile(_work(workflow_kind="plain-name"))
    arbitrary = "a cobalt lantern asserts an unrecorded prerequisite"
    forged_trace = tuple(
        entry.model_copy(
            update={
                "causes": (
                    CompilationCause(
                        locator=CompilationInputLocator(
                            path=CompilationInputPath.WORK_REQUIRED_CAPABILITIES,
                            item=arbitrary,
                        ),
                        predicate=CompilationPredicate(
                            operator=CompilationPredicateOperator.CONTAINS,
                            value=arbitrary,
                        ),
                        evaluated=False,
                        consequence=CompilationCauseConsequence.EXCLUDED,
                    ),
                )
            }
        )
        if entry.component == "capability" and entry.component_id == "repository.read"
        else entry
        for entry in result.explanation_trace
    )
    report = validate_compilation_explainability(
        result.model_copy(update={"explanation_trace": forged_trace})
    )
    assert not report.accepted()
    assert report.findings


def test_explainability_rejects_self_inconsistent_predicate_result():
    result = _compile(_work(workflow_kind="plain-name"))
    forged_trace = tuple(
        entry.model_copy(
            update={
                "causes": (
                    CompilationCause(
                        locator=CompilationInputLocator(
                            path=CompilationInputPath.WORK_RESERVED_AUTHORITY,
                        ),
                        predicate=CompilationPredicate(
                            operator=CompilationPredicateOperator.IS,
                            value=False,
                        ),
                        evaluated=False,
                        consequence=CompilationCauseConsequence.EXCLUDED,
                    ),
                )
            }
        )
        if entry.component == "role" and entry.component_id == "manager"
        else entry
        for entry in result.explanation_trace
    )
    report = validate_compilation_explainability(
        result.model_copy(update={"explanation_trace": forged_trace})
    )
    assert not report.accepted()
    assert any("recomputation" in finding for finding in report.findings)


def test_explainability_rejects_semantic_void_authority_trace_from_persisted_artifact():
    result = _compile(_work(workflow_kind="plain-name"))
    arbitrary = "a brass compass validates a silent boundary"
    payload = result.model_dump(mode="json")
    for entry in payload["explanation_trace"]:
        if entry["component"] == "authority-ceiling":
            entry["causes"] = [
                {
                    "locator": {
                        "path": CompilationInputPath.WORK_RESERVED_AUTHORITY.value,
                    },
                    "predicate": {
                        "operator": CompilationPredicateOperator.IS.value,
                        "value": arbitrary,
                    },
                    "evaluated": False,
                    "consequence": CompilationCauseConsequence.EXCLUDED.value,
                }
            ]
    forged = RoleAssuranceCompilation.model_validate(payload)
    report = validate_compilation_explainability(forged)
    assert not report.accepted()
    assert any("authority-ceiling" in finding for finding in report.findings)
    assert any("invalid predicate" in finding for finding in report.findings)


def test_explainability_rejects_trace_selection_contradicting_persisted_topology():
    result = _compile(_work(workflow_kind="plain-name"))
    payload = result.model_dump(mode="json")
    for entry in payload["explanation_trace"]:
        if entry["component"] == "role" and entry["component_id"] == "manager":
            entry["selected"] = True
            entry["causes"] = [
                {**cause, "consequence": CompilationCauseConsequence.SELECTED.value}
                for cause in entry["causes"]
            ]
    forged = RoleAssuranceCompilation.model_validate(payload)
    report = validate_compilation_explainability(forged)
    assert not report.accepted()
    assert any("canonical compilation state" in finding for finding in report.findings)
    assert any("records consequence" in finding for finding in report.findings)


@pytest.mark.parametrize("unknown_authority", tuple(ApprovalClass))
def test_missing_decision_rights_ceiling_returns_typed_refusal_and_escalation(
    unknown_authority: ApprovalClass,
):
    operating_model = _operating_model()
    rights = DecisionRights(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        authority_ceilings=tuple(
            ceiling
            for ceiling in operating_model.decision_rights.authority_ceilings
            if ceiling.consequence is not ConsequenceClass.HIGH
        ),
        unknown_authority=unknown_authority,
    )
    operating_model = operating_model.model_copy(update={"decision_rights": rights})

    result = compile_role_assurance(
        _profile(),
        operating_model,
        _work(consequence=ConsequenceClass.HIGH),
    )

    assert result.authority_ceiling.approval_class is ApprovalClass.REFUSED
    assert any(item.id == "authority-refused" for item in result.escalations)
    assert validate_compilation_explainability(result).accepted()


@pytest.mark.parametrize(
    ("field", "forged_value"),
    [
        ("approval_class", ApprovalClass.AUTOMATIC.value),
        ("max_external_effect", ExternalEffectClass.PUBLICATION.value),
        ("max_autonomy", Autonomy.CONTINUOUS_OPERATION.value),
    ],
)
def test_explainability_rejects_persisted_authority_dimension_relabel(field, forged_value):
    operating_model = _operating_model()
    rights = DecisionRights(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        authority_ceilings=tuple(
            ceiling
            for ceiling in operating_model.decision_rights.authority_ceilings
            if ceiling.consequence is not ConsequenceClass.HIGH
        ),
    )
    result = compile_role_assurance(
        _profile(),
        operating_model.model_copy(update={"decision_rights": rights}),
        _work(consequence=ConsequenceClass.HIGH),
    )
    payload = result.model_dump(mode="json")
    payload["authority_ceiling"][field] = forged_value

    forged = RoleAssuranceCompilation.model_validate(payload)
    report = validate_compilation_explainability(forged)

    assert not report.accepted()
    assert any(f"authority ceiling {field}" in finding for finding in report.findings)


def test_explainability_rejects_deleted_authority_refused_escalation():
    operating_model = _operating_model()
    rights = DecisionRights(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        authority_ceilings=tuple(
            ceiling
            for ceiling in operating_model.decision_rights.authority_ceilings
            if ceiling.consequence is not ConsequenceClass.HIGH
        ),
    )
    result = compile_role_assurance(
        _profile(),
        operating_model.model_copy(update={"decision_rights": rights}),
        _work(consequence=ConsequenceClass.HIGH),
    )
    payload = result.model_dump(mode="json")
    payload["escalations"] = [
        item for item in payload["escalations"] if item["id"] != "authority-refused"
    ]

    forged = RoleAssuranceCompilation.model_validate(payload)
    report = validate_compilation_explainability(forged)

    assert not report.accepted()
    assert any("authority-refused" in finding for finding in report.findings)


def test_explainability_rejects_capability_authorization_relabel_and_missing_prerequisite():
    result = _compile(
        _work(
            external_effect=ExternalEffectClass.READ_ONLY,
            required_capabilities=("repository.write",),
            capability_declarations=(
                CapabilityDeclaration(
                    capability_id="repository.write",
                    available=True,
                    verified=True,
                ),
            ),
        )
    )
    payload = result.model_dump(mode="json")
    requirement = next(
        item
        for item in payload["capability_requirements"]
        if item["capability_id"] == "repository.write"
    )
    requirement["authorized"] = True
    for entry in payload["explanation_trace"]:
        if entry["component"] == "capability" and entry["component_id"] == "repository.write":
            entry["selected"] = True
    payload["unresolved_prerequisites"] = [
        item
        for item in payload["unresolved_prerequisites"]
        if item["id"] != "capability-authority:repository.write"
    ]
    payload["escalations"] = [
        item
        for item in payload["escalations"]
        if item["id"] != "escalate:capability-authority:repository.write"
    ]

    forged = RoleAssuranceCompilation.model_validate(payload)
    report = validate_compilation_explainability(forged)

    assert not report.accepted()
    assert any(
        "capability 'repository.write' authorized" in finding
        for finding in report.findings
    )
    assert any(
        "missing unresolved prerequisite 'capability-authority:repository.write'" in finding
        for finding in report.findings
    )


def test_finished_task_rejects_permission_profile_above_effective_ceiling():
    work_item = _bridge_work_item(
        work_class="discovery",
        authority_class=ExternalEffectClass.READ_ONLY,
    )
    lock = _bridge_lock()
    read_only_ceiling = AuthorityCeiling(
        consequence=ConsequenceClass.LOW,
        max_external_effect=ExternalEffectClass.READ_ONLY,
        max_autonomy=Autonomy.SUGGEST,
        approval_class=ApprovalClass.AUTOMATIC,
    )
    task = resolve_task_toolkit_for_work_item(
        work_item,
        lock,
        registry=build_default_registry(),
        permission_profiles=build_default_registry_permission_profiles(),
        budget_profiles=build_default_registry_budget_profiles(),
        compiled_ceiling=read_only_ceiling,
    )
    assert task.permission_profile_ids == ["read-only"]
    forged = task.model_copy(
        update={"permission_profile_ids": ["repository-write-bounded"]}
    )

    with pytest.raises(ToolkitResolutionError, match="effective task ceiling"):
        validate_task_toolkit_against_ceiling(
            forged,
            lock,
            build_default_registry(),
            work_item,
            build_default_registry_permission_profiles(),
            compiled_ceiling=read_only_ceiling,
        )


def test_finished_task_accepts_permission_profile_at_effective_ceiling():
    work_item = _bridge_work_item(
        work_class="discovery",
        authority_class=ExternalEffectClass.READ_ONLY,
    )
    lock = _bridge_lock()
    read_only_ceiling = AuthorityCeiling(
        consequence=ConsequenceClass.LOW,
        max_external_effect=ExternalEffectClass.READ_ONLY,
        max_autonomy=Autonomy.SUGGEST,
        approval_class=ApprovalClass.AUTOMATIC,
    )
    task = resolve_task_toolkit_for_work_item(
        work_item,
        lock,
        registry=build_default_registry(),
        permission_profiles=build_default_registry_permission_profiles(),
        budget_profiles=build_default_registry_budget_profiles(),
        compiled_ceiling=read_only_ceiling,
    )

    validate_task_toolkit_against_ceiling(
        task,
        lock,
        build_default_registry(),
        work_item,
        build_default_registry_permission_profiles(),
        compiled_ceiling=read_only_ceiling,
    )
    assert task.permission_profile_ids == ["read-only"]


def _assert_duplicate_canonical_field_rejected(field_name: str) -> None:
    result = _compile(_work(workflow_kind="plain-name"))
    payload = result.model_dump(mode="json")
    seed = payload[field_name][0] if payload[field_name] else "synthetic-duplicate"
    payload[field_name] = [*payload[field_name], seed, seed]

    with pytest.raises(Exception, match=field_name):
        RoleAssuranceCompilation.model_validate(payload)


def test_role_assurance_compilation_rejects_duplicate_canonical_role_ids():
    _assert_duplicate_canonical_field_rejected("canonical_role_ids")


def test_role_assurance_compilation_rejects_duplicate_canonical_required_roles():
    _assert_duplicate_canonical_field_rejected("canonical_required_roles")


def test_role_assurance_compilation_rejects_duplicate_canonical_capability_ids():
    _assert_duplicate_canonical_field_rejected("canonical_capability_ids")


def test_explainability_rejects_persisted_role_identity_outside_canonical_input():
    result = _compile(_work(workflow_kind="plain-name"))
    shadow_role = "review6-shadow-role"
    payload = result.model_dump(mode="json")
    payload["topology"]["selected_roles"].append(shadow_role)
    payload["topology"]["required_roles"].append(shadow_role)
    shadow_cause = {
        "locator": {
            "path": CompilationInputPath.OPERATING_MODEL_REQUIRED_ROLES.value,
            "item": shadow_role,
        },
        "predicate": {
            "operator": CompilationPredicateOperator.CONTAINS.value,
            "value": shadow_role,
        },
        "evaluated": True,
        "consequence": CompilationCauseConsequence.SELECTED.value,
    }
    payload["role_decisions"].append(
        {
            "role_id": shadow_role,
            "selected": True,
            "rationale": "selected for the minimum logical responsibility topology",
            "causes": [shadow_cause],
            "policy_refs": [],
        }
    )
    payload["explanation_trace"].append(
        {
            "component": "role",
            "component_id": shadow_role,
            "selected": True,
            "rationale": "selected for the minimum logical responsibility topology",
            "causes": [shadow_cause],
            "policy_refs": [],
        }
    )

    forged = RoleAssuranceCompilation.model_validate(payload)
    report = validate_compilation_explainability(forged)

    assert not report.accepted()
    assert any("outside retained canonical role input" in finding for finding in report.findings)


def test_explainability_rejects_persisted_capability_identity_outside_canonical_input():
    result = _compile(_work(workflow_kind="plain-name"))
    shadow_capability = "review6.shadow-capability"
    payload = result.model_dump(mode="json")
    source_requirement = payload["capability_requirements"][0]
    forged_requirement = {**source_requirement, "capability_id": shadow_capability}
    payload["capability_requirements"].append(forged_requirement)
    source_trace = next(
        entry for entry in payload["explanation_trace"] if entry["component"] == "capability"
    )
    payload["explanation_trace"].append(
        {**source_trace, "component_id": shadow_capability}
    )

    forged = RoleAssuranceCompilation.model_validate(payload)
    report = validate_compilation_explainability(forged)

    assert not report.accepted()
    assert any(
        "outside retained canonical capability input" in finding
        for finding in report.findings
    )


def test_explainability_rejects_persisted_authority_consequence_relabel():
    result = _compile(_work(workflow_kind="plain-name"))
    payload = result.model_dump(mode="json")
    for entry in payload["explanation_trace"]:
        if entry["component"] == "authority-ceiling":
            entry["component_id"] = ConsequenceClass.HIGH.value
    payload["authority_ceiling"]["consequence"] = ConsequenceClass.HIGH.value

    forged = RoleAssuranceCompilation.model_validate(payload)
    report = validate_compilation_explainability(forged)

    assert not report.accepted()
    assert any("does not match canonical work consequence" in finding for finding in report.findings)


def test_explainability_rejects_decision_rights_schema_provenance_from_compilation_schema():
    result = _compile(_work(workflow_kind="plain-name"))
    forged_rights = result.decision_rights.model_copy(update={"schema_version": "0.9"})
    forged = result.model_copy(update={"decision_rights": forged_rights})

    report = validate_compilation_explainability(forged)

    assert not report.accepted()
    assert any("records predicate result" in finding for finding in report.findings)


def test_explainability_rejects_duplicate_and_unknown_persisted_material_entries():
    result = _compile(_work(workflow_kind="plain-name"))
    payload = result.model_dump(mode="json")
    duplicate = dict(payload["explanation_trace"][0])
    unknown = dict(duplicate)
    unknown["component"] = "unregistered-material"
    unknown["component_id"] = "synthetic"
    payload["explanation_trace"].extend((duplicate, unknown))
    forged = RoleAssuranceCompilation.model_validate(payload)
    report = validate_compilation_explainability(forged)
    assert not report.accepted()
    assert any("duplicate material trace entry" in finding for finding in report.findings)
    assert any("unknown material trace entry" in finding for finding in report.findings)


def test_compilation_bridge_rejects_role_outside_compiled_topology():
    base_registry = build_default_registry()
    altered_workflow = next(
        item for item in base_registry.workflows if item.id == "single-worker-validation"
    ).model_copy(update={"required_roles": ["builder", "validator", "manager"]})
    registry = base_registry.model_copy(
        update={
            "workflows": [
                altered_workflow
                if item.id == altered_workflow.id
                else item
                for item in base_registry.workflows
            ]
        }
    )
    compilation = _bridge_compilation(registry=registry)
    assert "manager" not in compilation.selected_roles
    assert "manager" in compilation.excluded_roles
    lock = _bridge_lock()
    lock = lock.model_copy(update={"role_ids": [*lock.role_ids, "manager"]})
    with pytest.raises(ToolkitResolutionError, match="outside compiled topology"):
        resolve_task_toolkit_for_compilation(
            _bridge_work_item(),
            lock,
            compilation,
            registry=registry,
            permission_profiles=build_default_registry_permission_profiles(),
            budget_profiles=build_default_registry_budget_profiles(),
        )


def test_compilation_bridge_rejects_required_role_outside_selected_roles():
    compilation = _bridge_compilation()
    forged_topology = compilation.topology.model_copy(
        update={
            "required_roles": ("manager",),
            "excluded_roles": tuple(
                role_id
                for role_id in compilation.topology.excluded_roles
                if role_id != "manager"
            ),
        }
    )
    forged_compilation = compilation.model_copy(update={"topology": forged_topology})
    payload = forged_compilation.model_dump()
    payload["topology"]["required_roles"] = ["manager"]
    with pytest.raises(Exception, match="required_roles.*subset"):
        RoleAssuranceCompilation.model_validate(payload)

    base_registry = build_default_registry()
    altered_workflow = next(
        item for item in base_registry.workflows if item.id == "single-worker-validation"
    ).model_copy(update={"required_roles": ["builder", "validator", "manager"]})
    registry = base_registry.model_copy(
        update={
            "workflows": [
                altered_workflow
                if item.id == altered_workflow.id
                else item
                for item in base_registry.workflows
            ]
        }
    )
    lock = _bridge_lock().model_copy(
        update={"role_ids": [*_bridge_lock().role_ids, "manager"]}
    )
    with pytest.raises(ToolkitResolutionError, match="required roles.*selected_roles"):
        resolve_task_toolkit_for_compilation(
            _bridge_work_item(),
            lock,
            forged_compilation,
            registry=registry,
            permission_profiles=build_default_registry_permission_profiles(),
            budget_profiles=build_default_registry_budget_profiles(),
        )


def test_role_assurance_compilation_rejects_schema_0_1():
    payload = _compile(_work()).model_dump()
    payload["schema_version"] = "0.1"
    with pytest.raises(Exception, match="introduced in schema_version"):
        RoleAssuranceCompilation.model_validate(payload)


def test_read_only_task_rejects_selected_role_write_scope_escape():
    base_registry = build_default_registry()
    escaped_role = RoleContract(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        id="scope-bearing-reader",
        version="1.0.0",
        description="Synthetic reader with an invalid write bound",
        allowed_capabilities=["repository.read"],
        write_scope=["../outside"],
    )
    inspection_skill = next(
        item for item in base_registry.skills if item.id == "repository-inspection"
    ).model_copy(
        update={"roles": SkillRoleConstraint(allowed=["scope-bearing-reader"])}
    )
    investigation_workflow = next(
        item for item in base_registry.workflows if item.id == "investigator-synthesis"
    ).model_copy(update={"required_roles": ["scope-bearing-reader"]})
    registry = base_registry.model_copy(
        update={
            "roles": [*base_registry.roles, escaped_role],
            "skills": [
                inspection_skill
                if item.id == "repository-inspection"
                else item
                for item in base_registry.skills
            ],
            "workflows": [
                investigation_workflow
                if item.id == "investigator-synthesis"
                else item
                for item in base_registry.workflows
            ],
        }
    )
    lock = ToolkitLock(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        project_name="synthetic",
        capability_ids=["repository.read", "inspection.read"],
        skill_ids=["repository-inspection"],
        workflow_ids=["investigator-synthesis"],
        role_ids=["scope-bearing-reader"],
        permission_profile_ids=["read-only"],
        budget_profile_ids=["default"],
    )
    work_item = _bridge_work_item(
        id="WI-READONLY-SCOPE",
        work_class="discovery",
        authority_class=ExternalEffectClass.READ_ONLY,
    )
    with pytest.raises(ToolkitResolutionError, match="unusable write scope"):
        resolve_task_toolkit_for_work_item(
            work_item,
            lock,
            registry=registry,
            permission_profiles=build_default_registry_permission_profiles(),
            budget_profiles=build_default_registry_budget_profiles(),
        )
