"""Permission ceiling chokepoints — single source for effect rank and lock validation."""

from __future__ import annotations

from agent_foundry.models.common import ExternalEffectClass
from agent_foundry.models.integrations import IntegrationSpec
from agent_foundry.models.policy import PermissionProfile
from agent_foundry.models.project import ProjectManifest
from agent_foundry.models.registry import (
    CapabilityRegistry,
    CapabilitySpec,
    RoleContract,
    SkillSpec,
    WorkflowSpec,
)
from agent_foundry.models.toolkit import TaskToolkit, ToolkitLock, ToolkitResolutionError
from agent_foundry.models.work import WorkItemContract

UNKNOWN_EXTERNAL_EFFECT = ExternalEffectClass.PUBLICATION

EFFECT_RANK: dict[ExternalEffectClass, int] = {
    ExternalEffectClass.READ_ONLY: 0,
    ExternalEffectClass.REPOSITORY_WRITE: 1,
    ExternalEffectClass.SHARED_SERVICE_WRITE: 2,
    ExternalEffectClass.DATA_MUTATION: 3,
    ExternalEffectClass.RUNTIME_MUTATION: 4,
    ExternalEffectClass.PUBLICATION: 5,
}


def effective_permission_ceiling(manifest: ProjectManifest) -> ExternalEffectClass:
    """Compute the manifest reconciliation ceiling. All reconciliation uses this."""
    if manifest.impact.external_effect is not None:
        return manifest.impact.external_effect
    return ExternalEffectClass.READ_ONLY


def unknown_external_effect() -> ExternalEffectClass:
    """Fail-closed maximum for unknown ids, absent fields, missing specs, and None."""
    return UNKNOWN_EXTERNAL_EFFECT


def capability_min_external_effect(
    capability_id: str,
    capabilities_by_id: dict[str, object],
) -> ExternalEffectClass:
    """Minimum external effect for a capability — unknown paths return PUBLICATION."""
    spec = capabilities_by_id.get(capability_id)
    if isinstance(spec, CapabilitySpec):
        return spec.min_external_effect
    return unknown_external_effect()


def exceeds_permission_ceiling(
    effect: ExternalEffectClass,
    ceiling: ExternalEffectClass,
) -> bool:
    return EFFECT_RANK[effect] > EFFECT_RANK[ceiling]


def tighten_ceiling(
    ceiling: ExternalEffectClass,
    bound: ExternalEffectClass,
) -> ExternalEffectClass:
    if EFFECT_RANK[bound] < EFFECT_RANK[ceiling]:
        return bound
    return ceiling


def _index_registry(registry: CapabilityRegistry) -> dict[str, dict[str, object]]:
    return {
        "capabilities": {item.id: item for item in registry.capabilities},
        "skills": {item.id: item for item in registry.skills},
        "workflows": {item.id: item for item in registry.workflows},
        "roles": {item.id: item for item in registry.roles},
        "integrations": {item.id: item for item in registry.integrations},
    }


def validate_toolkit_lock_against_ceiling(
    lock: ToolkitLock,
    registry: CapabilityRegistry,
    ceiling: ExternalEffectClass,
    *,
    integrations: list[IntegrationSpec] = [],
) -> None:
    """Validate a finished project lock against the effective ceiling. Resolver bugs raise here."""
    index = _index_registry(registry)
    capabilities_by_id = index["capabilities"]
    skills_by_id = index["skills"]
    roles_by_id = index["roles"]
    workflows_by_id = index["workflows"]
    integration_specs = {spec.id: spec for spec in integrations}

    for capability_id in lock.capability_ids:
        min_effect = capability_min_external_effect(capability_id, capabilities_by_id)
        if exceeds_permission_ceiling(min_effect, ceiling):
            raise ToolkitResolutionError(
                f"lock capability {capability_id!r} min_external_effect {min_effect.value} "
                f"exceeds ceiling {ceiling.value}"
            )

    for skill_id in lock.skill_ids:
        skill = skills_by_id.get(skill_id)
        if not isinstance(skill, SkillSpec):
            raise ToolkitResolutionError(f"lock skill {skill_id!r} missing from registry")
        if skill.permissions.external_write and exceeds_permission_ceiling(
            ExternalEffectClass.REPOSITORY_WRITE,
            ceiling,
        ):
            raise ToolkitResolutionError(
                f"lock skill {skill_id!r} external_write exceeds ceiling {ceiling.value}"
            )
        missing_capabilities = sorted(
            capability_id
            for capability_id in skill.required_capabilities
            if capability_id not in lock.capability_ids
        )
        if missing_capabilities:
            raise ToolkitResolutionError(
                f"lock skill {skill_id!r} missing required capabilities: "
                f"{', '.join(missing_capabilities)}"
            )
        for capability_id in skill.required_capabilities:
            min_effect = capability_min_external_effect(capability_id, capabilities_by_id)
            if exceeds_permission_ceiling(min_effect, ceiling):
                raise ToolkitResolutionError(
                    f"lock skill {skill_id!r} requires capability {capability_id!r} "
                    f"with min_external_effect {min_effect.value} above ceiling {ceiling.value}"
                )

    for role_id in lock.role_ids:
        role = roles_by_id.get(role_id)
        if not isinstance(role, RoleContract):
            raise ToolkitResolutionError(f"lock role {role_id!r} missing from registry")
        for capability_id in role.allowed_capabilities:
            min_effect = capability_min_external_effect(capability_id, capabilities_by_id)
            if exceeds_permission_ceiling(min_effect, ceiling):
                raise ToolkitResolutionError(
                    f"lock role {role_id!r} allows capability {capability_id!r} "
                    f"with min_external_effect {min_effect.value} above ceiling {ceiling.value}"
                )

    for workflow_id in lock.workflow_ids:
        workflow = workflows_by_id.get(workflow_id)
        if not isinstance(workflow, WorkflowSpec):
            raise ToolkitResolutionError(f"lock workflow {workflow_id!r} missing from registry")
        missing_roles = sorted(set(workflow.required_roles) - set(lock.role_ids))
        if missing_roles:
            raise ToolkitResolutionError(
                f"lock workflow {workflow_id!r} missing required roles: {', '.join(missing_roles)}"
            )
        missing_skills = sorted(set(workflow.required_skills) - set(lock.skill_ids))
        if missing_skills:
            raise ToolkitResolutionError(
                f"lock workflow {workflow_id!r} missing required skills: "
                f"{', '.join(missing_skills)}"
            )

    for integration_id in lock.integration_ids:
        spec = integration_specs.get(integration_id)
        if spec is not None:
            for capability_id in spec.capabilities:
                min_effect = capability_min_external_effect(capability_id, capabilities_by_id)
                if exceeds_permission_ceiling(min_effect, ceiling):
                    raise ToolkitResolutionError(
                        f"lock integration {integration_id!r} capability {capability_id!r} "
                        f"with min_external_effect {min_effect.value} above ceiling {ceiling.value}"
                    )

    if lock.permission_external_effect is not None:
        if exceeds_permission_ceiling(lock.permission_external_effect, ceiling):
            raise ToolkitResolutionError(
                f"pinned permission profile effect {lock.permission_external_effect.value} "
                f"exceeds ceiling {ceiling.value}"
            )


def validate_task_toolkit_against_ceiling(
    task: TaskToolkit,
    project_lock: ToolkitLock,
    registry: CapabilityRegistry,
    work_item: WorkItemContract,
    permission_profiles: list[PermissionProfile],
) -> None:
    """Validate a finished task toolkit against pinned profile and work-item authority."""
    profile_by_id = {profile.id: profile for profile in permission_profiles}
    pinned_id = project_lock.permission_profile_ids[0]
    pinned_profile = profile_by_id.get(pinned_id)
    if pinned_profile is None:
        raise ToolkitResolutionError(f"pinned permission profile {pinned_id!r} not in profile set")

    task_profile_id = task.permission_profile_ids[0]
    task_profile = profile_by_id.get(task_profile_id)
    if task_profile is None:
        raise ToolkitResolutionError(f"task permission profile {task_profile_id!r} not in profile set")

    if exceeds_permission_ceiling(task_profile.external_effect, pinned_profile.external_effect):
        raise ToolkitResolutionError(
            f"task permission profile {task_profile_id!r} effect "
            f"{task_profile.external_effect.value} exceeds pinned profile effect "
            f"{pinned_profile.external_effect.value}"
        )

    ceiling = tighten_ceiling(work_item.authority_class, pinned_profile.external_effect)
    index = _index_registry(registry)
    capabilities_by_id = index["capabilities"]
    skills_by_id = index["skills"]

    for capability_id in task.capability_ids:
        if capability_id not in project_lock.capability_ids:
            raise ToolkitResolutionError(
                f"task capability {capability_id!r} not in project lock"
            )
        min_effect = capability_min_external_effect(capability_id, capabilities_by_id)
        if exceeds_permission_ceiling(min_effect, ceiling):
            raise ToolkitResolutionError(
                f"task capability {capability_id!r} min_external_effect {min_effect.value} "
                f"exceeds task ceiling {ceiling.value}"
            )

    for skill_id in task.skill_ids:
        if skill_id not in project_lock.skill_ids:
            raise ToolkitResolutionError(f"task skill {skill_id!r} not in project lock")
        skill = skills_by_id.get(skill_id)
        if isinstance(skill, SkillSpec) and skill.permissions.external_write:
            if exceeds_permission_ceiling(ExternalEffectClass.REPOSITORY_WRITE, ceiling):
                raise ToolkitResolutionError(
                    f"task skill {skill_id!r} external_write exceeds task ceiling {ceiling.value}"
                )

    if task.workflow_id is not None and task.workflow_id not in project_lock.workflow_ids:
        raise ToolkitResolutionError(
            f"task workflow {task.workflow_id!r} not in project lock"
        )
