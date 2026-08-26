"""Toolkit resolution Core API."""

from __future__ import annotations

from agent_foundry.models.integrations import IntegrationHealth, IntegrationSpec
from agent_foundry.models.policy import BudgetProfile, PermissionProfile
from agent_foundry.models.project import ProjectManifest
from agent_foundry.models.registry import CapabilityRegistry
from agent_foundry.models.toolkit import TaskToolkit, ToolkitLock, ToolkitResolution
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
    )


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
