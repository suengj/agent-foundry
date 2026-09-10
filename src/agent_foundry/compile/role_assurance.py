"""Deterministic SUE-583 role, assurance, authority, and escalation compiler."""

from __future__ import annotations

from collections.abc import Iterable

from agent_foundry.models.base import FOUNDRY_SCHEMA_VERSION
from agent_foundry.models.common import (
    Ambiguity,
    ApprovalClass,
    AssuranceMode,
    Autonomy,
    ConsequenceClass,
    ControlTrigger,
    CorrectnessObservability,
    Coupling,
    EvidenceClass,
    EvidenceStrength,
    ExternalEffectClass,
    Reversibility,
)
from agent_foundry.models.compiler import (
    AssuranceDecision,
    CapabilityDeclaration,
    CompilationTraceEntry,
    CompiledCapabilityRequirement,
    EscalationRequirement,
    LogicalRoleTopology,
    RoleAssuranceCompilation,
    RoleDecision,
    UnresolvedPrerequisite,
    WorkCharacteristics,
    validate_compilation_explainability,
)
from agent_foundry.models.policy import (
    AssuranceRequirement,
    AuthorityCeiling,
    DecisionRights,
    OperatingModel,
)
from agent_foundry.models.project import ProfileResolution, ProjectProfile
from agent_foundry.models.registry import CapabilityRegistry, CapabilitySpec, RoleContract
from agent_foundry.models.work import WorkItemContract
from agent_foundry.toolkit.builtin_registry import build_default_registry


_EFFECT_RANK = {item: index for index, item in enumerate(ExternalEffectClass)}
_AUTONOMY_RANK = {item: index for index, item in enumerate(Autonomy)}
_ROLE_ORDER = (
    "manager",
    "explorer",
    "builder",
    "validator",
    "reviewer",
    "integrator",
    "runtime-verifier",
)


def _min_effect(left: ExternalEffectClass, right: ExternalEffectClass) -> ExternalEffectClass:
    return left if _EFFECT_RANK[left] <= _EFFECT_RANK[right] else right


def _min_autonomy(left: Autonomy, right: Autonomy) -> Autonomy:
    return left if _AUTONOMY_RANK[left] <= _AUTONOMY_RANK[right] else right


def _profile_values(profile: ProjectProfile | None, *names: str) -> tuple[str, ...]:
    if profile is None:
        return ()
    wanted = set(names)
    values: list[str] = []
    for dimension in profile.dimensions:
        if dimension.dimension not in wanted or dimension.resolution is not ProfileResolution.RESOLVED:
            continue
        values.append(dimension.attributions[0].value)
    return tuple(sorted(set(values)))


def _profile_list(profile: ProjectProfile | None, *names: str) -> tuple[str, ...]:
    values: list[str] = []
    for value in _profile_values(profile, *names):
        values.extend(part.strip() for part in value.replace(";", ",").split(","))
    return tuple(sorted({item for item in values if item}))


def _characteristics(work: WorkCharacteristics | WorkItemContract) -> WorkCharacteristics:
    if isinstance(work, WorkCharacteristics):
        return work
    runtime = any(item in {"runtime-readback", "integration-proof"} for item in work.required_evidence)
    sit = any("sit" in item.lower() for item in (*work.acceptance_criteria, *work.title, *work.objective))
    return WorkCharacteristics(
        workflow_kind=work.work_class.value,
        external_effect=work.authority_class,
        consequence=work.consequence_class,
        required_evidence=tuple(
            item for item in EvidenceClass if item.value in set(work.required_evidence)
        ),
        requires_sit=sit,
        requires_runtime_readback=runtime,
    )


def _blast_radius(work: WorkCharacteristics):
    from agent_foundry.models.policy import BlastRadius

    return BlastRadius(
        consequence=work.consequence,
        uncertainty=work.uncertainty,
        coupling=work.coupling,
        reversibility=work.reversibility,
        observability=work.observability,
    )


def _assurance(
    work: WorkCharacteristics,
    operating_model: OperatingModel,
    *,
    profile: ProjectProfile | None,
) -> tuple[AssuranceRequirement, tuple[str, ...], tuple[AssuranceDecision, ...]]:
    if (
        not operating_model.assurance.requirements
        and operating_model.assurance.default_requirement is None
    ):
        # A fully known low-impact work item gets the minimum executable floor.
        # The policy contract's fail-closed resolver remains unchanged for callers
        # asking it directly; this compiler does not turn an omitted low-risk
        # assurance profile into an unnecessary reviewer/human gate.
        base = AssuranceRequirement(
            blast_radius=_blast_radius(work),
            minimum_evidence_strength=EvidenceStrength.MODERATE,
            required_evidence=(EvidenceClass.DETERMINISTIC_TEST,),
            required_modes=(AssuranceMode.DETERMINISTIC_TESTS,),
        )
    else:
        base = operating_model.assurance.for_blast_radius(_blast_radius(work))
    modes = set(base.required_modes)
    evidence = set(base.required_evidence)
    causes_by_mode: dict[AssuranceMode, set[str]] = {
        mode: {"operating_model.assurance"} for mode in base.required_modes
    }
    causes_by_evidence: dict[EvidenceClass, set[str]] = {
        item: {"operating_model.assurance"} for item in base.required_evidence
    }

    def require_mode(mode: AssuranceMode, cause: str) -> None:
        modes.add(mode)
        causes_by_mode.setdefault(mode, set()).add(cause)

    def require_evidence(item: EvidenceClass, cause: str) -> None:
        evidence.add(item)
        causes_by_evidence.setdefault(item, set()).add(cause)

    for mode in work.required_assurance_modes:
        require_mode(mode, "work.required_assurance_modes")
    for item in work.required_evidence:
        require_evidence(item, "work.required_evidence")

    kind = work.workflow_kind.lower().replace("_", "-")
    if work.external_effect is ExternalEffectClass.READ_ONLY and (
        "review" in kind or "exact-sha" in kind or "exact-sha" in (work.request_type or "").lower()
    ):
        require_mode(AssuranceMode.INDEPENDENT_REVIEW, "workflow kind requests independent review")
        require_evidence(EvidenceClass.INDEPENDENT_REVIEW, "workflow kind requests independent review")

    # This is the high-consequence floor. It is deliberately explicit at the
    # compiler seam: deleting it must make the high-consequence topology weaker,
    # which is covered by the mutation test in test_role_assurance_compiler.py.
    if work.consequence in {ConsequenceClass.HIGH, ConsequenceClass.CRITICAL}:
        require_mode(AssuranceMode.INDEPENDENT_REVIEW, "work.consequence>=high")
        require_evidence(EvidenceClass.INDEPENDENT_REVIEW, "work.consequence>=high")

    if work.requires_sit:
        require_mode(AssuranceMode.RUNTIME_READBACK, "work.requires_sit")
        require_evidence(EvidenceClass.INTEGRATION_PROOF, "work.requires_sit")
    if work.requires_runtime_readback:
        require_mode(AssuranceMode.RUNTIME_READBACK, "work.requires_runtime_readback")
        require_evidence(EvidenceClass.RUNTIME_READBACK, "work.requires_runtime_readback")

    profile_modes = _profile_list(profile, "assurance.required", "assurance.mode")
    for value in profile_modes:
        try:
            require_mode(AssuranceMode(value), "project_profile.assurance")
        except ValueError:
            # A descriptive profile value is not authority. Unknown declarations
            # become a prerequisite rather than a silently invented mode.
            continue

    independent = (
        base.independent_review
        or AssuranceMode.INDEPENDENT_REVIEW in modes
        or operating_model.role_separation.independent_review_required
    )
    human = base.human_required or AssuranceMode.HUMAN_ACCEPTANCE in modes
    minimum_actors = max(
        base.minimum_distinct_actors,
        operating_model.role_separation.minimum_distinct_actors,
        2 if independent else 1,
    )
    requirement = AssuranceRequirement(
        blast_radius=_blast_radius(work),
        minimum_evidence_strength=base.minimum_evidence_strength,
        required_evidence=tuple(sorted(evidence, key=lambda item: item.value)),
        required_modes=tuple(sorted(modes, key=lambda item: item.value)),
        independent_review=independent,
        human_required=human,
        minimum_distinct_actors=minimum_actors,
        relaxation_evidence_refs=base.relaxation_evidence_refs,
    )

    decisions: list[AssuranceDecision] = []
    for mode in AssuranceMode:
        selected = mode in modes
        causes = causes_by_mode.get(mode, {"not required by supplied work/policy"})
        decisions.append(
            AssuranceDecision(
                component="assurance-mode",
                component_id=mode.value,
                selected=selected,
                rationale=("required by compiled assurance floor" if selected else "not required by compiled assurance floor"),
                causes=tuple(sorted(causes)),
                policy_refs=(f"operating-model:{operating_model.id}",),
            )
        )
    for item in EvidenceClass:
        selected = item in evidence
        causes = causes_by_evidence.get(item, {"not required by supplied work/policy"})
        decisions.append(
            AssuranceDecision(
                component="assurance-evidence",
                component_id=item.value,
                selected=selected,
                rationale=("required by compiled assurance floor" if selected else "not required by compiled assurance floor"),
                causes=tuple(sorted(causes)),
                policy_refs=(f"operating-model:{operating_model.id}",),
            )
        )
    gates: set[str] = set()
    if AssuranceMode.DETERMINISTIC_TESTS in modes or EvidenceClass.DETERMINISTIC_TEST in evidence:
        gates.add("deterministic-validation")
    if independent:
        gates.add("independent-review")
    if human:
        gates.add("human-acceptance")
    if work.requires_sit:
        gates.add("sit")
        gates.add("runtime-readback")
    if work.requires_runtime_readback:
        gates.add("runtime-readback")
    return requirement, tuple(sorted(gates)), tuple(decisions)


def _authority(
    work: WorkCharacteristics,
    operating_model: OperatingModel,
    decision_rights: DecisionRights,
) -> tuple[AuthorityCeiling, tuple[str, ...]]:
    causes = [
        f"work.consequence={work.consequence.value}",
        f"work.external_effect={work.external_effect.value}",
        f"decision-rights:{decision_rights.schema_version}",
    ]
    declared = decision_rights.ceiling_for(work.consequence)
    if declared is None:
        return (
            AuthorityCeiling(
                consequence=work.consequence,
                max_external_effect=ExternalEffectClass.READ_ONLY,
                max_autonomy=Autonomy.SUGGEST,
                approval_class=decision_rights.unknown_authority,
                policy_evidence_refs=tuple(causes),
            ),
            tuple(causes + ["no consequence-specific ceiling declared"]),
        )

    effect = _min_effect(declared.max_external_effect, operating_model.constraints.max_external_effect)
    autonomy = _min_autonomy(declared.max_autonomy, operating_model.constraints.max_autonomy)
    approval = declared.approval_class
    if work.reserved_authority and approval is ApprovalClass.AUTOMATIC:
        approval = ApprovalClass.APPROVAL_REQUIRED
        causes.append("work.reserved_authority=true")
    if _EFFECT_RANK[work.external_effect] > _EFFECT_RANK[effect]:
        approval = ApprovalClass.REFUSED
        causes.append("requested effect exceeds effective ceiling")
    if work.requested_autonomy is not None and _AUTONOMY_RANK[work.requested_autonomy] > _AUTONOMY_RANK[autonomy]:
        approval = ApprovalClass.REFUSED
        causes.append("requested autonomy exceeds effective ceiling")
    ceiling = AuthorityCeiling(
        consequence=work.consequence,
        max_external_effect=effect,
        max_autonomy=autonomy,
        approval_class=approval,
        policy_evidence_refs=tuple(sorted(set((*declared.policy_evidence_refs, *causes)))),
    )
    return ceiling, tuple(sorted(set(causes)))


def _role_ids(registry: CapabilityRegistry) -> tuple[str, ...]:
    ids = {role.id for role in registry.roles}
    return tuple(role_id for role_id in _ROLE_ORDER if role_id in ids) + tuple(sorted(ids - set(_ROLE_ORDER)))


def _select_roles(
    work: WorkCharacteristics,
    operating_model: OperatingModel,
    assurance: AssuranceRequirement,
    authority: AuthorityCeiling,
    profile: ProjectProfile | None,
    registry: CapabilityRegistry,
) -> tuple[LogicalRoleTopology, tuple[RoleDecision, ...], tuple[str, ...]]:
    kind = work.workflow_kind.lower().replace("_", "-")
    read_only_review = work.external_effect is ExternalEffectClass.READ_ONLY and (
        "review" in kind or "exact-sha" in kind or "exact-sha" in (work.request_type or "").lower()
    )
    sit = work.requires_sit or "sit" in kind
    apply_preview = work.reserved_authority or "apply" in kind
    writer_needed = not read_only_review and work.external_effect is not ExternalEffectClass.READ_ONLY
    if "docs" in kind or "document" in kind:
        writer_needed = work.external_effect is not ExternalEffectClass.READ_ONLY

    selected: set[str] = set()
    causes: dict[str, set[str]] = {}

    def select(role_id: str, *role_causes: str) -> None:
        selected.add(role_id)
        causes.setdefault(role_id, set()).update(role_causes)

    if writer_needed:
        select("builder", "work requires repository/external mutation")
    # Deterministic validation is the reachable minimum for simple implementation,
    # documentation, review, resume, and integration work.
    if writer_needed or read_only_review or assurance.required_modes or sit:
        select("validator", "work requires deterministic validation boundary")
    if read_only_review:
        select("reviewer", "workflow kind requests exact-SHA independent review")
    if assurance.independent_review:
        select("reviewer", "compiled assurance requires independent review")
    if sit or work.requires_runtime_readback or AssuranceMode.RUNTIME_READBACK in assurance.required_modes:
        select("runtime-verifier", "compiled assurance requires external-state read-back")
    if apply_preview:
        select("integrator", "apply-preview requires a separate integration/apply gate")
        select("manager", "reserved authority requires a logical authority owner")
    if operating_model.role_separation.minimum_distinct_actors > 1:
        select("reviewer", "role-separation requires distinct actors")
    for role_id in operating_model.role_separation.required_roles:
        select(role_id, "operating_model.role_separation.required_roles")
    for role_id in _profile_list(profile, "role.required", "roles.required"):
        select(role_id, "project_profile.role.required")

    forbidden = set(_profile_list(profile, "role.forbidden", "roles.forbidden"))
    if forbidden:
        selected -= forbidden

    known_roles = set(_role_ids(registry))
    missing = sorted(selected - known_roles)
    unresolved = tuple(f"role:{role_id}" for role_id in missing)
    selected &= known_roles

    required = set(operating_model.role_separation.required_roles)
    required.update(_profile_list(profile, "role.required", "roles.required"))
    if operating_model.role_separation.independent_review_required:
        required.update(operating_model.role_separation.reviewer_roles or ("reviewer",))
    missing_required = sorted(required - selected)
    missing = sorted(set(missing).union(missing_required))
    selected_roles = tuple(role_id for role_id in _role_ids(registry) if role_id in selected)
    excluded_roles = tuple(role_id for role_id in _role_ids(registry) if role_id not in selected)
    writer = "builder" if "builder" in selected_roles else None
    ordered = [role_id for role_id in _ROLE_ORDER if role_id in selected_roles]
    ordered.extend(role_id for role_id in selected_roles if role_id not in _ROLE_ORDER)
    edges = tuple(f"{left}->{right}" for left, right in zip(ordered, ordered[1:]))
    topology = LogicalRoleTopology(
        selected_roles=selected_roles,
        excluded_roles=excluded_roles,
        required_roles=tuple(sorted(required)),
        writer_role=writer,
        single_writer=work.single_writer,
        edges=edges,
    )

    decisions: list[RoleDecision] = []
    policy_refs = (f"operating-model:{operating_model.id}",)
    for role_id in _role_ids(registry):
        is_selected = role_id in selected_roles
        role_causes = causes.get(role_id, set())
        if role_id in forbidden:
            role_causes.add("project_profile.role.forbidden")
            rationale = "excluded by project profile role subtraction"
        elif is_selected:
            rationale = "selected for the minimum logical responsibility topology"
        else:
            role_causes.add("not required by workflow, assurance, authority, or role floor")
            rationale = "materially excluded from the minimum topology"
        decisions.append(
            RoleDecision(
                role_id=role_id,
                selected=is_selected,
                rationale=rationale,
                causes=tuple(sorted(role_causes)),
                policy_refs=policy_refs,
            )
        )
    return topology, tuple(decisions), unresolved


def _role_capabilities(
    selected_roles: Iterable[str], registry: CapabilityRegistry
) -> dict[str, set[str]]:
    by_id = {role.id: role for role in registry.roles}
    result: dict[str, set[str]] = {}
    for role_id in selected_roles:
        role = by_id.get(role_id)
        if isinstance(role, RoleContract):
            for capability_id in role.allowed_capabilities:
                result.setdefault(capability_id, set()).add(f"role:{role_id}")
    return result


def _capability_requirements(
    work: WorkCharacteristics,
    topology: LogicalRoleTopology,
    authority: AuthorityCeiling,
    profile: ProjectProfile | None,
    registry: CapabilityRegistry,
) -> tuple[tuple[CompiledCapabilityRequirement, ...], tuple[UnresolvedPrerequisite, ...]]:
    role_caps = _role_capabilities(topology.selected_roles, registry)
    requested = set(work.required_capabilities)
    requested.update(_profile_list(profile, "capability.required", "capabilities.required"))
    requested.update(role_caps)
    specs = {item.id: item for item in registry.capabilities}
    declarations = {item.capability_id: item for item in work.capability_declarations}
    requirements: list[CompiledCapabilityRequirement] = []
    unresolved: list[UnresolvedPrerequisite] = []
    for capability_id in sorted(requested):
        spec = specs.get(capability_id)
        declaration = declarations.get(capability_id)
        minimum = spec.min_external_effect if isinstance(spec, CapabilitySpec) else ExternalEffectClass.PUBLICATION
        task_effect_ceiling = _min_effect(authority.max_external_effect, work.external_effect)
        within_ceiling = (
            _EFFECT_RANK[minimum] <= _EFFECT_RANK[task_effect_ceiling]
            and authority.approval_class is not ApprovalClass.REFUSED
        )
        available = (
            declaration.available
            if declaration is not None and declaration.available is not None
            else isinstance(spec, CapabilitySpec)
        )
        verified = declaration.verified if declaration is not None else None
        authorized = within_ceiling
        if declaration is not None and declaration.authorized is False:
            authorized = False
        if declaration is not None and declaration.authorized is True:
            authorized = within_ceiling
        causes = set(role_caps.get(capability_id, set()))
        if capability_id in work.required_capabilities:
            causes.add("work.required_capabilities")
        if capability_id in _profile_list(profile, "capability.required", "capabilities.required"):
            causes.add("project_profile.capability.required")
        if not causes:
            causes.add("compiled role topology")
        requirement = CompiledCapabilityRequirement(
            capability_id=capability_id,
            declared=True,
            available=available,
            verified=verified,
            authorized=authorized,
            minimum_external_effect=minimum,
            causes=tuple(sorted(causes)),
        )
        requirements.append(requirement)
        if available is not True:
            unresolved.append(
                UnresolvedPrerequisite(
                    id=f"capability-availability:{capability_id}",
                    reason="required capability is not declared available; no equivalent is substituted",
                    causes=requirement.causes,
                )
            )
        if not authorized:
            unresolved.append(
                UnresolvedPrerequisite(
                    id=f"capability-authority:{capability_id}",
                    reason="required capability exceeds the compiled authority ceiling",
                    causes=tuple(sorted((*requirement.causes, "compiled authority ceiling"))),
                )
            )
    return tuple(requirements), tuple(unresolved)


def _escalations(
    work: WorkCharacteristics,
    operating_model: OperatingModel,
    authority: AuthorityCeiling,
    unresolved: tuple[UnresolvedPrerequisite, ...],
    assurance: AssuranceRequirement,
) -> tuple[EscalationRequirement, ...]:
    result: list[EscalationRequirement] = []
    if authority.approval_class is ApprovalClass.REFUSED:
        result.append(
            EscalationRequirement(
                id="authority-refused",
                trigger=ControlTrigger.AUTHORITY_UNKNOWN,
                reason="requested work cannot fit the declared authority ceiling",
                action="stop and request explicit authority or a narrower work item",
                causes=("compiled authority ceiling",),
            )
        )
    elif authority.approval_class is ApprovalClass.APPROVAL_REQUIRED:
        result.append(
            EscalationRequirement(
                id="authority-approval",
                trigger=ControlTrigger.AUTHORITY_UNKNOWN,
                reason="apply authority is reserved and approval is required",
                action="hold preview until the reserved authority decision is recorded",
                causes=("authority_ceiling.approval_class=approval-required",),
            )
        )
    if assurance.independent_review:
        result.append(
            EscalationRequirement(
                id="review-failure",
                trigger=ControlTrigger.REVIEW_FAILED,
                reason="independent review is a compiled assurance floor",
                action="stop and escalate unresolved review findings",
                causes=("assurance.independent_review=true",),
            )
        )
    if assurance.required_evidence:
        result.append(
            EscalationRequirement(
                id="required-evidence-missing",
                trigger=ControlTrigger.REQUIRED_EVIDENCE_MISSING,
                reason="compiled assurance requires typed evidence",
                action="do not advance until the required evidence is present",
                causes=("assurance.required_evidence",),
            )
        )
    if work.requires_sit or work.requires_runtime_readback:
        result.append(
            EscalationRequirement(
                id="external-state-unobservable",
                trigger=ControlTrigger.EXTERNAL_STATE_UNOBSERVABLE,
                reason="the work requires system-level read-back",
                action="hold and escalate when the declared read-back is unavailable",
                causes=("work.requires_sit or work.requires_runtime_readback",),
            )
        )
    for item in unresolved:
        trigger = (
            ControlTrigger.AUTHORITY_UNKNOWN
            if item.id.startswith("capability-authority")
            else ControlTrigger.CREDENTIAL_UNAVAILABLE
        )
        result.append(
            EscalationRequirement(
                id=f"escalate:{item.id}",
                trigger=trigger,
                reason=item.reason,
                action="stop; obtain the missing declared prerequisite",
                causes=item.causes,
            )
        )
    for condition in operating_model.escalation_conditions:
        result.append(
            EscalationRequirement(
                id=condition.id,
                trigger=condition.trigger,
                reason=condition.reason,
                action="follow operating-model escalation condition",
                causes=(f"operating-model:{operating_model.id}",),
            )
        )
    unique: dict[str, EscalationRequirement] = {item.id: item for item in result}
    return tuple(unique[key] for key in sorted(unique))


def _trace(
    role_decisions: tuple[RoleDecision, ...],
    assurance_decisions: tuple[AssuranceDecision, ...],
    capability_requirements: tuple[CompiledCapabilityRequirement, ...],
    authority: AuthorityCeiling,
    authority_causes: tuple[str, ...],
) -> tuple[CompilationTraceEntry, ...]:
    entries: list[CompilationTraceEntry] = []
    for decision in role_decisions:
        entries.append(
            CompilationTraceEntry(
                component="role",
                component_id=decision.role_id,
                selected=decision.selected,
                rationale=decision.rationale,
                causes=decision.causes,
                policy_refs=decision.policy_refs,
            )
        )
    for decision in assurance_decisions:
        entries.append(
            CompilationTraceEntry(
                component=decision.component,
                component_id=decision.component_id,
                selected=decision.selected,
                rationale=decision.rationale,
                causes=decision.causes,
                policy_refs=decision.policy_refs,
            )
        )
    for requirement in capability_requirements:
        entries.append(
            CompilationTraceEntry(
                component="capability",
                component_id=requirement.capability_id,
                selected=requirement.authorized is True and requirement.available is True,
                rationale=(
                    "required capability is within the compiled authority ceiling"
                    if requirement.authorized
                    else "required capability is not authorized by the compiled ceiling"
                ),
                causes=requirement.causes,
                policy_refs=("compiled-authority-ceiling",),
            )
        )
    entries.append(
        CompilationTraceEntry(
            component="authority-ceiling",
            component_id=authority.consequence.value,
            selected=True,
            rationale="effective ceiling is the intersection of DecisionRights and OperatingConstraints",
            causes=authority_causes,
            policy_refs=("decision-rights", "operating-constraints"),
        )
    )
    return tuple(sorted(entries, key=lambda item: (item.component, item.component_id, not item.selected)))


def compile_role_assurance(
    profile: ProjectProfile | None,
    operating_model: OperatingModel,
    work: WorkCharacteristics | WorkItemContract,
    *,
    decision_rights: DecisionRights | None = None,
    registry: CapabilityRegistry | None = None,
) -> RoleAssuranceCompilation:
    """Compile the minimum logical topology and policy floors deterministically.

    The compiler only consumes supplied declarations.  It does not inspect a live
    system, dispatch a role, choose a provider/model, or imply one process per role.
    """

    characteristics = _characteristics(work)
    reg = registry or build_default_registry()
    rights = decision_rights or operating_model.decision_rights
    assurance, gates, assurance_decisions = _assurance(
        characteristics,
        operating_model,
        profile=profile,
    )
    authority, authority_causes = _authority(characteristics, operating_model, rights)
    topology, role_decisions, missing_roles = _select_roles(
        characteristics,
        operating_model,
        assurance,
        authority,
        profile,
        reg,
    )
    capability_requirements, missing_capabilities = _capability_requirements(
        characteristics,
        topology,
        authority,
        profile,
        reg,
    )
    unresolved = list(missing_capabilities)
    for role_id in missing_roles:
        unresolved.append(
            # A missing logical role is a staffing prerequisite, not a permission
            # substitution.
            UnresolvedPrerequisite(
                id=role_id,
                reason="required logical role is absent from the supplied registry",
                causes=("role topology floor",),
            )
        )
    unresolved = sorted(unresolved, key=lambda item: item.id)
    escalations = _escalations(
        characteristics,
        operating_model,
        authority,
        tuple(unresolved),
        assurance,
    )
    trace = _trace(role_decisions, assurance_decisions, capability_requirements, authority, authority_causes)
    result = RoleAssuranceCompilation(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        project_profile_ref=profile.source_intake_ref if profile is not None else None,
        work=characteristics,
        topology=topology,
        assurance_requirement=assurance,
        authority_ceiling=authority,
        required_gates=gates,
        capability_requirements=capability_requirements,
        escalations=escalations,
        unresolved_prerequisites=tuple(unresolved),
        role_decisions=role_decisions,
        assurance_decisions=assurance_decisions,
        explanation_trace=trace,
    )
    report = validate_compilation_explainability(result)
    if not report.accepted():
        raise ValueError("compiler produced an incomplete explanation trace: " + "; ".join(report.findings))
    return result


def compile_operating_model(
    profile: ProjectProfile | None,
    operating_model: OperatingModel,
    work: WorkCharacteristics | WorkItemContract,
    *,
    decision_rights: DecisionRights | None = None,
    registry: CapabilityRegistry | None = None,
) -> RoleAssuranceCompilation:
    """Descriptive alias for callers that treat this as policy compilation."""

    return compile_role_assurance(
        profile,
        operating_model,
        work,
        decision_rights=decision_rights,
        registry=registry,
    )


__all__ = [
    "compile_operating_model",
    "compile_role_assurance",
    "validate_compilation_explainability",
]
