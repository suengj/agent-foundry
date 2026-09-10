"""Toolkit resolution Core API."""

from __future__ import annotations

from agent_foundry.models.common import AssuranceMode, EvidenceClass
from agent_foundry.models.integrations import IntegrationHealth, IntegrationSpec
from agent_foundry.models.compiler import RoleAssuranceCompilation, WorkCharacteristics
from agent_foundry.models.policy import AuthorityCeiling, BudgetProfile, PermissionProfile
from agent_foundry.models.project import ProjectManifest
from agent_foundry.models.registry import CapabilityRegistry
from agent_foundry.models.toolkit import (
    TaskToolkit,
    ToolkitLock,
    ToolkitResolution,
    ToolkitResolutionError,
)
from agent_foundry.models.work import WorkItemContract
from agent_foundry.toolkit.builtin_registry import (
    build_default_registry,
    build_default_registry_budget_profiles,
    build_default_registry_permission_profiles,
)
from agent_foundry.toolkit.preflight import preflight_integrations
from agent_foundry.toolkit.resolve import (
    assert_component_schema_supported,
    resolve_project_toolkit,
    resolve_task_toolkit,
)


def resolve_toolkit(
    manifest: ProjectManifest,
    *,
    registry: CapabilityRegistry | None = None,
    integrations: list[IntegrationSpec] = [],
    integration_health: list[IntegrationHealth] = [],
    desired_integration_ids: list[str] = [],
    permission_profiles: list[PermissionProfile] | None = None,
    budget_profiles: list[BudgetProfile] | None = None,
) -> tuple[ToolkitResolution, ToolkitLock]:
    """Resolve Project Toolkit and version-pinned lock from manifest."""
    reg = registry or build_default_registry()
    assert_component_schema_supported(reg)
    profiles = (
        build_default_registry_permission_profiles()
        if permission_profiles is None
        else permission_profiles
    )
    budgets = (
        build_default_registry_budget_profiles()
        if budget_profiles is None
        else budget_profiles
    )
    return resolve_project_toolkit(
        manifest,
        reg,
        integrations=integrations,
        integration_health=integration_health,
        desired_integration_ids=desired_integration_ids,
        permission_profiles=profiles,
        budget_profiles=budgets,
    )


def resolve_task_toolkit_for_work_item(
    work_item: WorkItemContract,
    project_lock: ToolkitLock,
    *,
    registry: CapabilityRegistry | None = None,
    permission_profiles: list[PermissionProfile] | None = None,
    budget_profiles: list[BudgetProfile] | None = None,
    integrations: list[IntegrationSpec] = [],
    integration_health: list[IntegrationHealth] = [],
    compiled_ceiling: AuthorityCeiling | None = None,
) -> TaskToolkit:
    """Resolve minimum Task Toolkit for one Work Item."""
    reg = registry or build_default_registry()
    profiles = (
        build_default_registry_permission_profiles()
        if permission_profiles is None
        else permission_profiles
    )
    budgets = (
        build_default_registry_budget_profiles()
        if budget_profiles is None
        else budget_profiles
    )
    return resolve_task_toolkit(
        work_item,
        project_lock,
        reg,
        permission_profiles=profiles,
        budget_profiles=budgets,
        integrations=integrations,
        integration_health=integration_health,
        compiled_ceiling=compiled_ceiling,
    )


def resolve_task_toolkit_for_compilation(
    work_item: WorkItemContract,
    project_lock: ToolkitLock,
    compilation: RoleAssuranceCompilation,
    *,
    registry: CapabilityRegistry | None = None,
    permission_profiles: list[PermissionProfile] | None = None,
    budget_profiles: list[BudgetProfile] | None = None,
    integrations: list[IntegrationSpec] = [],
    integration_health: list[IntegrationHealth] = [],
) -> TaskToolkit:
    """Resolve a task toolkit while enforcing a SUE-583 compiled ceiling."""
    _validate_compilation_input(work_item, compilation)
    task = resolve_task_toolkit_for_work_item(
        work_item,
        project_lock,
        registry=registry,
        permission_profiles=permission_profiles,
        budget_profiles=budget_profiles,
        integrations=integrations,
        integration_health=integration_health,
        compiled_ceiling=compilation.authority_ceiling,
    )
    _validate_compiled_toolkit_contract(task, project_lock, compilation)
    return task


def _characteristics_for_work_item(work_item: WorkItemContract) -> WorkCharacteristics:
    evidence_values = set(work_item.required_evidence)
    return WorkCharacteristics(
        workflow_kind=work_item.work_class.value,
        external_effect=work_item.authority_class,
        consequence=work_item.consequence_class,
        required_evidence=tuple(
            item for item in EvidenceClass if item.value in evidence_values
        ),
        requires_sit=work_item.runtime_external_validation_requirement is not None,
        requires_runtime_readback=bool(
            evidence_values & {"runtime-readback", "integration-proof"}
        ),
    )


def _validate_compilation_input(
    work_item: WorkItemContract,
    compilation: RoleAssuranceCompilation,
) -> None:
    """Reject a toolkit request whose Work Item is not the compiled input."""

    if compilation.work_item_id is not None and compilation.work_item_id != work_item.id:
        raise ToolkitResolutionError(
            "compiled Work Item identity does not match the requested Work Item"
        )
    expected = _characteristics_for_work_item(work_item)
    actual = compilation.work
    mismatches = [
        field
        for field in (
            "workflow_kind",
            "external_effect",
            "consequence",
            "required_evidence",
            "requires_sit",
            "requires_runtime_readback",
        )
        if getattr(actual, field) != getattr(expected, field)
    ]
    if mismatches:
        raise ToolkitResolutionError(
            "compiled Work Item characteristics do not match: "
            + ", ".join(mismatches)
        )
    if compilation.unresolved_prerequisites:
        unresolved = ", ".join(item.id for item in compilation.unresolved_prerequisites)
        raise ToolkitResolutionError(
            f"compiled prerequisites remain unresolved: {unresolved}"
        )
    unready_capabilities = [
        item.capability_id
        for item in compilation.capability_requirements
        if item.available is not True or item.authorized is not True
    ]
    if unready_capabilities:
        raise ToolkitResolutionError(
            "compiled capabilities are not both available and authorized: "
            + ", ".join(sorted(unready_capabilities))
        )
    blocked = [
        item.id
        for item in compilation.escalations
        if item.id == "authority-refused" or item.id.startswith("escalate:")
    ]
    if blocked:
        raise ToolkitResolutionError(
            "compiled escalations block toolkit resolution: " + ", ".join(blocked)
        )


def _validate_compiled_toolkit_contract(
    task: TaskToolkit,
    project_lock: ToolkitLock,
    compilation: RoleAssuranceCompilation,
) -> None:
    """Enforce compiled topology, prerequisites, assurance, and gates at the bridge."""

    missing_roles = sorted(
        (
            set(compilation.topology.selected_roles)
            | set(compilation.topology.required_roles)
        )
        - set(task.role_ids)
    )
    if missing_roles:
        raise ToolkitResolutionError(
            "task toolkit is missing compiled roles: " + ", ".join(missing_roles)
        )

    required_capabilities = {
        item.capability_id for item in compilation.capability_requirements
    }
    missing_capabilities = sorted(required_capabilities - set(task.capability_ids))
    if missing_capabilities:
        raise ToolkitResolutionError(
            "task toolkit is missing compiled capabilities: "
            + ", ".join(missing_capabilities)
        )

    required_modes = set(compilation.assurance_requirement.required_modes)
    required_evidence = set(compilation.assurance_requirement.required_evidence)
    derived_gates: set[str] = set()
    if AssuranceMode.DETERMINISTIC_TESTS in required_modes or EvidenceClass.DETERMINISTIC_TEST in required_evidence:
        derived_gates.add("deterministic-validation")
    if compilation.assurance_requirement.independent_review or AssuranceMode.INDEPENDENT_REVIEW in required_modes or EvidenceClass.INDEPENDENT_REVIEW in required_evidence:
        derived_gates.add("independent-review")
    if AssuranceMode.RUNTIME_READBACK in required_modes or EvidenceClass.RUNTIME_READBACK in required_evidence:
        derived_gates.add("runtime-readback")
    if AssuranceMode.HUMAN_ACCEPTANCE in required_modes or EvidenceClass.HUMAN_ACCEPTANCE in required_evidence:
        derived_gates.add("human-acceptance")
    missing_declared_gates = sorted(derived_gates - set(compilation.required_gates))
    if missing_declared_gates:
        raise ToolkitResolutionError(
            "compiled assurance modes/evidence lack required gates: "
            + ", ".join(missing_declared_gates)
        )

    gate_skills = {
        "deterministic-validation": "deterministic-test",
        "independent-review": "independent-review",
    }
    known_gates = set(gate_skills) | {"runtime-readback", "sit", "human-acceptance"}
    unknown_gates = sorted(set(compilation.required_gates) - known_gates)
    if unknown_gates:
        raise ToolkitResolutionError(
            "compiled gates are not representable by Task Toolkit: "
            + ", ".join(unknown_gates)
        )
    for gate, skill_id in gate_skills.items():
        if gate in compilation.required_gates and skill_id not in task.skill_ids:
            raise ToolkitResolutionError(
                f"task toolkit is missing compiled gate {gate!r} skill {skill_id!r}"
            )
    if "independent-review" in compilation.required_gates and "reviewer" not in task.role_ids:
        raise ToolkitResolutionError(
            "task toolkit is missing reviewer for compiled independent-review gate"
        )
    if "runtime-readback" in compilation.required_gates or "sit" in compilation.required_gates:
        if "runtime-verifier" not in task.role_ids:
            raise ToolkitResolutionError(
                "task toolkit is missing runtime-verifier for compiled read-back gate"
            )
    if "human-acceptance" in compilation.required_gates:
        raise ToolkitResolutionError(
            "compiled human-acceptance gate requires an explicit human handoff"
        )

    if set(task.role_ids) - set(project_lock.role_ids):
        raise ToolkitResolutionError("task toolkit selected a role outside the project lock")


def check_integrations(
    integrations: list[IntegrationSpec],
    *,
    required_ids: list[str],
    observed_health: list[IntegrationHealth] = [],
) -> list[IntegrationHealth]:
    """Preflight integration health without exposing secret material."""
    return preflight_integrations(
        integrations,
        required_ids=required_ids,
        observed_health=observed_health,
    )


def default_registry() -> CapabilityRegistry:
    """Return the builtin capability registry."""
    return build_default_registry()
