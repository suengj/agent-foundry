"""SUE-583 golden compilation and anti-vacuity tests."""

from __future__ import annotations

import pytest

from agent_foundry.compile import compile_role_assurance
from agent_foundry.models import (
    ApprovalClass,
    AssuranceMode,
    Autonomy,
    AuthorityCeiling,
    CapabilityDeclaration,
    ConsequenceClass,
    DecisionRights,
    ExternalEffectClass,
    FOUNDRY_SCHEMA_VERSION,
    OperatingConstraints,
    OperatingModel,
    ProjectProfile,
    RoleAssuranceCompilation,
    ToolkitLock,
    ToolkitResolutionError,
    WorkItemContract,
    WorkCharacteristics,
    dump_json,
    validate_compilation_explainability,
)
from agent_foundry.toolkit import resolve_task_toolkit_for_work_item
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
    )


def _work(**overrides: object) -> WorkCharacteristics:
    values: dict[str, object] = {
        "workflow_kind": "behaviour-preserving-refactor",
        "external_effect": ExternalEffectClass.REPOSITORY_WRITE,
        "consequence": ConsequenceClass.LOW,
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


def test_profile_subtracts_irrelevant_role_and_requires_declared_capability():
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
    result = compile_role_assurance(profile, _operating_model(), _work(consequence="low"))
    assert "reviewer" in result.excluded_roles
    assert any(item.id == "capability-availability:not-in-registry" for item in result.unresolved_prerequisites)
