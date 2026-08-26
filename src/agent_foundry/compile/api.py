"""Work Item compiler — Task Toolkit + ExecutionBundle with provenance."""

from __future__ import annotations

from agent_foundry.compile.authority import (
    CompileAuthorityError,
    compute_compiled_authority,
    validate_execution_bundle_authority,
)
from agent_foundry.compile.context import select_relevant_conventions, select_relevant_observations
from agent_foundry.models.base import FOUNDRY_SCHEMA_VERSION, FoundryModel
from agent_foundry.models.execution import (
    BundleProvenanceRecord,
    ExecutionBundle,
    SkillSummary,
)
from agent_foundry.models.integrations import IntegrationHealth, IntegrationSpec
from agent_foundry.models.policy import BudgetProfile, PermissionProfile
from agent_foundry.models.project import ConventionSpec, ProjectManifest, ProjectObservation
from agent_foundry.models.registry import CapabilityRegistry, RoleContract, SkillSpec
from agent_foundry.models.toolkit import ResolutionAction, ResolutionSource, TaskToolkit, ToolkitLock
from agent_foundry.models.work import WorkItemContract
from agent_foundry.toolkit import check_integrations, resolve_task_toolkit_for_work_item
from agent_foundry.toolkit.builtin_registry import (
    build_default_registry,
    build_default_registry_budget_profiles,
    build_default_registry_permission_profiles,
)
from agent_foundry.toolkit.ceiling import EFFECT_RANK, capability_min_external_effect


class CompileResult(FoundryModel):
    """Output of compiling one Work Item for a role."""

    task_toolkit: TaskToolkit
    bundle: ExecutionBundle


class CompileError(ValueError):
    """Raised when compilation cannot produce a valid bundle."""


def _lookup_role(role_id: str, registry: CapabilityRegistry) -> RoleContract | None:
    for role in registry.roles:
        if role.id == role_id:
            return role
    return None


def _lookup_permission_profile(
    profile_id: str,
    profiles: list[PermissionProfile],
) -> PermissionProfile | None:
    for profile in profiles:
        if profile.id == profile_id:
            return profile
    return None


def _lookup_budget_profile(
    profile_id: str,
    profiles: list[BudgetProfile],
) -> BudgetProfile | None:
    for profile in profiles:
        if profile.id == profile_id:
            return profile
    return None


def _skill_summaries(
    task_toolkit: TaskToolkit,
    registry: CapabilityRegistry,
    work_item: WorkItemContract,
) -> tuple[list[SkillSummary], list[BundleProvenanceRecord]]:
    skills_by_id = {skill.id: skill for skill in registry.skills}
    summaries: list[SkillSummary] = []
    provenance: list[BundleProvenanceRecord] = []

    for skill_id in sorted(task_toolkit.skill_ids):
        skill = skills_by_id.get(skill_id)
        if not isinstance(skill, SkillSpec):
            continue
        summaries.append(
            SkillSummary(
                skill_id=skill_id,
                description=skill.description,
                relevance=f"work_class={work_item.work_class.value}",
            )
        )
        provenance.append(
            BundleProvenanceRecord(
                component_kind="skill",
                component_id=skill_id,
                selected=True,
                rationale="skill included in task toolkit for work item class",
                source=ResolutionSource.WORK_ITEM,
                project_fact=f"work_item.work_class={work_item.work_class.value}",
            )
        )

    for skill in sorted(registry.skills, key=lambda item: item.id):
        if skill.id in task_toolkit.skill_ids:
            continue
        provenance.append(
            BundleProvenanceRecord(
                component_kind="skill",
                component_id=skill.id,
                selected=False,
                rationale="skill not selected in task toolkit",
                source=ResolutionSource.WORK_ITEM,
                project_fact=f"work_item.work_class={work_item.work_class.value}",
            )
        )
    return summaries, provenance


def _allowed_capabilities_for_role(
    task_toolkit: TaskToolkit,
    role: RoleContract | None,
    registry: CapabilityRegistry,
    compiled_authority_effect: object,
) -> tuple[list[str], list[str]]:
    capabilities_by_id = {item.id: item for item in registry.capabilities}
    role_allowed = set(role.allowed_capabilities) if role is not None else set(task_toolkit.capability_ids)
    selected = sorted(
        capability_id
        for capability_id in task_toolkit.capability_ids
        if capability_id in role_allowed
        and EFFECT_RANK[capability_min_external_effect(capability_id, capabilities_by_id)]
        <= EFFECT_RANK[compiled_authority_effect]
    )
    forbidden = sorted(set(task_toolkit.capability_ids) - set(selected))
    return selected, forbidden


def _policy_ids_from_decisions(task_toolkit: TaskToolkit) -> list[str]:
    return sorted(
        {
            decision.policy_id
            for decision in task_toolkit.decisions
            if decision.policy_id is not None
        }
    )


def _interaction_outputs(role_id: str, task_toolkit: TaskToolkit) -> list[str]:
    outputs = ["structured-handoff"]
    if "validator" in task_toolkit.role_ids or role_id == "validator":
        outputs.append("test-evidence")
    if "reviewer" in task_toolkit.role_ids or role_id == "reviewer":
        outputs.append("review-decision")
    if role_id == "builder":
        outputs.append("implementation-diff")
    return sorted(set(outputs))


def _role_compatible_with_task(
    role_id: str,
    task_toolkit: TaskToolkit,
    project_lock: ToolkitLock,
    registry: CapabilityRegistry,
) -> bool:
    if role_id not in project_lock.role_ids:
        return False
    if role_id in task_toolkit.role_ids:
        return True
    skills_by_id = {skill.id: skill for skill in registry.skills}
    for skill_id in task_toolkit.skill_ids:
        skill = skills_by_id.get(skill_id)
        if not isinstance(skill, SkillSpec):
            continue
        allowed = skill.roles.allowed
        if not allowed or role_id in allowed:
            return True
    return False


def compile_work_item(
    work_item: WorkItemContract,
    manifest: ProjectManifest,
    project_lock: ToolkitLock,
    role_id: str,
    run_id: str,
    *,
    registry: CapabilityRegistry | None = None,
    integrations: list[IntegrationSpec] | None = None,
    integration_health: list[IntegrationHealth] | None = None,
    observations: list[ProjectObservation] | None = None,
    conventions: list[ConventionSpec] | None = None,
    context_refs: list[str] | None = None,
    permission_profiles: list[PermissionProfile] | None = None,
    budget_profiles: list[BudgetProfile] | None = None,
) -> CompileResult:
    """Compile Task Toolkit and role-specific ExecutionBundle from inputs."""
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
    integration_list = integrations or []
    health_list = integration_health or []
    observation_list = observations if observations is not None else list(manifest.observations)
    convention_list = conventions or []
    context_ref_list = sorted(context_refs or [])

    task_toolkit = resolve_task_toolkit_for_work_item(
        work_item,
        project_lock,
        registry=reg,
        permission_profiles=profiles,
        budget_profiles=budgets,
    )

    if not _role_compatible_with_task(role_id, task_toolkit, project_lock, reg):
        raise CompileError(
            f"role {role_id!r} is not compatible with task toolkit "
            f"(project roles={project_lock.role_ids!r}, task roles={task_toolkit.role_ids!r})"
        )

    role = _lookup_role(role_id, reg)
    if role is None:
        raise CompileError(f"role {role_id!r} not in registry")

    task_profile_id = task_toolkit.permission_profile_ids[0]
    permission_profile = _lookup_permission_profile(task_profile_id, profiles)
    if permission_profile is None:
        raise CompileError(f"permission profile {task_profile_id!r} not found")

    compiled_authority = compute_compiled_authority(
        work_item,
        manifest,
        task_toolkit,
        role,
        permission_profile,
        reg,
    )

    budget_id = task_toolkit.budget_profile_ids[0]
    budget_profile = _lookup_budget_profile(budget_id, budgets)

    required_integration_ids = sorted(task_toolkit.integration_ids)
    check_integrations(
        integration_list,
        required_ids=required_integration_ids,
        observed_health=health_list,
    )

    selected_conventions, convention_provenance = select_relevant_conventions(
        work_item,
        convention_list,
    )
    selected_observations, observation_provenance = select_relevant_observations(
        work_item,
        observation_list,
    )
    skill_summaries, skill_provenance = _skill_summaries(task_toolkit, reg, work_item)

    allowed_capabilities, forbidden_capabilities = _allowed_capabilities_for_role(
        task_toolkit,
        role,
        reg,
        compiled_authority.external_effect,
    )

    toolkit_provenance: list[BundleProvenanceRecord] = []
    for decision in sorted(
        task_toolkit.decisions,
        key=lambda item: (item.component_kind, item.component_id, item.rationale),
    ):
        toolkit_provenance.append(
            BundleProvenanceRecord(
                component_kind=decision.component_kind,
                component_id=decision.component_id,
                selected=decision.action == ResolutionAction.INCLUDE,
                rationale=decision.rationale,
                source=decision.source,
                project_fact=decision.project_fact,
                policy_id=decision.policy_id,
            )
        )

    provenance = sorted(
        [
            *toolkit_provenance,
            *convention_provenance,
            *observation_provenance,
            *skill_provenance,
        ],
        key=lambda item: (
            item.component_kind,
            item.component_id,
            item.selected,
            item.rationale,
        ),
    )

    project_name = manifest.project.name or project_lock.project_name

    bundle = ExecutionBundle(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        work_item_id=work_item.id,
        run_id=run_id,
        role_id=role_id,
        project_name=project_name,
        objective=work_item.objective,
        scope=sorted(work_item.scope),
        out_of_scope=sorted(work_item.out_of_scope),
        acceptance_criteria=sorted(work_item.acceptance_criteria),
        allowed_capabilities=allowed_capabilities,
        forbidden_capabilities=forbidden_capabilities,
        write_scope=sorted(compiled_authority.write_scope),
        required_evidence=sorted(work_item.required_evidence),
        integration_ids=required_integration_ids,
        authority=compiled_authority,
        context_refs=context_ref_list,
        selected_conventions=sorted(item.subject for item in selected_conventions),
        selected_observations=sorted(item.subject for item in selected_observations),
        policy_ids=_policy_ids_from_decisions(task_toolkit),
        task_toolkit=task_toolkit,
        budget_profile_id=budget_id,
        max_retry_budget=budget_profile.max_retry_budget if budget_profile else None,
        max_parallel_runs=budget_profile.max_parallel_runs if budget_profile else None,
        validator_ids=sorted(task_toolkit.validator_ids),
        stop_conditions=sorted(work_item.stop_conditions),
        escalation_conditions=sorted(work_item.escalation_conditions),
        skill_summaries=skill_summaries,
        interaction_outputs=_interaction_outputs(role_id, task_toolkit),
        provenance=provenance,
    )

    validate_execution_bundle_authority(
        bundle.authority,
        work_item,
        manifest,
        task_toolkit,
        role,
        permission_profile,
        reg,
    )

    return CompileResult(task_toolkit=task_toolkit, bundle=bundle)


__all__ = [
    "CompileAuthorityError",
    "CompileError",
    "CompileResult",
    "compile_work_item",
    "compute_compiled_authority",
    "validate_execution_bundle_authority",
]
