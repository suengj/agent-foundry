"""Deterministic two-stage toolkit resolver."""

from __future__ import annotations

from agent_foundry.models.base import FOUNDRY_SCHEMA_VERSION, SchemaCompatibilityError
from agent_foundry.models.common import (
    AssuranceMode,
    AuthorityRequirement,
    ConsequenceClass,
    ExternalEffectClass,
    PrimaryArtifactState,
    PrimaryWorkMode,
    WorkClass,
)
from agent_foundry.models.integrations import IntegrationHealth, IntegrationSpec
from agent_foundry.models.policy import BudgetProfile, PermissionProfile, PolicyRule
from agent_foundry.models.project import ProjectManifest
from agent_foundry.models.registry import CapabilityRegistry
from agent_foundry.models.toolkit import (
    PolicyViolationError,
    ResolutionAction,
    ResolutionDecision,
    ResolutionSource,
    TaskToolkit,
    ToolkitLock,
    ToolkitResolution,
    ToolkitResolutionError,
)
from agent_foundry.models.work import WorkItemContract
from agent_foundry.toolkit.builtin_registry import (
    manifest_external_effect_allows_repository_write,
    manifest_requires_code_capabilities,
)
from agent_foundry.toolkit.compat import assert_registry_compat
from agent_foundry.toolkit.ceiling import (
    EFFECT_RANK,
    capability_min_external_effect,
    effective_permission_ceiling,
    exceeds_permission_ceiling,
    tighten_ceiling,
    unknown_external_effect,
    validate_task_toolkit_against_ceiling,
    validate_toolkit_lock_against_ceiling,
)
from agent_foundry.toolkit.preflight import meets_required_health, preflight_integrations

def _manifest_facts_unspecified(manifest: ProjectManifest) -> bool:
    artifact = manifest.project.primary_artifact
    primary_mode = (
        manifest.project.work_modes.primary if manifest.project.work_modes is not None else None
    )
    return (
        artifact is None
        and primary_mode is None
        and manifest.impact.external_effect is None
    )


def _lookup_permission_profile(
    profile_id: str,
    profiles: list[PermissionProfile],
) -> PermissionProfile:
    for profile in profiles:
        if profile.id == profile_id:
            return profile
    raise ToolkitResolutionError(
        f"permission profile {profile_id!r} not in supplied permission profiles"
    )


def _lookup_budget_profile(profile_id: str, profiles: list[BudgetProfile]) -> BudgetProfile:
    for profile in profiles:
        if profile.id == profile_id:
            return profile
    raise ToolkitResolutionError(
        f"budget profile {profile_id!r} not in supplied budget profiles"
    )


def _capability_exceeds_ceiling(
    capability_id: str,
    ceiling: ExternalEffectClass,
    capabilities: dict[str, object],
) -> bool:
    return exceeds_permission_ceiling(
        capability_min_external_effect(capability_id, capabilities),
        ceiling,
    )


def _select_validator_ids(manifest: ProjectManifest) -> set[str]:
    validator_ids: set[str] = {"schema-compat"}
    if manifest.assurance.required:
        validator_ids.add("evidence-contract")
    elif manifest.impact.consequence in {ConsequenceClass.HIGH, ConsequenceClass.CRITICAL}:
        validator_ids.add("evidence-contract")
    return validator_ids


def _retract_include(
    decisions: list[ResolutionDecision],
    component_kind: str,
    component_id: str,
) -> None:
    decisions[:] = [
        decision
        for decision in decisions
        if not (
            decision.action == ResolutionAction.INCLUDE
            and decision.component_kind == component_kind
            and decision.component_id == component_id
        )
    ]


def _retract_exclude(
    decisions: list[ResolutionDecision],
    component_kind: str,
    component_id: str,
) -> None:
    decisions[:] = [
        decision
        for decision in decisions
        if not (
            decision.action == ResolutionAction.EXCLUDE
            and decision.component_kind == component_kind
            and decision.component_id == component_id
        )
    ]


def _record_include(
    decisions: list[ResolutionDecision],
    component_kind: str,
    component_id: str,
    rationale: str,
    source: ResolutionSource,
    *,
    project_fact: str | None = None,
    policy_id: str | None = None,
) -> None:
    _retract_exclude(decisions, component_kind, component_id)
    if any(
        decision.action == ResolutionAction.INCLUDE
        and decision.component_kind == component_kind
        and decision.component_id == component_id
        for decision in decisions
    ):
        return
    decisions.append(
        _decision(
            ResolutionAction.INCLUDE,
            component_kind,
            component_id,
            rationale,
            source,
            project_fact=project_fact,
            policy_id=policy_id,
        )
    )


def _record_exclude(
    decisions: list[ResolutionDecision],
    component_kind: str,
    component_id: str,
    rationale: str,
    source: ResolutionSource,
    *,
    project_fact: str | None = None,
    policy_id: str | None = None,
) -> None:
    if any(
        decision.action == ResolutionAction.EXCLUDE
        and decision.component_kind == component_kind
        and decision.component_id == component_id
        for decision in decisions
    ):
        return
    _retract_include(decisions, component_kind, component_id)
    decisions.append(
        _decision(
            ResolutionAction.EXCLUDE,
            component_kind,
            component_id,
            rationale,
            source,
            project_fact=project_fact,
            policy_id=policy_id,
        )
    )


def _assert_policy_requirements_satisfied(
    policy_require: dict[str, set[str]],
    capabilities: set[str],
    skills: set[str],
    roles: set[str],
    workflows: set[str],
) -> None:
    missing_capabilities = sorted(policy_require["capabilities"] - capabilities)
    if missing_capabilities:
        raise PolicyViolationError(
            f"policy-required capabilities unsatisfiable: {', '.join(missing_capabilities)}"
        )
    missing_skills = sorted(policy_require["skills"] - skills)
    if missing_skills:
        raise PolicyViolationError(
            f"policy-required skills unsatisfiable: {', '.join(missing_skills)}"
        )
    missing_roles = sorted(policy_require["roles"] - roles)
    if missing_roles:
        raise PolicyViolationError(
            f"policy-required roles unsatisfiable: {', '.join(missing_roles)}"
        )
    missing_workflows = sorted(policy_require["workflows"] - workflows)
    if missing_workflows:
        raise PolicyViolationError(
            f"policy-required workflows unsatisfiable: {', '.join(missing_workflows)}"
        )


def _reconcile_with_permission_ceiling(
    manifest: ProjectManifest,
    capabilities: set[str],
    skills: set[str],
    roles: set[str],
    workflows: set[str],
    index: dict[str, dict[str, object]],
    decisions: list[ResolutionDecision],
) -> None:
    from agent_foundry.models.registry import RoleContract, SkillSpec, WorkflowSpec

    ceiling = effective_permission_ceiling(manifest)
    ceiling_fact = (
        f"impact.external_effect={ceiling.value}"
        if manifest.impact.external_effect is not None
        else "impact.external_effect unknown; read-only default"
    )
    skills_by_id = index["skills"]
    roles_by_id = index["roles"]
    capabilities_by_id = index["capabilities"]
    workflows_by_id = index["workflows"]

    for capability_id in sorted(capabilities):
        if _capability_exceeds_ceiling(capability_id, ceiling, capabilities_by_id):
            capabilities.discard(capability_id)
            _record_exclude(
                decisions,
                "capability",
                capability_id,
                f"exceeds declared external-effect ceiling {ceiling.value}",
                ResolutionSource.PROJECT_FACT,
                project_fact=ceiling_fact,
            )

    for skill_id in sorted(skills):
        skill = skills_by_id.get(skill_id)
        if not isinstance(skill, SkillSpec):
            continue
        exceeds = skill.permissions.external_write and exceeds_permission_ceiling(
            ExternalEffectClass.REPOSITORY_WRITE,
            ceiling,
        )
        if exceeds:
            skills.discard(skill_id)
            _record_exclude(
                decisions,
                "skill",
                skill_id,
                f"external_write skill exceeds declared external-effect ceiling {ceiling.value}",
                ResolutionSource.PROJECT_FACT,
                project_fact=ceiling_fact,
            )

    for skill_id in sorted(skills):
        skill = skills_by_id.get(skill_id)
        if not isinstance(skill, SkillSpec):
            continue
        missing_capabilities = sorted(
            capability_id
            for capability_id in skill.required_capabilities
            if capability_id not in capabilities
        )
        if missing_capabilities:
            skills.discard(skill_id)
            _record_exclude(
                decisions,
                "skill",
                skill_id,
                f"required capabilities absent after ceiling reconciliation: {', '.join(missing_capabilities)}",
                ResolutionSource.PROJECT_FACT,
                project_fact=ceiling_fact,
            )

    for role_id in sorted(roles):
        role = roles_by_id.get(role_id)
        if not isinstance(role, RoleContract):
            continue
        if any(
            _capability_exceeds_ceiling(cap, ceiling, capabilities_by_id)
            for cap in role.allowed_capabilities
        ):
            roles.discard(role_id)
            _record_exclude(
                decisions,
                "role",
                role_id,
                f"role capabilities exceed declared external-effect ceiling {ceiling.value}",
                ResolutionSource.PROJECT_FACT,
                project_fact=ceiling_fact,
            )

    for workflow_id in sorted(workflows):
        workflow = workflows_by_id.get(workflow_id)
        if not isinstance(workflow, WorkflowSpec):
            continue
        missing_roles = sorted(set(workflow.required_roles) - roles)
        missing_skills = sorted(set(workflow.required_skills) - skills)
        if missing_roles or missing_skills:
            workflows.discard(workflow_id)
            detail_parts: list[str] = []
            if missing_roles:
                detail_parts.append(f"missing roles: {', '.join(missing_roles)}")
            if missing_skills:
                detail_parts.append(f"missing skills: {', '.join(missing_skills)}")
            _record_exclude(
                decisions,
                "workflow",
                workflow_id,
                f"workflow requirements absent after ceiling reconciliation ({'; '.join(detail_parts)})",
                ResolutionSource.PROJECT_FACT,
                project_fact=ceiling_fact,
            )

    if not workflows:
        if not any(
            decision.action == ResolutionAction.EXCLUDE and decision.component_kind == "workflow"
            for decision in decisions
        ):
            decisions.append(
                _decision(
                    ResolutionAction.EXCLUDE,
                    "workflow",
                    "(none)",
                    "no workflow pinned after ceiling reconciliation",
                    ResolutionSource.PROJECT_FACT,
                    project_fact=ceiling_fact,
                )
            )


def _reconcile_integrations_against_ceiling(
    manifest: ProjectManifest,
    integration_ids: list[str],
    integrations: list[IntegrationSpec],
    index: dict[str, dict[str, object]],
    decisions: list[ResolutionDecision],
) -> list[str]:
    ceiling = effective_permission_ceiling(manifest)
    ceiling_fact = (
        f"impact.external_effect={ceiling.value}"
        if manifest.impact.external_effect is not None
        else "impact.external_effect unknown; read-only default"
    )
    capabilities_by_id = index["capabilities"]
    specs_by_id = {spec.id: spec for spec in integrations}
    retained: list[str] = []

    for integration_id in integration_ids:
        spec = specs_by_id.get(integration_id)
        if spec is None:
            # An undeclared integration has unknown capabilities. Retaining it would let
            # the absence of an IntegrationSpec grant more than supplying one does, so the
            # unknown set is treated as the fail-closed maximum and excluded.
            _record_exclude(
                decisions,
                "integration",
                integration_id,
                (
                    "no IntegrationSpec declared; capabilities unknown and treated as "
                    f"{unknown_external_effect().value}, which exceeds ceiling {ceiling.value}"
                ),
                ResolutionSource.PROJECT_FACT,
                project_fact=ceiling_fact,
            )
            continue
        exceeded = any(
            _capability_exceeds_ceiling(capability_id, ceiling, capabilities_by_id)
            for capability_id in spec.capabilities
        )
        if exceeded:
            _record_exclude(
                decisions,
                "integration",
                integration_id,
                f"integration capabilities exceed declared external-effect ceiling {ceiling.value}",
                ResolutionSource.PROJECT_FACT,
                project_fact=ceiling_fact,
            )
            continue
        retained.append(integration_id)

    return retained


def _scrub_include_decisions_not_in_lock(
    decisions: list[ResolutionDecision],
    capabilities: set[str],
    skills: set[str],
    roles: set[str],
    workflows: set[str],
    integration_ids: list[str],
    validator_ids: set[str],
    permission_profile_id: str,
    budget_profile_id: str,
) -> None:
    in_lock = {
        *(("capability", capability_id) for capability_id in capabilities),
        *(("skill", skill_id) for skill_id in skills),
        *(("role", role_id) for role_id in roles),
        *(("workflow", workflow_id) for workflow_id in workflows),
        *(("integration", integration_id) for integration_id in integration_ids),
        *(("validator", validator_id) for validator_id in validator_ids),
        ("permission-profile", permission_profile_id),
        ("budget-profile", budget_profile_id),
    }
    decisions[:] = [
        decision
        for decision in decisions
        if decision.action != ResolutionAction.INCLUDE
        or (decision.component_kind, decision.component_id) in in_lock
    ]


def _sorted_ids(items: list[str]) -> list[str]:
    return sorted(set(items))


def _decision(
    action: ResolutionAction,
    kind: str,
    component_id: str,
    rationale: str,
    source: ResolutionSource,
    *,
    project_fact: str | None = None,
    policy_id: str | None = None,
) -> ResolutionDecision:
    return ResolutionDecision(
        action=action,
        component_kind=kind,
        component_id=component_id,
        rationale=rationale,
        source=source,
        project_fact=project_fact,
        policy_id=policy_id,
    )


def _policy_matches(manifest: ProjectManifest, rule: PolicyRule) -> bool:
    when = rule.when
    # Consequence is not substituted when unknown: fail-closed substitute would be CRITICAL,
    # which would over-provision or refuse every under-specified project.
    if when.consequence is not None:
        if manifest.impact.consequence != when.consequence:
            return False
    declared_effect = manifest.impact.external_effect
    if declared_effect is None:
        declared_effect = effective_permission_ceiling(manifest)
    if when.external_effect is not None:
        if declared_effect != when.external_effect:
            return False
    if when.authority_class is not None:
        if declared_effect != when.authority_class:
            return False
    if when.assurance is not None:
        required_mode = AssuranceMode(when.assurance)
        if required_mode not in manifest.assurance.required:
            return False
    return True


def _collect_policy_constraints(
    manifest: ProjectManifest,
    policy_rules: list[PolicyRule],
) -> tuple[dict[str, set[str]], dict[str, set[str]], list[ResolutionDecision]]:
    require: dict[str, set[str]] = {
        "capabilities": set(),
        "skills": set(),
        "workflows": set(),
        "roles": set(),
    }
    forbid: dict[str, set[str]] = {
        "capabilities": set(),
        "skills": set(),
        "workflows": set(),
        "roles": set(),
        "permission_profiles": set(),
    }
    decisions: list[ResolutionDecision] = []

    for rule in sorted(policy_rules, key=lambda item: item.id):
        if not _policy_matches(manifest, rule):
            continue
        for cap in rule.require_capabilities:
            require["capabilities"].add(cap)
            _record_include(
                decisions,
                "capability",
                cap,
                f"policy {rule.id} requires capability",
                ResolutionSource.POLICY,
                policy_id=rule.id,
            )
        for skill in rule.require_skills:
            require["skills"].add(skill)
            _record_include(
                decisions,
                "skill",
                skill,
                f"policy {rule.id} requires skill",
                ResolutionSource.POLICY,
                policy_id=rule.id,
            )
        for workflow in rule.require_workflows:
            require["workflows"].add(workflow)
            _record_include(
                decisions,
                "workflow",
                workflow,
                f"policy {rule.id} requires workflow",
                ResolutionSource.POLICY,
                policy_id=rule.id,
            )
        for role in rule.require_roles:
            require["roles"].add(role)
            _record_include(
                decisions,
                "role",
                role,
                f"policy {rule.id} requires role",
                ResolutionSource.POLICY,
                policy_id=rule.id,
            )
        for cap in rule.forbid_capabilities:
            forbid["capabilities"].add(cap)
        for skill in rule.forbid_skills:
            forbid["skills"].add(skill)
        for workflow in rule.forbid_workflows:
            forbid["workflows"].add(workflow)
        for role in rule.forbid_roles:
            forbid["roles"].add(role)
        for profile in rule.forbid_permission_profiles:
            forbid["permission_profiles"].add(profile)

    return forbid, require, decisions


def _manifest_fact_requirements(
    manifest: ProjectManifest,
) -> tuple[dict[str, set[str]], list[ResolutionDecision]]:
    require: dict[str, set[str]] = {
        "capabilities": set(),
        "skills": set(),
        "workflows": set(),
        "roles": set(),
    }
    decisions: list[ResolutionDecision] = []

    artifact = manifest.project.primary_artifact
    primary_mode = (
        manifest.project.work_modes.primary if manifest.project.work_modes is not None else None
    )
    external_effect = manifest.impact.external_effect
    code_signal = (
        artifact == PrimaryArtifactState.CODE or primary_mode == PrimaryWorkMode.BUILD
    )

    if code_signal:
        require["capabilities"].add("repository.read")
        _record_include(
            decisions,
            "capability",
            "repository.read",
            "code-centric project requires repository read",
            ResolutionSource.PROJECT_FACT,
            project_fact="project.primary_artifact=code or work_modes.primary=build",
        )
        require["skills"].add("repository-inspection")
        require["roles"].add("explorer")
        _record_include(
            decisions,
            "skill",
            "repository-inspection",
            "code-centric project requires read-only inspection baseline",
            ResolutionSource.PROJECT_FACT,
            project_fact="project.primary_artifact=code or work_modes.primary=build",
        )
        _record_include(
            decisions,
            "role",
            "explorer",
            "code-centric project requires explorer for inspection baseline",
            ResolutionSource.PROJECT_FACT,
            project_fact="project.primary_artifact=code or work_modes.primary=build",
        )
        if external_effect is None:
            _record_exclude(
                decisions,
                "skill",
                "bounded-change",
                "impact.external_effect is unknown; cannot authorize write skill",
                ResolutionSource.PROJECT_FACT,
                project_fact="impact.external_effect is unknown",
            )
            _record_exclude(
                decisions,
                "role",
                "builder",
                "impact.external_effect is unknown; cannot authorize builder role",
                ResolutionSource.PROJECT_FACT,
                project_fact="impact.external_effect is unknown",
            )
        elif manifest_external_effect_allows_repository_write(manifest):
            require["skills"].add("bounded-change")
            require["roles"].add("builder")
            _record_include(
                decisions,
                "skill",
                "bounded-change",
                "code-centric project with repository-write authority requires bounded change",
                ResolutionSource.PROJECT_FACT,
                project_fact=f"impact.external_effect={external_effect.value}",
            )
            _record_include(
                decisions,
                "role",
                "builder",
                "code-centric project with repository-write authority requires builder role",
                ResolutionSource.PROJECT_FACT,
                project_fact=f"impact.external_effect={external_effect.value}",
            )
        else:
            _record_exclude(
                decisions,
                "skill",
                "bounded-change",
                "repository write exceeds declared external effect ceiling",
                ResolutionSource.PROJECT_FACT,
                project_fact=f"impact.external_effect={external_effect.value}",
            )
            _record_exclude(
                decisions,
                "role",
                "builder",
                "builder role exceeds declared external effect ceiling",
                ResolutionSource.PROJECT_FACT,
                project_fact=f"impact.external_effect={external_effect.value}",
            )
    else:
        if artifact is None:
            _record_exclude(
                decisions,
                "capability",
                "repository.read",
                "project.primary_artifact is unknown",
                ResolutionSource.PROJECT_FACT,
                project_fact="project.primary_artifact is unknown",
            )
        if primary_mode is None:
            _record_exclude(
                decisions,
                "skill",
                "bounded-change",
                "project.work_modes.primary is unknown",
                ResolutionSource.PROJECT_FACT,
                project_fact="project.work_modes.primary is unknown",
            )
            _record_exclude(
                decisions,
                "role",
                "builder",
                "project.work_modes.primary is unknown",
                ResolutionSource.PROJECT_FACT,
                project_fact="project.work_modes.primary is unknown",
            )

    if primary_mode == PrimaryWorkMode.ANALYZE:
        require["skills"].add("repository-inspection")
        require["roles"].add("explorer")
        _record_include(
            decisions,
            "skill",
            "repository-inspection",
            "analyze work mode requires inspection skill",
            ResolutionSource.PROJECT_FACT,
            project_fact="project.work_modes.primary=analyze",
        )
        _record_include(
            decisions,
            "role",
            "explorer",
            "analyze work mode requires explorer role",
            ResolutionSource.PROJECT_FACT,
            project_fact="project.work_modes.primary=analyze",
        )
    elif primary_mode is None:
        _record_exclude(
            decisions,
            "skill",
            "repository-inspection",
            "project.work_modes.primary is unknown",
            ResolutionSource.PROJECT_FACT,
            project_fact="project.work_modes.primary is unknown",
        )

    return require, decisions


def _policy_requirement_signature(rule: PolicyRule) -> tuple:
    return (
        rule.when.consequence,
        rule.when.assurance,
        tuple(sorted(rule.require_capabilities)),
        tuple(sorted(rule.require_skills)),
        tuple(sorted(rule.require_roles)),
    )


def _validate_policy_effect_coverage(
    policy_rules: list[PolicyRule],
    *,
    contract_name: str = "CapabilityRegistry",
) -> None:
    covered_signatures: set[tuple] = set()
    for rule in policy_rules:
        if not any(
            [
                rule.require_capabilities,
                rule.require_skills,
                rule.require_workflows,
                rule.require_roles,
            ]
        ):
            continue
        if rule.when.external_effect is None or rule.when.external_effect == ExternalEffectClass.READ_ONLY:
            covered_signatures.add(_policy_requirement_signature(rule))

    for rule in policy_rules:
        effect = rule.when.external_effect
        if effect is None or effect == ExternalEffectClass.READ_ONLY:
            continue
        if not any(
            [
                rule.require_capabilities,
                rule.require_skills,
                rule.require_workflows,
                rule.require_roles,
            ]
        ):
            continue
        signature = _policy_requirement_signature(rule)
        if signature not in covered_signatures:
            raise ToolkitResolutionError(
                f"{contract_name}: policy rule {rule.id!r} lacks read-only or "
                f"effect-agnostic sibling for requirements {signature}"
            )


def _validate_registry_ids(
    registry: CapabilityRegistry,
    *,
    contract_name: str = "CapabilityRegistry",
) -> None:
    for collection_name, items in (
        ("capabilities", registry.capabilities),
        ("skills", registry.skills),
        ("workflows", registry.workflows),
        ("roles", registry.roles),
        ("validators", registry.validators),
    ):
        ids = [item.id for item in items]
        if len(ids) != len(set(ids)):
            raise ToolkitResolutionError(f"{contract_name}: duplicate ids in {collection_name}")


def _index_registry(registry: CapabilityRegistry) -> dict[str, dict[str, object]]:
    return {
        "capabilities": {item.id: item for item in registry.capabilities},
        "skills": {item.id: item for item in registry.skills},
        "workflows": {item.id: item for item in registry.workflows},
        "roles": {item.id: item for item in registry.roles},
        "validators": {item.id: item for item in registry.validators},
        "integrations": {item.id: item for item in registry.integrations},
    }


def _assert_present(kind: str, required: set[str], available: dict[str, object]) -> None:
    missing = sorted(required - set(available.keys()))
    if missing:
        raise ToolkitResolutionError(
            f"missing mandatory {kind}: {', '.join(missing)}"
        )


def _assert_not_forbidden(
    kind: str,
    selected: set[str],
    forbidden: set[str],
) -> None:
    blocked = sorted(selected & forbidden)
    if blocked:
        raise PolicyViolationError(
            f"forbidden {kind}: {', '.join(blocked)}"
        )


def _expand_skill_capabilities(
    skill_ids: set[str],
    skills: dict[str, object],
    capabilities: set[str],
    decisions: list[ResolutionDecision],
) -> None:
    from agent_foundry.models.registry import SkillSpec

    for skill_id in sorted(skill_ids):
        skill = skills.get(skill_id)
        if not isinstance(skill, SkillSpec):
            continue
        for cap in skill.required_capabilities:
            if cap not in capabilities:
                capabilities.add(cap)
                _record_include(
                    decisions,
                    "capability",
                    cap,
                    f"required by skill {skill_id}",
                    ResolutionSource.REGISTRY,
                )


def _expand_workflow_requirements(
    workflow_ids: set[str],
    workflows: dict[str, object],
    skills: set[str],
    roles: set[str],
    decisions: list[ResolutionDecision],
) -> None:
    from agent_foundry.models.registry import WorkflowSpec

    for workflow_id in sorted(workflow_ids):
        workflow = workflows.get(workflow_id)
        if not isinstance(workflow, WorkflowSpec):
            continue
        for skill_id in workflow.required_skills:
            if skill_id not in skills:
                skills.add(skill_id)
                _record_include(
                    decisions,
                    "skill",
                    skill_id,
                    f"required by workflow {workflow_id}",
                    ResolutionSource.REGISTRY,
                )
        for role_id in workflow.required_roles:
            if role_id not in roles:
                roles.add(role_id)
                _record_include(
                    decisions,
                    "role",
                    role_id,
                    f"required by workflow {workflow_id}",
                    ResolutionSource.REGISTRY,
                )


def _select_permission_profile(
    manifest: ProjectManifest,
    profiles: list[PermissionProfile],
    forbidden_profiles: set[str],
) -> PermissionProfile:
    effect = effective_permission_ceiling(manifest)

    allowed = [profile for profile in profiles if profile.id not in forbidden_profiles]
    if not allowed:
        raise PolicyViolationError("no permission profile allowed after policy filtering")

    candidates = [
        profile
        for profile in allowed
        if EFFECT_RANK[profile.external_effect] <= EFFECT_RANK[effect]
    ]
    if not candidates:
        raise PolicyViolationError(
            f"no permission profile within project external effect {effect.value}"
        )
    return max(candidates, key=lambda profile: (EFFECT_RANK[profile.external_effect], profile.id))


def _select_budget_profile(manifest: ProjectManifest, profiles: list[BudgetProfile]) -> BudgetProfile:
    if manifest.impact.consequence in {ConsequenceClass.HIGH, ConsequenceClass.CRITICAL}:
        tight = next((p for p in profiles if p.id == "tight-validation"), None)
        if tight is not None:
            return tight
    return next((p for p in profiles if p.id == "default"), profiles[0])


def _permission_profile_for_effect(
    effect: ExternalEffectClass,
    profiles: list[PermissionProfile],
) -> PermissionProfile:
    candidates = [
        profile
        for profile in profiles
        if EFFECT_RANK[profile.external_effect] <= EFFECT_RANK[effect]
    ]
    if not candidates:
        raise PolicyViolationError(
            f"no permission profile within authority {effect.value}"
        )
    return max(candidates, key=lambda profile: (EFFECT_RANK[profile.external_effect], profile.id))


def _assert_no_permission_escalation(
    manifest: ProjectManifest,
    profile: PermissionProfile,
) -> None:
    effect = effective_permission_ceiling(manifest)
    if EFFECT_RANK[profile.external_effect] > EFFECT_RANK[effect]:
        raise PolicyViolationError(
            f"permission escalation: profile {profile.id} allows "
            f"{profile.external_effect.value} but project impact is {effect.value}"
        )


def resolve_project_toolkit(
    manifest: ProjectManifest,
    registry: CapabilityRegistry,
    *,
    integrations: list[IntegrationSpec] = [],
    integration_health: list[IntegrationHealth] = [],
    desired_integration_ids: list[str] = [],
    permission_profiles: list[PermissionProfile] = [],
    budget_profiles: list[BudgetProfile] = [],
) -> tuple[ToolkitResolution, ToolkitLock]:
    """Resolve a version-pinned Project Toolkit lock from manifest and registry."""
    assert_registry_compat(registry.foundry_compat)
    _validate_registry_ids(registry)
    _validate_policy_effect_coverage(registry.policy_rules)

    index = _index_registry(registry)
    forbid, policy_require, policy_decisions = _collect_policy_constraints(
        manifest, registry.policy_rules
    )
    manifest_require, manifest_decisions = _manifest_fact_requirements(manifest)

    capabilities: set[str] = set()
    capabilities.update(policy_require["capabilities"])
    capabilities.update(manifest_require["capabilities"])
    skills: set[str] = set()
    skills.update(policy_require["skills"])
    skills.update(manifest_require["skills"])
    workflows: set[str] = set(policy_require["workflows"])
    roles: set[str] = set()
    roles.update(policy_require["roles"])
    roles.update(manifest_require["roles"])

    decisions = sorted(
        [*policy_decisions, *manifest_decisions],
        key=lambda item: (item.component_kind, item.component_id, item.rationale),
    )

    _assert_present("capability", capabilities, index["capabilities"])
    _assert_present("skill", skills, index["skills"])
    if workflows:
        _assert_present("workflow", workflows, index["workflows"])
    _assert_present("role", roles, index["roles"])

    _assert_not_forbidden("capability", capabilities, forbid["capabilities"])
    _assert_not_forbidden("skill", skills, forbid["skills"])
    _assert_not_forbidden("workflow", workflows, forbid["workflows"])
    _assert_not_forbidden("role", roles, forbid["roles"])

    _expand_workflow_requirements(workflows, index["workflows"], skills, roles, decisions)
    _expand_skill_capabilities(skills, index["skills"], capabilities, decisions)

    if not permission_profiles:
        raise ToolkitResolutionError("permission profiles required for resolution")
    if not budget_profiles:
        raise ToolkitResolutionError("budget profiles required for resolution")

    permission_profile = _select_permission_profile(manifest, permission_profiles, forbid["permission_profiles"])
    _assert_no_permission_escalation(manifest, permission_profile)
    declared_effect = effective_permission_ceiling(manifest)
    _reconcile_with_permission_ceiling(
        manifest,
        capabilities,
        skills,
        roles,
        workflows,
        index,
        decisions,
    )
    _assert_policy_requirements_satisfied(
        policy_require,
        capabilities,
        skills,
        roles,
        workflows,
    )

    if skills:
        _assert_present("skill", skills, index["skills"])
    if roles:
        _assert_present("role", roles, index["roles"])
    if capabilities:
        _assert_present("capability", capabilities, index["capabilities"])

    validator_ids = _select_validator_ids(manifest)
    # A validator id is pinned only when the registry actually carries the validator.
    # Without this, a registry with `validators: []` still pins names nothing can run.
    _assert_present("validator", validator_ids, index["validators"])
    decisions.append(
        _decision(
            ResolutionAction.INCLUDE,
            "validator",
            "schema-compat",
            "baseline schema contract validation",
            ResolutionSource.REGISTRY,
        )
    )
    if "evidence-contract" in validator_ids:
        decisions.append(
            _decision(
                ResolutionAction.INCLUDE,
                "validator",
                "evidence-contract",
                "validator required by assurance or consequence policy",
                ResolutionSource.PROJECT_FACT,
                project_fact=(
                    "assurance.required"
                    if manifest.assurance.required
                    else f"impact.consequence={manifest.impact.consequence.value}"
                ),
            )
        )

    budget_profile = _select_budget_profile(manifest, budget_profiles)

    if desired_integration_ids:
        integration_ids = _sorted_ids(desired_integration_ids)
        integration_include_rationale = "explicitly requested integration"
    elif _manifest_facts_unspecified(manifest):
        integration_ids = []
        _record_exclude(
            decisions,
            "integration",
            "repository",
            "no integration declared and project facts are unknown",
            ResolutionSource.PROJECT_FACT,
            project_fact="project facts unspecified",
        )
        integration_include_rationale = None
    else:
        integration_ids = ["repository"]
        integration_include_rationale = "default project integration pin"
    for integration_id in integration_ids:
        if integration_id not in index["integrations"]:
            raise ToolkitResolutionError(f"integration {integration_id!r} not in registry")

    integration_ids = _reconcile_integrations_against_ceiling(
        manifest,
        integration_ids,
        integrations,
        index,
        decisions,
    )
    if integration_include_rationale is not None:
        integration_ids = [
            integration_id
            for integration_id in integration_ids
            if not any(
                decision.action == ResolutionAction.EXCLUDE
                and decision.component_kind == "integration"
                and decision.component_id == integration_id
                for decision in decisions
            )
        ]
        if not integration_ids:
            integration_include_rationale = None

    health_results = preflight_integrations(
        integrations,
        required_ids=integration_ids,
        observed_health=integration_health,
    )

    skill_versions = {
        skill_id: index["skills"][skill_id].version
        for skill_id in sorted(skills)
    }
    workflow_versions = {
        workflow_id: index["workflows"][workflow_id].version
        for workflow_id in sorted(workflows)
    }
    integration_adapter_versions = {
        integration_id: index["integrations"][integration_id].adapter_version
        for integration_id in integration_ids
    }
    validator_versions = {
        validator_id: index["validators"][validator_id].version
        for validator_id in sorted(validator_ids)
    }

    if integration_include_rationale is not None:
        for integration_id in integration_ids:
            decisions.append(
                _decision(
                    ResolutionAction.INCLUDE,
                    "integration",
                    integration_id,
                    integration_include_rationale,
                    ResolutionSource.REGISTRY,
                )
            )

    decisions.append(
        _decision(
            ResolutionAction.INCLUDE,
            "permission-profile",
            permission_profile.id,
            f"selected for external effect {permission_profile.external_effect.value}",
            ResolutionSource.PROJECT_FACT,
            project_fact=(
                f"impact.external_effect={manifest.impact.external_effect.value}"
                if manifest.impact.external_effect is not None
                else "impact.external_effect unknown; read-only default"
            ),
        )
    )
    decisions.append(
        _decision(
            ResolutionAction.INCLUDE,
            "budget-profile",
            budget_profile.id,
            "selected by consequence and registry defaults",
            ResolutionSource.PROJECT_FACT,
            project_fact=(
                f"impact.consequence={manifest.impact.consequence.value}"
                if manifest.impact.consequence is not None
                else "impact.consequence unknown; default budget"
            ),
        )
    )

    _scrub_include_decisions_not_in_lock(
        decisions,
        capabilities,
        skills,
        roles,
        workflows,
        integration_ids,
        validator_ids,
        permission_profile.id,
        budget_profile.id,
    )

    project_name = manifest.project.name or "unknown-project"

    lock = ToolkitLock(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        project_name=project_name,
        foundry_compat=registry.foundry_compat,
        capability_ids=_sorted_ids(list(capabilities)),
        skill_ids=_sorted_ids(list(skills)),
        workflow_ids=_sorted_ids(list(workflows)),
        integration_ids=integration_ids,
        role_ids=_sorted_ids(list(roles)),
        validator_ids=_sorted_ids(list(validator_ids)),
        permission_profile_ids=[permission_profile.id],
        budget_profile_ids=[budget_profile.id],
        skill_versions=skill_versions,
        workflow_versions=workflow_versions,
        validator_versions=validator_versions,
        integration_adapter_versions=integration_adapter_versions,
        permission_profile_version=permission_profile.version,
        declared_external_effect=declared_effect,
        permission_external_effect=permission_profile.external_effect,
        budget_profile_version=budget_profile.version,
        decisions=sorted(
            decisions,
            key=lambda item: (item.component_kind, item.component_id, item.rationale),
        ),
    )

    resolution = ToolkitResolution(
        resolved_capabilities=lock.capability_ids,
        resolved_skills=lock.skill_ids,
        resolved_workflows=lock.workflow_ids,
        integration_ids=lock.integration_ids,
        role_ids=lock.role_ids,
        validator_ids=lock.validator_ids,
        permission_profile_ids=lock.permission_profile_ids,
        budget_profile_ids=lock.budget_profile_ids,
        decisions=lock.decisions,
        integration_health=health_results,
    )
    validate_toolkit_lock_against_ceiling(
        lock,
        registry,
        declared_effect,
        integrations=integrations,
    )
    return resolution, lock


def _work_item_skill_relevance(work_item: WorkItemContract, skill_id: str, skills: dict[str, object]) -> bool:
    from agent_foundry.models.registry import SkillSpec

    skill = skills.get(skill_id)
    if not isinstance(skill, SkillSpec):
        return False
    triggers = skill.triggers
    if triggers.work_classes and work_item.work_class not in triggers.work_classes:
        return False
    return True


def _skill_allowed_for_work_item(
    work_item: WorkItemContract,
    skill_id: str,
    skills: dict[str, object],
) -> bool:
    from agent_foundry.models.registry import SkillSpec

    skill = skills.get(skill_id)
    if not isinstance(skill, SkillSpec):
        return False
    if not _work_item_skill_relevance(work_item, skill_id, skills):
        return False
    if skill.permissions.external_write and work_item.authority_class == ExternalEffectClass.READ_ONLY:
        return False
    return True


def _role_allowed_for_work_item(
    work_item: WorkItemContract,
    role_id: str,
    roles_by_id: dict[str, object],
    capabilities_by_id: dict[str, object],
) -> bool:
    from agent_foundry.models.registry import RoleContract

    role = roles_by_id.get(role_id)
    if not isinstance(role, RoleContract):
        return False
    ceiling = work_item.authority_class
    for capability_id in role.allowed_capabilities:
        min_effect = capability_min_external_effect(capability_id, capabilities_by_id)
        if exceeds_permission_ceiling(min_effect, ceiling):
            return False
    return True


def _derive_roles_from_selected_skills(
    work_item: WorkItemContract,
    selected_skills: set[str],
    project_lock: ToolkitLock,
    skills_by_id: dict[str, object],
    roles_by_id: dict[str, object],
    capabilities_by_id: dict[str, object],
) -> set[str]:
    from agent_foundry.models.registry import SkillSpec

    derived: set[str] = set()
    for skill_id in sorted(selected_skills):
        skill = skills_by_id.get(skill_id)
        if not isinstance(skill, SkillSpec):
            continue
        candidates = skill.roles.allowed if skill.roles.allowed else list(project_lock.role_ids)
        for role_id in sorted(candidates):
            if role_id not in project_lock.role_ids:
                continue
            if _role_allowed_for_work_item(work_item, role_id, roles_by_id, capabilities_by_id):
                derived.add(role_id)
    return derived


def _annotate_empty_task_toolkit(
    work_item: WorkItemContract,
    project_lock: ToolkitLock,
    selected_skills: set[str],
    selected_roles: set[str],
    selected_capabilities: set[str],
    skills_by_id: dict[str, object],
    decisions: list[ResolutionDecision],
) -> None:
    if selected_skills or selected_roles or selected_capabilities:
        if selected_skills and not selected_roles:
            _record_exclude(
                decisions,
                "task-toolkit",
                work_item.id,
                "selected skills have no compatible role in project lock for work item authority",
                ResolutionSource.WORK_ITEM,
                project_fact=(
                    f"work_item.authority_class={work_item.authority_class.value}; "
                    f"work_item.work_class={work_item.work_class.value}"
                ),
            )
        return

    compatible_skills = sorted(
        skill_id
        for skill_id in project_lock.skill_ids
        if _skill_allowed_for_work_item(work_item, skill_id, skills_by_id)
    )
    if not compatible_skills:
        rationale = (
            "no project-lock skill satisfies work item authority "
            f"{work_item.authority_class.value} and work class {work_item.work_class.value}"
        )
    else:
        rationale = (
            "no project-lock role can exercise the compatible skills for this work item "
            f"under authority {work_item.authority_class.value}"
        )
    _record_exclude(
        decisions,
        "task-toolkit",
        work_item.id,
        rationale,
        ResolutionSource.WORK_ITEM,
        project_fact=(
            f"work_item.authority_class={work_item.authority_class.value}; "
            f"work_item.work_class={work_item.work_class.value}"
        ),
    )


def _select_task_integrations(
    work_item: WorkItemContract,
    project_lock: ToolkitLock,
    integrations: list[IntegrationSpec],
    integration_health: list[IntegrationHealth],
    ceiling: ExternalEffectClass,
    capabilities_by_id: dict[str, object],
    decisions: list[ResolutionDecision],
) -> list[str]:
    """Subtract unavailable and over-authority integrations from the project pin.

    docs/foundry/04 §4 says the Task Toolkit subtracts unavailable integrations, and §12
    says a Task Toolkit must fail preflight when a required integration is not authorized
    and sufficiently healthy. This is where preflight health actually gates: an integration
    reaches the Task Toolkit only when a spec declares it, observed health meets that
    spec's requirement, and its capabilities stay inside the work item's authority.
    """
    specs_by_id = {spec.id: spec for spec in integrations}
    health_by_id = {
        item.integration_id: item
        for item in preflight_integrations(
            integrations,
            required_ids=list(project_lock.integration_ids),
            observed_health=integration_health,
        )
    }
    authority_fact = (
        f"work_item.authority_class={work_item.authority_class.value}; "
        f"task ceiling {ceiling.value}"
    )
    retained: list[str] = []

    for integration_id in project_lock.integration_ids:
        spec = specs_by_id.get(integration_id)
        health = health_by_id.get(integration_id)
        if spec is None or health is None:
            _record_exclude(
                decisions,
                "integration",
                integration_id,
                "no IntegrationSpec declared; availability cannot be established at task time",
                ResolutionSource.WORK_ITEM,
                project_fact=authority_fact,
            )
            continue
        if not meets_required_health(health.state, spec.health.required):
            _record_exclude(
                decisions,
                "integration",
                integration_id,
                (
                    f"integration health {health.state.value} does not meet required "
                    f"{spec.health.required.value}"
                ),
                ResolutionSource.WORK_ITEM,
                project_fact=authority_fact,
            )
            continue
        exceeding = sorted(
            capability_id
            for capability_id in spec.capabilities
            if _capability_exceeds_ceiling(capability_id, ceiling, capabilities_by_id)
        )
        if exceeding:
            _record_exclude(
                decisions,
                "integration",
                integration_id,
                (
                    f"integration capabilities exceed work item authority ceiling "
                    f"{ceiling.value}: {', '.join(exceeding)}"
                ),
                ResolutionSource.WORK_ITEM,
                project_fact=authority_fact,
            )
            continue
        retained.append(integration_id)
        _record_include(
            decisions,
            "integration",
            integration_id,
            (
                f"integration preflight health {health.state.value} meets required "
                f"{spec.health.required.value} within work item authority"
            ),
            ResolutionSource.WORK_ITEM,
            project_fact=authority_fact,
        )

    return retained


def _work_item_workflow_for_item(
    work_item: WorkItemContract,
    available_workflow_ids: list[str],
) -> str | None:
    if not available_workflow_ids:
        return None

    preference: list[str] = []
    if work_item.work_class == WorkClass.DISCOVERY:
        preference = ["investigator-synthesis"]
    elif work_item.work_class == WorkClass.INCIDENT:
        if work_item.authority_class == ExternalEffectClass.READ_ONLY:
            preference = ["investigator-synthesis"]
        else:
            preference = ["single-worker-validation", "investigator-synthesis"]
    elif work_item.work_class == WorkClass.CONTRACT_AMENDMENT:
        preference = ["builder-reviewer", "single-worker-validation"]
    elif work_item.work_class in {WorkClass.CAPABILITY, WorkClass.BASELINE}:
        if work_item.consequence_class in {ConsequenceClass.HIGH, ConsequenceClass.CRITICAL}:
            preference = ["builder-reviewer", "single-worker-validation"]
        else:
            preference = ["single-worker-validation", "builder-reviewer"]
    elif work_item.work_class == WorkClass.ADOPTION:
        preference = ["investigator-synthesis"]

    available = set(available_workflow_ids)
    for workflow_id in preference:
        if workflow_id in available:
            return workflow_id
    return sorted(available_workflow_ids)[0]


def resolve_task_toolkit(
    work_item: WorkItemContract,
    project_lock: ToolkitLock,
    registry: CapabilityRegistry,
    *,
    permission_profiles: list[PermissionProfile] = [],
    budget_profiles: list[BudgetProfile] = [],
    integrations: list[IntegrationSpec] = [],
    integration_health: list[IntegrationHealth] = [],
) -> TaskToolkit:
    """Resolve minimum Task Toolkit — strict subset of project lock, may only tighten controls."""
    index = _index_registry(registry)
    skills = index["skills"]
    roles_by_id = index["roles"]
    capabilities_by_id = index["capabilities"]

    selected_skills: set[str] = set()
    selected_roles: set[str] = set()
    selected_capabilities: set[str] = set()
    decisions: list[ResolutionDecision] = []

    workflow_id = _work_item_workflow_for_item(work_item, project_lock.workflow_ids)
    if workflow_id is not None:
        workflow = index["workflows"].get(workflow_id)
        from agent_foundry.models.registry import WorkflowSpec

        if isinstance(workflow, WorkflowSpec):
            for skill_id in workflow.required_skills:
                if skill_id in project_lock.skill_ids and _skill_allowed_for_work_item(
                    work_item, skill_id, skills
                ):
                    selected_skills.add(skill_id)
            for role_id in workflow.required_roles:
                if role_id in project_lock.role_ids and _role_allowed_for_work_item(
                    work_item,
                    role_id,
                    roles_by_id,
                    capabilities_by_id,
                ):
                    selected_roles.add(role_id)
            decisions.append(
                _decision(
                    ResolutionAction.INCLUDE,
                    "workflow",
                    workflow_id,
                    f"work item class {work_item.work_class.value} selects workflow",
                    ResolutionSource.WORK_ITEM,
                    project_fact=f"work_item.work_class={work_item.work_class.value}",
                )
            )

    for skill_id in project_lock.skill_ids:
        if _skill_allowed_for_work_item(work_item, skill_id, skills):
            selected_skills.add(skill_id)
            decisions.append(
                _decision(
                    ResolutionAction.INCLUDE,
                    "skill",
                    skill_id,
                    "skill triggers match work item class",
                    ResolutionSource.WORK_ITEM,
                    project_fact=f"work_item.work_class={work_item.work_class.value}",
                )
            )
        else:
            reason = "skill triggers do not match work item class"
            skill = skills.get(skill_id)
            from agent_foundry.models.registry import SkillSpec

            if isinstance(skill, SkillSpec) and skill.permissions.external_write:
                if work_item.authority_class == ExternalEffectClass.READ_ONLY:
                    reason = "skill requires external write but work item authority is read-only"
            elif not _work_item_skill_relevance(work_item, skill_id, skills):
                reason = "skill triggers do not match work item class"
            decisions.append(
                _decision(
                    ResolutionAction.EXCLUDE,
                    "skill",
                    skill_id,
                    reason,
                    ResolutionSource.WORK_ITEM,
                    project_fact=f"work_item.work_class={work_item.work_class.value}",
                )
            )

    selected_roles.update(
        _derive_roles_from_selected_skills(
            work_item,
            selected_skills,
            project_lock,
            skills,
            roles_by_id,
            capabilities_by_id,
        )
    )

    for skill_id in sorted(selected_skills):
        skill = skills.get(skill_id)
        from agent_foundry.models.registry import SkillSpec

        if isinstance(skill, SkillSpec):
            for cap in skill.required_capabilities:
                if cap in project_lock.capability_ids:
                    selected_capabilities.add(cap)

    for cap in sorted(selected_capabilities):
        decisions.append(
            _decision(
                ResolutionAction.INCLUDE,
                "capability",
                cap,
                "required by selected task skills",
                ResolutionSource.WORK_ITEM,
                project_fact=f"work_item.work_class={work_item.work_class.value}",
            )
        )

    excluded_capabilities = set(project_lock.capability_ids) - selected_capabilities
    for cap in sorted(excluded_capabilities):
        decisions.append(
            _decision(
                ResolutionAction.EXCLUDE,
                "capability",
                cap,
                "not required for this work item",
                ResolutionSource.WORK_ITEM,
            )
        )

    for role_id in sorted(project_lock.role_ids):
        if role_id in selected_roles:
            decisions.append(
                _decision(
                    ResolutionAction.INCLUDE,
                    "role",
                    role_id,
                    "required by selected task workflow or skills",
                    ResolutionSource.WORK_ITEM,
                    project_fact=f"work_item.work_class={work_item.work_class.value}",
                )
            )
        else:
            decisions.append(
                _decision(
                    ResolutionAction.EXCLUDE,
                    "role",
                    role_id,
                    "not required for this work item",
                    ResolutionSource.WORK_ITEM,
                    project_fact=f"work_item.work_class={work_item.work_class.value}",
                )
            )

    if not permission_profiles:
        raise ToolkitResolutionError("permission profiles required for task resolution")

    project_profile_id = project_lock.permission_profile_ids[0]
    project_profile = _lookup_permission_profile(project_profile_id, permission_profiles)
    project_ceiling = project_profile.external_effect

    ceiling_rank = min(
        EFFECT_RANK[work_item.authority_class],
        EFFECT_RANK[project_ceiling],
    )
    candidates = [
        profile
        for profile in permission_profiles
        if EFFECT_RANK[profile.external_effect] <= ceiling_rank
    ]
    if not candidates:
        raise PolicyViolationError(
            "task permission profile would loosen project toolkit controls"
        )
    task_profile = max(
        candidates,
        key=lambda profile: (EFFECT_RANK[profile.external_effect], profile.id),
    )

    if EFFECT_RANK[task_profile.external_effect] > EFFECT_RANK[project_ceiling]:
        raise PolicyViolationError(
            "task permission profile would loosen project toolkit controls"
        )

    project_budget = project_lock.budget_profile_ids[0]
    task_budget = project_budget
    if work_item.consequence_class in {ConsequenceClass.HIGH, ConsequenceClass.CRITICAL}:
        if "tight-validation" in project_lock.budget_profile_ids:
            task_budget = "tight-validation"

    if not budget_profiles:
        raise ToolkitResolutionError("budget profiles required for task resolution")
    project_budget_profile = _lookup_budget_profile(project_budget, budget_profiles)
    task_budget_profile = _lookup_budget_profile(task_budget, budget_profiles)

    if (task_budget_profile.max_parallel_runs or 0) > (project_budget_profile.max_parallel_runs or 0):
        raise PolicyViolationError("task budget would loosen parallel run limit")
    if (task_budget_profile.max_retry_budget or 0) > (project_budget_profile.max_retry_budget or 0):
        raise PolicyViolationError("task budget would loosen retry budget")
    if task_budget_profile.token_budget is not None and project_budget_profile.token_budget is not None:
        if task_budget_profile.token_budget > project_budget_profile.token_budget:
            raise PolicyViolationError("task budget would loosen token budget")

    integration_ids = _select_task_integrations(
        work_item,
        project_lock,
        integrations,
        integration_health,
        tighten_ceiling(work_item.authority_class, project_ceiling),
        capabilities_by_id,
        decisions,
    )

    _annotate_empty_task_toolkit(
        work_item,
        project_lock,
        selected_skills,
        selected_roles,
        selected_capabilities,
        skills,
        decisions,
    )

    task_toolkit = TaskToolkit(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        work_item_id=work_item.id,
        capability_ids=_sorted_ids(list(selected_capabilities)),
        skill_ids=_sorted_ids(list(selected_skills)),
        workflow_id=workflow_id,
        integration_ids=integration_ids,
        role_ids=_sorted_ids(list(selected_roles)),
        validator_ids=list(project_lock.validator_ids),
        permission_profile_ids=[task_profile.id],
        budget_profile_ids=[task_budget],
        decisions=sorted(
            decisions,
            key=lambda item: (item.action.value, item.component_kind, item.component_id, item.rationale),
        ),
    )
    validate_task_toolkit_against_ceiling(
        task_toolkit,
        project_lock,
        registry,
        work_item,
        permission_profiles,
        integrations=integrations,
    )
    return task_toolkit


def assert_component_schema_supported(registry: CapabilityRegistry) -> None:
    """Reject registry whose component schema versions are newer than supported."""
    for collection_name, items in (
        ("capabilities", registry.capabilities),
        ("skills", registry.skills),
        ("workflows", registry.workflows),
        ("roles", registry.roles),
    ):
        for item in items:
            try:
                validate = item.schema_version
            except AttributeError:
                continue
            from agent_foundry.models.base import validate_schema_compatibility

            try:
                validate_schema_compatibility(f"{collection_name}:{item.id}", validate)
            except SchemaCompatibilityError as exc:
                raise SchemaCompatibilityError(
                    f"registry component {item.id} schema unsupported: {exc}"
                ) from exc
