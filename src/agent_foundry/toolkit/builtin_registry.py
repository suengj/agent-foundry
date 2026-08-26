"""Builtin capability registry — small, inspectable, version-pinned."""

from __future__ import annotations

from agent_foundry.models.base import FOUNDRY_SCHEMA_VERSION
from agent_foundry.models.common import (
    AssuranceMode,
    AuthorityRequirement,
    ConsequenceClass,
    EvidenceClass,
    ExternalEffectClass,
    PrimaryArtifactState,
    PrimaryWorkMode,
    WorkClass,
)
from agent_foundry.models.policy import BudgetProfile, PermissionProfile, PolicyPredicate, PolicyRule
from agent_foundry.models.registry import (
    BudgetProfileRef,
    CapabilityRegistry,
    CapabilitySpec,
    IntegrationRegistryEntry,
    PermissionProfileRef,
    RoleContract,
    SkillPermissions,
    SkillRoleConstraint,
    SkillSpec,
    SkillTriggers,
    ToolConnectorKind,
    ToolConnectorSpec,
    ValidatorSpec,
    WorkflowSpec,
)
_REGISTRY_VERSION = "1.0.0"
_FOUNDRY_COMPAT = ">=0.1,<0.2"

_WRITE_EXTERNAL_EFFECTS = [
    ExternalEffectClass.REPOSITORY_WRITE,
    ExternalEffectClass.SHARED_SERVICE_WRITE,
    ExternalEffectClass.DATA_MUTATION,
    ExternalEffectClass.RUNTIME_MUTATION,
    ExternalEffectClass.PUBLICATION,
]


def _independent_review_policy_rules() -> list[PolicyRule]:
    rules: list[PolicyRule] = []
    for consequence in (ConsequenceClass.HIGH, ConsequenceClass.CRITICAL):
        for effect in _WRITE_EXTERNAL_EFFECTS:
            rules.append(
                PolicyRule(
                    id=f"{consequence.value}-consequence-requires-independent-review-{effect.value}",
                    description=(
                        f"{consequence.value} consequence requires independent review "
                        f"for {effect.value} projects"
                    ),
                    when=PolicyPredicate(consequence=consequence, external_effect=effect),
                    require_skills=["independent-review"],
                    require_workflows=["builder-reviewer"],
                    require_roles=["reviewer"],
                )
            )
        rules.append(
            PolicyRule(
                id=f"{consequence.value}-consequence-requires-independent-review-read-only",
                description=(
                    f"{consequence.value} consequence read-only projects require "
                    "read-only independent review workflow"
                ),
                when=PolicyPredicate(
                    consequence=consequence,
                    external_effect=ExternalEffectClass.READ_ONLY,
                ),
                require_skills=["independent-review"],
                require_workflows=["independent-review-readonly"],
                require_roles=["reviewer"],
            )
        )
    for effect in _WRITE_EXTERNAL_EFFECTS:
        rules.append(
            PolicyRule(
                id=f"independent-review-assurance-{effect.value}",
                description=f"Projects requiring independent review assurance ({effect.value})",
                when=PolicyPredicate(
                    assurance=AssuranceMode.INDEPENDENT_REVIEW,
                    external_effect=effect,
                ),
                require_skills=["independent-review"],
                require_workflows=["builder-reviewer"],
                require_roles=["reviewer"],
            )
        )
    rules.append(
        PolicyRule(
            id="independent-review-assurance-read-only",
            description="Read-only projects requiring independent review assurance",
            when=PolicyPredicate(
                assurance=AssuranceMode.INDEPENDENT_REVIEW,
                external_effect=ExternalEffectClass.READ_ONLY,
            ),
            require_skills=["independent-review"],
            require_workflows=["independent-review-readonly"],
            require_roles=["reviewer"],
        )
    )
    return rules


def _cap(
    id: str,
    description: str,
    *,
    tags: list[str] = [],
    provides: list[str] = [],
    min_external_effect: ExternalEffectClass = ExternalEffectClass.PUBLICATION,
) -> CapabilitySpec:
    return CapabilitySpec(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        id=id,
        version="1.0.0",
        description=description,
        tags=tags,
        provides=provides or [id],
        min_external_effect=min_external_effect,
    )


def _skill(
    id: str,
    description: str,
    *,
    provides: list[str] = [],
    required_capabilities: list[str] = [],
    triggers: SkillTriggers | None = None,
    roles: SkillRoleConstraint | None = None,
    external_write: bool = False,
    inputs: list[str] = [],
    outputs: list[str] = [],
    produces_evidence: list[EvidenceClass] = [],
) -> SkillSpec:
    return SkillSpec(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        id=id,
        version="1.0.0",
        description=description,
        provides=provides or [id],
        required_capabilities=required_capabilities,
        triggers=triggers or SkillTriggers(),
        roles=roles or SkillRoleConstraint(),
        permissions=SkillPermissions(external_write=external_write),
        inputs=inputs,
        outputs=outputs,
        produces_evidence=list(produces_evidence),
    )


def _workflow(
    id: str,
    description: str,
    *,
    node_ids: list[str] = [],
    required_roles: list[str] = [],
    required_skills: list[str] = [],
) -> WorkflowSpec:
    return WorkflowSpec(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        id=id,
        version="1.0.0",
        description=description,
        node_ids=node_ids,
        required_roles=required_roles,
        required_skills=required_skills,
    )


def _role(
    id: str,
    description: str,
    *,
    allowed_capabilities: list[str] = [],
    write_scope: list[str] = [],
) -> RoleContract:
    return RoleContract(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        id=id,
        version="1.0.0",
        description=description,
        allowed_capabilities=allowed_capabilities,
        write_scope=write_scope,
    )


def build_default_registry() -> CapabilityRegistry:
    """Return the default small capability registry."""
    capabilities = [
        _cap(
            "repository.read",
            "Read repository files within scoped paths",
            tags=["repository"],
            min_external_effect=ExternalEffectClass.READ_ONLY,
        ),
        _cap(
            "repository.write",
            "Write repository files within scoped paths",
            tags=["repository"],
            min_external_effect=ExternalEffectClass.REPOSITORY_WRITE,
        ),
        _cap(
            "validation.test",
            "Run deterministic project tests",
            tags=["validation"],
            min_external_effect=ExternalEffectClass.READ_ONLY,
        ),
        _cap(
            "validation.review",
            "Perform independent review",
            tags=["validation"],
            min_external_effect=ExternalEffectClass.READ_ONLY,
        ),
        _cap(
            "inspection.read",
            "Inspect repository structure read-only",
            tags=["inspection"],
            min_external_effect=ExternalEffectClass.READ_ONLY,
        ),
        _cap(
            # Reading a tracker changes nothing outside the working tree, so it sits
            # on the same rung as runtime.verify. See CapabilitySpec.min_external_effect.
            "work.read",
            "Read work tracker state",
            tags=["work"],
            min_external_effect=ExternalEffectClass.READ_ONLY,
        ),
        _cap(
            "work.write",
            "Mutate work tracker state",
            tags=["work"],
            min_external_effect=ExternalEffectClass.SHARED_SERVICE_WRITE,
        ),
        _cap(
            "runtime.verify",
            "Verify runtime or external read-back",
            tags=["runtime"],
            min_external_effect=ExternalEffectClass.READ_ONLY,
        ),
    ]

    roles = [
        _role("manager", "Coordinate work and authority boundaries"),
        _role("explorer", "Read-only discovery", allowed_capabilities=["repository.read", "inspection.read"]),
        _role(
            # No `write_scope` here, deliberately. It used to be `["src/", "tests/"]`,
            # which is a project-shape assumption living in core: compiled write
            # authority is the intersection of the declared bounds with the Work Item
            # scope, so every project whose changes land elsewhere — an instruction
            # surface, a build file, a CI config — intersected to nothing and compiled
            # to a bundle authorizing no change it could make. The bound now comes from
            # the project's own `authority.write_scope` declaration, and a role in a
            # project-supplied registry may narrow it further.
            "builder",
            "Primary implementation role",
            allowed_capabilities=["repository.read", "repository.write"],
        ),
        _role("validator", "Run deterministic validation", allowed_capabilities=["validation.test"]),
        _role("reviewer", "Independent review role", allowed_capabilities=["validation.review"]),
        _role("integrator", "Integrate external systems", allowed_capabilities=["work.read", "work.write"]),
        _role("runtime-verifier", "Runtime verification", allowed_capabilities=["runtime.verify"]),
    ]

    skills = [
        _skill(
            "repository-inspection",
            "Inspect repository structure and conventions read-only",
            provides=["inspection.read"],
            required_capabilities=["repository.read", "inspection.read"],
            triggers=SkillTriggers(
                artifact_types=["source-code"],
                work_modes=[PrimaryWorkMode.ANALYZE, PrimaryWorkMode.RESEARCH, PrimaryWorkMode.OPERATE],
                work_classes=[
                    WorkClass.DISCOVERY,
                    WorkClass.ADOPTION,
                    WorkClass.INCIDENT,
                    WorkClass.CONTRACT_AMENDMENT,
                ],
            ),
            roles=SkillRoleConstraint(allowed=["explorer", "manager"]),
            inputs=["repository-root"],
            outputs=["inspection-evidence"],
            # Inspection evidence describes a repository; it closes no evidence class a
            # Work Item can require. This skill is selected as a read baseline or by a
            # workflow, never because an item asked for what it produces.
            produces_evidence=[],
        ),
        _skill(
            "bounded-change",
            "Make bounded code changes with tests",
            provides=["repository.write"],
            required_capabilities=["repository.read", "repository.write"],
            triggers=SkillTriggers(
                artifact_types=["source-code"],
                work_modes=[PrimaryWorkMode.BUILD, PrimaryWorkMode.OPERATE],
                # ADOPTION is here because adoption is repository-writing work: the
                # planner marks its own HARDEN/CONSOLIDATE/MIGRATE changes
                # `bounded-policy` precisely because applying them edits files. Without
                # it, the only work class the adoption planner emits was the one class
                # no write-bearing skill would accept, so a retrofit plan compiled to a
                # read-only bundle that could not carry it out.
                work_classes=[
                    WorkClass.ADOPTION,
                    WorkClass.CAPABILITY,
                    WorkClass.BASELINE,
                    WorkClass.INCIDENT,
                    WorkClass.CONTRACT_AMENDMENT,
                ],
            ),
            roles=SkillRoleConstraint(allowed=["builder"]),
            external_write=True,
            inputs=["changed-scope"],
            outputs=["implementation-diff"],
            produces_evidence=[EvidenceClass.REPOSITORY_REVISION],
        ),
        _skill(
            "deterministic-test",
            "Run project-approved deterministic tests and return normalized evidence",
            provides=["validation.test"],
            required_capabilities=["validation.test"],
            triggers=SkillTriggers(
                artifact_types=["source-code"],
                work_modes=[PrimaryWorkMode.BUILD, PrimaryWorkMode.OPERATE],
                # Adoption units carry "regression evidence passes" as an acceptance
                # criterion, so the class that has to produce that evidence must be
                # able to select the skill that produces it.
                work_classes=[
                    WorkClass.ADOPTION,
                    WorkClass.CAPABILITY,
                    WorkClass.BASELINE,
                    WorkClass.INCIDENT,
                    WorkClass.CONTRACT_AMENDMENT,
                ],
            ),
            roles=SkillRoleConstraint(allowed=["builder", "validator"]),
            inputs=["changed-scope"],
            outputs=["test-evidence"],
            produces_evidence=[EvidenceClass.DETERMINISTIC_TEST],
        ),
        _skill(
            "independent-review",
            "Perform independent review without implementation authority",
            provides=["validation.review"],
            required_capabilities=["validation.review"],
            triggers=SkillTriggers(
                # An adoption change the planner marks `explicit-authority` is exactly
                # the kind an independent-review assurance requirement is for.
                work_classes=[
                    WorkClass.ADOPTION,
                    WorkClass.CAPABILITY,
                    WorkClass.RESIDUAL_HARDENING,
                    WorkClass.CONTRACT_AMENDMENT,
                ],
            ),
            roles=SkillRoleConstraint(allowed=["reviewer"]),
            inputs=["implementation-diff", "test-evidence"],
            outputs=["review-decision"],
            produces_evidence=[EvidenceClass.INDEPENDENT_REVIEW],
        ),
    ]

    workflows = [
        _workflow(
            "single-worker-validation",
            "Single worker executes and validates",
            node_ids=["builder", "validator"],
            required_roles=["builder", "validator"],
            required_skills=["bounded-change", "deterministic-test"],
        ),
        _workflow(
            "builder-reviewer",
            "Builder then independent reviewer",
            node_ids=["builder", "reviewer"],
            required_roles=["builder", "reviewer"],
            required_skills=["bounded-change", "deterministic-test", "independent-review"],
        ),
        _workflow(
            "investigator-synthesis",
            "Explorer investigates then manager synthesizes",
            node_ids=["explorer", "manager"],
            required_roles=["explorer", "manager"],
            required_skills=["repository-inspection"],
        ),
        _workflow(
            "independent-review-readonly",
            "Independent reviewer without implementation authority",
            node_ids=["reviewer"],
            required_roles=["reviewer"],
            required_skills=["independent-review"],
        ),
    ]

    tools = [
        ToolConnectorSpec(
            schema_version=FOUNDRY_SCHEMA_VERSION,
            id="repository-edit",
            version="1.0.0",
            description="Repository file edit tool metadata",
            kind=ToolConnectorKind.TOOL,
            capabilities=["repository.read", "repository.write"],
            transport="local",
        ),
        ToolConnectorSpec(
            schema_version=FOUNDRY_SCHEMA_VERSION,
            id="repository-search",
            version="1.0.0",
            description="Repository search tool metadata",
            kind=ToolConnectorKind.TOOL,
            capabilities=["repository.read"],
            transport="local",
        ),
    ]

    connectors = [
        ToolConnectorSpec(
            schema_version=FOUNDRY_SCHEMA_VERSION,
            id="work-tracker-connector",
            version="1.0.0",
            description="Work tracker connector metadata",
            kind=ToolConnectorKind.CONNECTOR,
            capabilities=["work.read", "work.write"],
            transport="mcp",
        ),
    ]

    validators = [
        ValidatorSpec(
            schema_version=FOUNDRY_SCHEMA_VERSION,
            id="evidence-contract",
            version="1.0.0",
            description="Validate evidence bundle contract completeness",
            validates=["evidence-bundle"],
        ),
        ValidatorSpec(
            schema_version=FOUNDRY_SCHEMA_VERSION,
            id="schema-compat",
            version="1.0.0",
            description="Validate schema version compatibility",
            validates=["schema-version"],
        ),
    ]

    permission_profiles = [
        PermissionProfile(
            id="read-only",
            external_effect=ExternalEffectClass.READ_ONLY,
            write_requires=AuthorityRequirement.NONE,
            preview_required=False,
            apply_requires=AuthorityRequirement.NONE,
        ),
        PermissionProfile(
            id="repository-write-bounded",
            external_effect=ExternalEffectClass.REPOSITORY_WRITE,
            write_requires=AuthorityRequirement.BOUNDED_POLICY,
            preview_required=True,
            apply_requires=AuthorityRequirement.EXPLICIT_AUTHORITY,
        ),
        PermissionProfile(
            id="shared-service-write",
            external_effect=ExternalEffectClass.SHARED_SERVICE_WRITE,
            write_requires=AuthorityRequirement.EXPLICIT_AUTHORITY,
            preview_required=True,
            apply_requires=AuthorityRequirement.EXPLICIT_AUTHORITY,
        ),
        PermissionProfile(
            id="runtime-mutation-bounded",
            external_effect=ExternalEffectClass.RUNTIME_MUTATION,
            write_requires=AuthorityRequirement.EXPLICIT_AUTHORITY,
            preview_required=True,
            apply_requires=AuthorityRequirement.EXPLICIT_AUTHORITY,
        ),
    ]

    budget_profiles = [
        BudgetProfile(id="default", max_parallel_runs=4, max_retry_budget=2),
        BudgetProfile(id="tight-validation", max_parallel_runs=1, max_retry_budget=1, token_budget=50000),
    ]

    policy_rules = [
        * _independent_review_policy_rules(),
        PolicyRule(
            id="deterministic-tests-assurance",
            description="Projects requiring deterministic tests must include test skill",
            when=PolicyPredicate(assurance=AssuranceMode.DETERMINISTIC_TESTS),
            require_skills=["deterministic-test"],
            require_capabilities=["validation.test"],
        ),
        PolicyRule(
            id="runtime-readback-assurance",
            description="Projects requiring runtime readback include runtime verifier",
            when=PolicyPredicate(assurance=AssuranceMode.RUNTIME_READBACK),
            require_roles=["runtime-verifier"],
            require_capabilities=["runtime.verify"],
        ),
        PolicyRule(
            id="forbid-shared-service-without-explicit-authority",
            description="Forbid shared-service-write profile unless external effect warrants it",
            when=PolicyPredicate(external_effect=ExternalEffectClass.READ_ONLY),
            forbid_permission_profiles=["shared-service-write"],
        ),
    ]

    integrations = [
        IntegrationRegistryEntry(id="repository", adapter_version="adapter-v1"),
        IntegrationRegistryEntry(id="work-tracker", adapter_version="adapter-v1"),
    ]

    return CapabilityRegistry(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        foundry_compat=_FOUNDRY_COMPAT,
        capabilities=capabilities,
        skills=skills,
        workflows=workflows,
        roles=roles,
        tools=tools,
        connectors=connectors,
        validators=validators,
        permission_profiles=[
            PermissionProfileRef(id=p.id, version=p.version) for p in permission_profiles
        ],
        budget_profiles=[BudgetProfileRef(id=b.id, version=b.version) for b in budget_profiles],
        integrations=integrations,
        policy_rules=policy_rules,
    )


def permission_profiles_for_registry(registry: CapabilityRegistry) -> list[PermissionProfile]:
    """Full permission profile objects keyed by registry refs — builtin registry only."""
    profiles = build_default_registry_permission_profiles()
    by_id = {profile.id: profile for profile in profiles}
    return [by_id[ref.id] for ref in registry.permission_profiles if ref.id in by_id]


def budget_profiles_for_registry(registry: CapabilityRegistry) -> list[BudgetProfile]:
    profiles = build_default_registry_budget_profiles()
    by_id = {profile.id: profile for profile in profiles}
    return [by_id[ref.id] for ref in registry.budget_profiles if ref.id in by_id]


def build_default_registry_permission_profiles() -> list[PermissionProfile]:
    return [
        PermissionProfile(
            id="read-only",
            external_effect=ExternalEffectClass.READ_ONLY,
            write_requires=AuthorityRequirement.NONE,
            preview_required=False,
            apply_requires=AuthorityRequirement.NONE,
        ),
        PermissionProfile(
            id="repository-write-bounded",
            external_effect=ExternalEffectClass.REPOSITORY_WRITE,
            write_requires=AuthorityRequirement.BOUNDED_POLICY,
            preview_required=True,
            apply_requires=AuthorityRequirement.EXPLICIT_AUTHORITY,
        ),
        PermissionProfile(
            id="shared-service-write",
            external_effect=ExternalEffectClass.SHARED_SERVICE_WRITE,
            write_requires=AuthorityRequirement.EXPLICIT_AUTHORITY,
            preview_required=True,
            apply_requires=AuthorityRequirement.EXPLICIT_AUTHORITY,
        ),
        PermissionProfile(
            id="runtime-mutation-bounded",
            external_effect=ExternalEffectClass.RUNTIME_MUTATION,
            write_requires=AuthorityRequirement.EXPLICIT_AUTHORITY,
            preview_required=True,
            apply_requires=AuthorityRequirement.EXPLICIT_AUTHORITY,
        ),
    ]


def build_default_registry_budget_profiles() -> list[BudgetProfile]:
    return [
        BudgetProfile(id="default", max_parallel_runs=4, max_retry_budget=2),
        BudgetProfile(id="tight-validation", max_parallel_runs=1, max_retry_budget=1, token_budget=50000),
    ]


def manifest_requires_code_capabilities(manifest) -> bool:
    """True when manifest facts indicate a code-centric project."""
    from agent_foundry.models.project import ProjectManifest

    if not isinstance(manifest, ProjectManifest):
        return False
    artifact = manifest.project.primary_artifact
    if artifact == PrimaryArtifactState.CODE:
        return True
    primary_mode = (
        manifest.project.work_modes.primary if manifest.project.work_modes is not None else None
    )
    return primary_mode == PrimaryWorkMode.BUILD


def manifest_external_effect_allows_repository_write(manifest) -> bool:
    """True when declared external effect permits repository write."""
    from agent_foundry.models.project import ProjectManifest
    from agent_foundry.toolkit.ceiling import EFFECT_RANK, effective_permission_ceiling

    if not isinstance(manifest, ProjectManifest):
        return False
    effect = manifest.impact.external_effect
    if effect is None:
        return False
    return EFFECT_RANK[effect] >= EFFECT_RANK[ExternalEffectClass.REPOSITORY_WRITE]
