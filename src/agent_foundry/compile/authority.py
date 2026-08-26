"""Compiled authority intersection — single chokepoint for AF6."""

from __future__ import annotations

from agent_foundry.models.common import ExternalEffectClass
from agent_foundry.models.execution import CompiledAuthority
from agent_foundry.models.policy import PermissionProfile
from agent_foundry.models.project import ProjectManifest
from agent_foundry.models.registry import CapabilityRegistry, RoleContract
from agent_foundry.models.toolkit import TaskToolkit
from agent_foundry.models.work import WorkItemContract
from agent_foundry.toolkit.ceiling import (
    EFFECT_RANK,
    capability_min_external_effect,
    effective_permission_ceiling,
    tighten_ceiling,
    unknown_external_effect,
)


class CompileAuthorityError(ValueError):
    """Raised when compiled authority cannot be determined or would widen bounds."""


def _role_max_external_effect(
    role: RoleContract | None,
    capabilities_by_id: dict[str, object],
) -> ExternalEffectClass:
    if role is None:
        return unknown_external_effect()
    if not role.allowed_capabilities:
        return ExternalEffectClass.READ_ONLY
    max_effect = ExternalEffectClass.READ_ONLY
    for capability_id in role.allowed_capabilities:
        effect = capability_min_external_effect(capability_id, capabilities_by_id)
        if EFFECT_RANK[effect] > EFFECT_RANK[max_effect]:
            max_effect = effect
    return max_effect


def _normalize_scope_path(scope: str) -> str | None:
    normalized = scope.strip()
    if not normalized or normalized == "/":
        return None
    trimmed = normalized.rstrip("/")
    return trimmed or None


def _is_scope_prefix(prefix: str, path: str) -> bool:
    return path == prefix or path.startswith(f"{prefix}/")


def _intersect_scope_paths(role_scope: str, work_item_scope: str) -> str | None:
    role_path = _normalize_scope_path(role_scope)
    work_path = _normalize_scope_path(work_item_scope)
    if role_path is None or work_path is None:
        return None
    if _is_scope_prefix(role_path, work_path):
        return work_path
    if _is_scope_prefix(work_path, role_path):
        return role_path
    return None


def _intersect_write_scopes(role_scopes: list[str], work_item_scopes: list[str]) -> list[str]:
    if not role_scopes:
        return []
    normalized_role = [
        path
        for path in (_normalize_scope_path(scope) for scope in role_scopes)
        if path is not None
    ]
    if not normalized_role:
        return []
    normalized_work = [
        path
        for path in (_normalize_scope_path(scope) for scope in work_item_scopes)
        if path is not None
    ]
    if not normalized_work:
        return []

    intersections: set[str] = set()
    for role_path in normalized_role:
        for work_path in normalized_work:
            overlap = _intersect_scope_paths(role_path, work_path)
            if overlap is not None:
                intersections.add(overlap)
    return sorted(intersections)


def _scope_contained_in_bounds(compiled_scope: str, bound_scopes: list[str]) -> bool:
    compiled_path = _normalize_scope_path(compiled_scope)
    if compiled_path is None:
        return False
    for bound_scope in bound_scopes:
        bound_path = _normalize_scope_path(bound_scope)
        if bound_path is None:
            continue
        if _is_scope_prefix(bound_path, compiled_path):
            return True
    return False


def _forbidden_scopes(role_scopes: list[str], compiled_write_scope: list[str]) -> list[str]:
    if not role_scopes:
        return []
    allowed = {scope.rstrip("/") for scope in compiled_write_scope}
    return sorted(
        scope
        for scope in role_scopes
        if scope.rstrip("/") not in allowed
    )


def compute_compiled_authority(
    work_item: WorkItemContract,
    manifest: ProjectManifest,
    task_toolkit: TaskToolkit,
    role: RoleContract | None,
    permission_profile: PermissionProfile | None,
    registry: CapabilityRegistry,
) -> CompiledAuthority:
    """Compute authority as intersection of work item, role, toolkit, and policy."""
    capabilities_by_id: dict[str, object] = {
        item.id: item for item in registry.capabilities
    }

    manifest_ceiling = effective_permission_ceiling(manifest)
    work_item_effect = work_item.authority_class

    if permission_profile is None:
        toolkit_effect = unknown_external_effect()
    else:
        toolkit_effect = permission_profile.external_effect

    role_effect = _role_max_external_effect(role, capabilities_by_id)

    compiled_effect = manifest_ceiling
    for bound in (work_item_effect, toolkit_effect, role_effect):
        compiled_effect = tighten_ceiling(compiled_effect, bound)

    role_write_scope = list(role.write_scope) if role is not None else []
    compiled_write_scope = _intersect_write_scopes(role_write_scope, work_item.scope)
    if compiled_effect == ExternalEffectClass.READ_ONLY:
        compiled_write_scope = []
    forbidden = _forbidden_scopes(role_write_scope, compiled_write_scope)

    return CompiledAuthority(
        external_effect=compiled_effect,
        write_scope=compiled_write_scope,
        forbidden_scopes=forbidden,
    )


def validate_execution_bundle_authority(
    authority: CompiledAuthority,
    work_item: WorkItemContract,
    manifest: ProjectManifest,
    task_toolkit: TaskToolkit,
    role: RoleContract | None,
    permission_profile: PermissionProfile | None,
    registry: CapabilityRegistry,
) -> None:
    """Validate finished bundle authority against every contributing bound."""
    expected = compute_compiled_authority(
        work_item,
        manifest,
        task_toolkit,
        role,
        permission_profile,
        registry,
    )
    if authority.external_effect != expected.external_effect:
        raise CompileAuthorityError(
            f"bundle authority {authority.external_effect.value} != "
            f"intersection {expected.external_effect.value}"
        )
    if authority.write_scope != expected.write_scope:
        raise CompileAuthorityError(
            f"bundle write_scope {authority.write_scope!r} != intersection {expected.write_scope!r}"
        )

    role_write_scope = list(role.write_scope) if role is not None else []
    for compiled_scope in authority.write_scope:
        if not _scope_contained_in_bounds(compiled_scope, work_item.scope):
            raise CompileAuthorityError(
                f"bundle write_scope {compiled_scope!r} is not contained in work item scope "
                f"{work_item.scope!r}"
            )
        if role_write_scope and not _scope_contained_in_bounds(compiled_scope, role_write_scope):
            raise CompileAuthorityError(
                f"bundle write_scope {compiled_scope!r} is not contained in role write_scope "
                f"{role_write_scope!r}"
            )

    manifest_ceiling = effective_permission_ceiling(manifest)
    if EFFECT_RANK[authority.external_effect] > EFFECT_RANK[manifest_ceiling]:
        raise CompileAuthorityError(
            f"bundle authority exceeds manifest ceiling {manifest_ceiling.value}"
        )
    if EFFECT_RANK[authority.external_effect] > EFFECT_RANK[work_item.authority_class]:
        raise CompileAuthorityError(
            f"bundle authority exceeds work item authority {work_item.authority_class.value}"
        )
    if permission_profile is not None:
        if EFFECT_RANK[authority.external_effect] > EFFECT_RANK[permission_profile.external_effect]:
            raise CompileAuthorityError(
                f"bundle authority exceeds task toolkit profile {permission_profile.external_effect.value}"
            )

    capabilities_by_id = {item.id: item for item in registry.capabilities}
    role_effect = _role_max_external_effect(role, capabilities_by_id)
    if EFFECT_RANK[authority.external_effect] > EFFECT_RANK[role_effect]:
        raise CompileAuthorityError(
            f"bundle authority exceeds role capability ceiling {role_effect.value}"
        )

    for capability_id in task_toolkit.capability_ids:
        min_effect = capability_min_external_effect(capability_id, capabilities_by_id)
        if EFFECT_RANK[min_effect] > EFFECT_RANK[authority.external_effect]:
            raise CompileAuthorityError(
                f"allowed capability {capability_id!r} min effect {min_effect.value} "
                f"exceeds compiled authority {authority.external_effect.value}"
            )
