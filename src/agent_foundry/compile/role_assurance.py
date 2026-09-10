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
    CompilationCause,
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
from agent_foundry.models.project import ProjectProfile
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


def _cause(locator: str, predicate: str, evaluated: bool = True) -> CompilationCause:
    return CompilationCause(locator=locator, predicate=predicate, evaluated=evaluated)


def _unique_causes(*causes: CompilationCause) -> tuple[CompilationCause, ...]:
    unique = {(item.locator, item.predicate, item.evaluated): item for item in causes}
    return tuple(unique[key] for key in sorted(unique))


def _characteristics(work: WorkCharacteristics | WorkItemContract) -> WorkCharacteristics:
    if isinstance(work, WorkCharacteristics):
        return work
    runtime = any(item in {"runtime-readback", "integration-proof"} for item in work.required_evidence)
    return WorkCharacteristics(
        workflow_kind=work.work_class.value,
        external_effect=work.authority_class,
        consequence=work.consequence_class,
        required_evidence=tuple(
            item for item in EvidenceClass if item.value in set(work.required_evidence)
        ),
        requires_sit=work.runtime_external_validation_requirement is not None,
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
    blast_radius = _blast_radius(work)
    base = operating_model.assurance.for_blast_radius(blast_radius)
    modes = set(base.required_modes)
    evidence = set(base.required_evidence)
    base_predicate = (
        "AssuranceProfile.for_blast_radius(work blast-radius) includes the compiled floor"
    )
    causes_by_mode: dict[AssuranceMode, list[CompilationCause]] = {
        mode: [_cause("operating_model.assurance", base_predicate)]
        for mode in base.required_modes
    }
    causes_by_evidence: dict[EvidenceClass, list[CompilationCause]] = {
        item: [_cause("operating_model.assurance", base_predicate)]
        for item in base.required_evidence
    }

    def require_mode(mode: AssuranceMode, cause: CompilationCause) -> None:
        modes.add(mode)
        causes_by_mode.setdefault(mode, []).append(cause)

    def require_evidence(item: EvidenceClass, cause: CompilationCause) -> None:
        evidence.add(item)
        causes_by_evidence.setdefault(item, []).append(cause)

    for mode in work.required_assurance_modes:
        require_mode(
            mode,
            _cause("work.required_assurance_modes", f"contains {mode.value!r}"),
        )
    for item in work.required_evidence:
        require_evidence(
            item,
            _cause("work.required_evidence", f"contains {item.value!r}"),
        )

    # This is the high-consequence floor. It is deliberately explicit at the
    # compiler seam: deleting it must make the high-consequence topology weaker,
    # which is covered by the mutation test in test_role_assurance_compiler.py.
    if work.consequence in {ConsequenceClass.HIGH, ConsequenceClass.CRITICAL}:
        require_mode(
            AssuranceMode.INDEPENDENT_REVIEW,
            _cause("work.consequence", "is high or critical"),
        )
        require_evidence(
            EvidenceClass.INDEPENDENT_REVIEW,
            _cause("work.consequence", "is high or critical"),
        )

    if work.requires_sit:
        require_mode(AssuranceMode.RUNTIME_READBACK, _cause("work.requires_sit", "is true"))
        require_evidence(EvidenceClass.INTEGRATION_PROOF, _cause("work.requires_sit", "is true"))
    if work.requires_runtime_readback:
        require_mode(
            AssuranceMode.RUNTIME_READBACK,
            _cause("work.requires_runtime_readback", "is true"),
        )
        require_evidence(
            EvidenceClass.RUNTIME_READBACK,
            _cause("work.requires_runtime_readback", "is true"),
        )

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
        required_evidence=tuple(item for item in EvidenceClass if item in evidence),
        required_modes=tuple(mode for mode in AssuranceMode if mode in modes),
        independent_review=independent,
        human_required=human,
        minimum_distinct_actors=minimum_actors,
        relaxation_evidence_refs=base.relaxation_evidence_refs,
    )

    decisions: list[AssuranceDecision] = []
    for mode in AssuranceMode:
        selected = mode in modes
        causes = causes_by_mode.get(
            mode,
            [_cause("assurance.required_modes", f"contains {mode.value!r}", False)],
        )
        decisions.append(
            AssuranceDecision(
                component="assurance-mode",
                component_id=mode.value,
                selected=selected,
                rationale=("required by compiled assurance floor" if selected else "not required by compiled assurance floor"),
                causes=_unique_causes(*causes),
                policy_refs=(f"operating-model:{operating_model.id}",),
            )
        )
    for item in EvidenceClass:
        selected = item in evidence
        causes = causes_by_evidence.get(
            item,
            [_cause("assurance.required_evidence", f"contains {item.value!r}", False)],
        )
        decisions.append(
            AssuranceDecision(
                component="assurance-evidence",
                component_id=item.value,
                selected=selected,
                rationale=("required by compiled assurance floor" if selected else "not required by compiled assurance floor"),
                causes=_unique_causes(*causes),
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
) -> tuple[AuthorityCeiling, tuple[CompilationCause, ...]]:
    causes = [
        _cause("work.consequence", f"equals {work.consequence.value!r}"),
        _cause("work.external_effect", f"equals {work.external_effect.value!r}"),
        _cause(
            "decision_rights.schema_version",
            f"equals {decision_rights.schema_version!r}",
        ),
    ]
    declared = decision_rights.ceiling_for(work.consequence)
    if declared is None:
        return (
            AuthorityCeiling(
                consequence=work.consequence,
                max_external_effect=ExternalEffectClass.READ_ONLY,
                max_autonomy=Autonomy.SUGGEST,
                approval_class=decision_rights.unknown_authority,
                policy_evidence_refs=tuple(
                    f"{item.locator}:{item.predicate}" for item in causes
                ),
            ),
            tuple(
                [*causes, _cause("decision_rights.authority_ceilings", "contains the work consequence", False)]
            ),
        )

    effect = _min_effect(declared.max_external_effect, operating_model.constraints.max_external_effect)
    autonomy = _min_autonomy(declared.max_autonomy, operating_model.constraints.max_autonomy)
    approval = declared.approval_class
    if work.reserved_authority and approval is ApprovalClass.AUTOMATIC:
        approval = ApprovalClass.APPROVAL_REQUIRED
        causes.append(_cause("work.reserved_authority", "is true"))
    if _EFFECT_RANK[work.external_effect] > _EFFECT_RANK[effect]:
        approval = ApprovalClass.REFUSED
        causes.append(
            _cause(
                "work.external_effect and authority_ceiling.max_external_effect",
                "requested effect is above the effective ceiling",
            )
        )
    if work.requested_autonomy is not None and _AUTONOMY_RANK[work.requested_autonomy] > _AUTONOMY_RANK[autonomy]:
        approval = ApprovalClass.REFUSED
        causes.append(
            _cause(
                "work.requested_autonomy and authority_ceiling.max_autonomy",
                "requested autonomy is above the effective ceiling",
            )
        )
    ceiling = AuthorityCeiling(
        consequence=work.consequence,
        max_external_effect=effect,
        max_autonomy=autonomy,
        approval_class=approval,
        policy_evidence_refs=tuple(
            sorted(
                {
                    *declared.policy_evidence_refs,
                    *(f"{item.locator}:{item.predicate}" for item in causes),
                }
            )
        ),
    )
    return ceiling, _unique_causes(*causes)


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
    read_only_review = (
        work.external_effect is ExternalEffectClass.READ_ONLY
        and assurance.independent_review
    )
    sit = work.requires_sit
    apply_preview = work.reserved_authority
    writer_needed = work.external_effect is not ExternalEffectClass.READ_ONLY

    selected: set[str] = set()
    causes: dict[str, list[CompilationCause]] = {}

    def select(role_id: str, *role_causes: CompilationCause) -> None:
        selected.add(role_id)
        causes.setdefault(role_id, []).extend(role_causes)

    if writer_needed:
        select(
            "builder",
            _cause("work.external_effect", "is not read-only"),
        )
    # Deterministic validation is the reachable minimum for simple implementation,
    # documentation, review, resume, and integration work.
    if writer_needed or read_only_review or assurance.required_modes or sit:
        select(
            "validator",
            _cause(
                "assurance.required_modes or work.requires_sit",
                "requires a deterministic validation boundary",
            ),
        )
    if read_only_review:
        select(
            "reviewer",
            _cause("assurance.independent_review", "is true"),
        )
    if assurance.independent_review:
        select(
            "reviewer",
            _cause("assurance.independent_review", "is true"),
        )
    if sit or work.requires_runtime_readback or AssuranceMode.RUNTIME_READBACK in assurance.required_modes:
        select(
            "runtime-verifier",
            _cause(
                "assurance.required_modes or work.requires_runtime_readback or work.requires_sit",
                "requires external-state read-back",
            ),
        )
    if apply_preview:
        select(
            "integrator",
            _cause("work.reserved_authority", "is true and requires an integration gate"),
        )
        select(
            "manager",
            _cause("work.reserved_authority", "is true and requires an authority owner"),
        )
    if operating_model.role_separation.minimum_distinct_actors > 1:
        select(
            "reviewer",
            _cause("operating_model.role_separation.minimum_distinct_actors", "is greater than one"),
        )
    for role_id in operating_model.role_separation.required_roles:
        select(
            role_id,
            _cause(
                "operating_model.role_separation.required_roles",
                f"contains {role_id!r}",
            ),
        )

    known_roles = set(_role_ids(registry))
    missing = sorted(selected - known_roles)
    unresolved = tuple(f"role:{role_id}" for role_id in missing)
    selected &= known_roles

    required = set(operating_model.role_separation.required_roles)
    if assurance.independent_review or operating_model.role_separation.independent_review_required:
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
        role_causes = causes.get(role_id, [])
        if is_selected:
            rationale = "selected for the minimum logical responsibility topology"
        else:
            role_causes.append(
                _cause(
                    (
                        "work.external_effect"
                        if role_id == "builder"
                        else "assurance.independent_review"
                        if role_id == "reviewer"
                        else "work.reserved_authority"
                        if role_id in {"manager", "integrator"}
                        else "assurance.required_modes or work.requires_sit"
                        if role_id in {"validator", "runtime-verifier"}
                        else "operating_model.role_separation.required_roles"
                    ),
                    f"does not require role {role_id!r}",
                    False,
                )
            )
            rationale = "materially excluded from the minimum topology"
        decisions.append(
            RoleDecision(
                role_id=role_id,
                selected=is_selected,
                rationale=rationale,
                causes=_unique_causes(*role_causes),
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
        available = declaration.available if declaration is not None else None
        verified = declaration.verified if declaration is not None else None
        authorized = within_ceiling
        if declaration is not None and declaration.authorized is False:
            authorized = False
        if declaration is not None and declaration.authorized is True:
            authorized = within_ceiling
        causes: list[CompilationCause] = []
        for role_id in sorted(
            source.removeprefix("role:")
            for source in role_caps.get(capability_id, set())
        ):
            causes.append(
                _cause(
                    f"topology.selected_roles[{role_id}]",
                    f"allows capability {capability_id!r}",
                )
            )
        if capability_id in work.required_capabilities:
            causes.append(
                _cause(
                    "work.required_capabilities",
                    f"contains {capability_id!r}",
                )
            )
        if not causes:
            causes.append(
                _cause(
                    "topology.selected_roles",
                    f"requires capability {capability_id!r}",
                )
            )
        requirement = CompiledCapabilityRequirement(
            capability_id=capability_id,
            declared=True,
            available=available,
            verified=verified,
            authorized=authorized,
            minimum_external_effect=minimum,
            causes=_unique_causes(*causes),
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
                    causes=_unique_causes(
                        *requirement.causes,
                        _cause("authority_ceiling", "capability minimum effect is within the ceiling", False),
                    ),
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
                causes=(_cause("authority_ceiling.approval_class", "is refused"),),
            )
        )
    elif authority.approval_class is ApprovalClass.APPROVAL_REQUIRED:
        result.append(
            EscalationRequirement(
                id="authority-approval",
                trigger=ControlTrigger.AUTHORITY_UNKNOWN,
                reason="apply authority is reserved and approval is required",
                action="hold preview until the reserved authority decision is recorded",
                causes=(_cause("authority_ceiling.approval_class", "is approval-required"),),
            )
        )
    if assurance.independent_review:
        result.append(
            EscalationRequirement(
                id="review-failure",
                trigger=ControlTrigger.REVIEW_FAILED,
                reason="independent review is a compiled assurance floor",
                action="stop and escalate unresolved review findings",
                causes=(_cause("assurance.independent_review", "is true"),),
            )
        )
    if assurance.required_evidence:
        result.append(
            EscalationRequirement(
                id="required-evidence-missing",
                trigger=ControlTrigger.REQUIRED_EVIDENCE_MISSING,
                reason="compiled assurance requires typed evidence",
                action="do not advance until the required evidence is present",
                causes=(_cause("assurance.required_evidence", "is non-empty"),),
            )
        )
    if work.requires_sit or work.requires_runtime_readback:
        result.append(
            EscalationRequirement(
                id="external-state-unobservable",
                trigger=ControlTrigger.EXTERNAL_STATE_UNOBSERVABLE,
                reason="the work requires system-level read-back",
                action="hold and escalate when the declared read-back is unavailable",
                causes=(
                    _cause(
                        "work.requires_sit or work.requires_runtime_readback",
                        "is true",
                    ),
                ),
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
                causes=(
                    _cause(
                        f"operating_model.escalation_conditions[{condition.id}]",
                        "is declared",
                    ),
                ),
            )
        )
    unique: dict[str, EscalationRequirement] = {item.id: item for item in result}
    return tuple(unique[key] for key in sorted(unique))


def _trace(
    role_decisions: tuple[RoleDecision, ...],
    assurance_decisions: tuple[AssuranceDecision, ...],
    capability_requirements: tuple[CompiledCapabilityRequirement, ...],
    authority: AuthorityCeiling,
    authority_causes: tuple[CompilationCause, ...],
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
                causes=(_cause("operating_model.role_separation", "requires the missing role"),),
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
        work_item_id=work.id if isinstance(work, WorkItemContract) else None,
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
