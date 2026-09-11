"""Contracts produced by the role, assurance, and authority compiler.

These contracts describe logical responsibility and prerequisites.  They do not
describe process topology, provider/model choices, dispatch, or execution state.
"""

from __future__ import annotations

from collections import Counter
from enum import Enum, StrEnum

from pydantic import Field, model_validator

from agent_foundry.models.base import (
    FOUNDRY_SCHEMA_VERSION,
    FoundryModel,
    SchemaCompatibilityError,
    VersionedContract,
)
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
    ExternalEffectClass,
    Reversibility,
)
from agent_foundry.models.policy import (
    AssuranceProfile,
    AssuranceRequirement,
    AuthorityCeiling,
    BlastRadius,
    ControlCondition,
    DecisionRights,
    OperatingConstraints,
    RoleSeparation,
)


class WorkCharacteristics(FoundryModel):
    """Work facts used by policy compilation.

    ``workflow_kind`` is intentionally a free-form work characteristic.  It is
    independent from ``request_type`` and from consequence/effect, so a document
    change does not accidentally acquire deployment gates and a high-consequence
    request cannot lower its assurance floor by changing its prompt wording.
    """

    workflow_kind: str
    request_type: str | None = None
    external_effect: ExternalEffectClass = ExternalEffectClass.REPOSITORY_WRITE
    consequence: ConsequenceClass = ConsequenceClass.LOW
    requested_autonomy: "Autonomy | None" = None
    uncertainty: Ambiguity = Ambiguity.PROCEDURAL
    coupling: Coupling = Coupling.LOW
    reversibility: Reversibility = Reversibility.TRIVIAL
    observability: CorrectnessObservability = CorrectnessObservability.HIGH
    required_assurance_modes: tuple[AssuranceMode, ...] = Field(default_factory=tuple)
    required_evidence: tuple[EvidenceClass, ...] = Field(default_factory=tuple)
    required_capabilities: tuple[str, ...] = Field(default_factory=tuple)
    capability_declarations: tuple["CapabilityDeclaration", ...] = Field(default_factory=tuple)
    reserved_authority: bool = False
    requires_sit: bool = False
    requires_runtime_readback: bool = False
    single_writer: bool = True

    @model_validator(mode="after")
    def _validate_unique_declarations(self) -> "WorkCharacteristics":
        ids = [item.capability_id for item in self.capability_declarations]
        if len(ids) != len(set(ids)):
            raise ValueError("WorkCharacteristics: capability declarations must be unique")
        if self.external_effect is ExternalEffectClass.READ_ONLY and self.reserved_authority:
            raise ValueError(
                "WorkCharacteristics: reserved authority is not meaningful for read-only work"
            )
        return self


class CapabilityDeclaration(FoundryModel):
    """Supplied capability status, kept separate from permission authority.

    The compiler consumes these declarations as facts.  It never probes a live
    connector or turns availability into permission.
    """

    capability_id: str
    available: bool | None = None
    verified: bool | None = None
    authorized: bool | None = None
    source_ref: str | None = None


WorkCharacteristics.model_rebuild()


class CompilationInputPath(StrEnum):
    """Closed set of compiler inputs that can justify a material decision."""

    WORK_CONSEQUENCE = "work.consequence"
    WORK_EXTERNAL_EFFECT = "work.external_effect"
    WORK_REQUIRED_ASSURANCE_MODES = "work.required_assurance_modes"
    WORK_REQUIRED_EVIDENCE = "work.required_evidence"
    WORK_REQUIRED_CAPABILITIES = "work.required_capabilities"
    WORK_REQUIRES_SIT = "work.requires_sit"
    WORK_REQUIRES_RUNTIME_READBACK = "work.requires_runtime_readback"
    WORK_RESERVED_AUTHORITY = "work.reserved_authority"
    WORK_REQUESTED_AUTONOMY = "work.requested_autonomy"
    OPERATING_MODEL_ASSURANCE = "operating_model.assurance"
    OPERATING_MODEL_ROLE_MINIMUM_ACTORS = (
        "operating_model.role_separation.minimum_distinct_actors"
    )
    OPERATING_MODEL_REQUIRED_ROLES = "operating_model.role_separation.required_roles"
    OPERATING_MODEL_ESCALATION_CONDITIONS = "operating_model.escalation_conditions"
    ASSURANCE_INDEPENDENT_REVIEW = "assurance.independent_review"
    ASSURANCE_REQUIRED_MODES = "assurance.required_modes"
    ASSURANCE_REQUIRED_EVIDENCE = "assurance.required_evidence"
    DECISION_RIGHTS_SCHEMA_VERSION = "decision_rights.schema_version"
    DECISION_RIGHTS_AUTHORITY_CEILINGS = "decision_rights.authority_ceilings"
    AUTHORITY_CEILING = "authority_ceiling"
    AUTHORITY_CEILING_APPROVAL_CLASS = "authority_ceiling.approval_class"
    AUTHORITY_CEILING_MAX_EFFECT = "authority_ceiling.max_external_effect"
    AUTHORITY_CEILING_MAX_AUTONOMY = "authority_ceiling.max_autonomy"
    TOPOLOGY_SELECTED_ROLES = "topology.selected_roles"
    CAPABILITY_MIN_EXTERNAL_EFFECT = "capability.minimum_external_effect"


class CompilationPredicateOperator(StrEnum):
    """Closed vocabulary for predicates in a compilation cause."""

    EQUALS = "equals"
    DOES_NOT_EQUAL = "does-not-equal"
    CONTAINS = "contains"
    DOES_NOT_CONTAIN = "does-not-contain"
    IS = "is"
    IS_NOT = "is-not"
    IN = "in"
    NOT_IN = "not-in"
    INCLUDES = "includes"
    EXCEEDS = "exceeds"
    WITHIN = "within"
    NON_EMPTY = "non-empty"
    EMPTY = "empty"
    REQUIRES = "requires"
    DOES_NOT_REQUIRE = "does-not-require"
    ALLOWS = "allows"


class CompilationCauseConsequence(StrEnum):
    """Decision consequence separately recorded from predicate evaluation."""

    SELECTED = "selected"
    EXCLUDED = "excluded"


class CompilationInputLocator(FoundryModel):
    """Typed locator for one closed compiler input path and optional item."""

    path: CompilationInputPath
    item: str | None = None

    @model_validator(mode="after")
    def _validate_item_shape(self) -> "CompilationInputLocator":
        item_paths = {
            CompilationInputPath.WORK_REQUIRED_ASSURANCE_MODES,
            CompilationInputPath.WORK_REQUIRED_EVIDENCE,
            CompilationInputPath.WORK_REQUIRED_CAPABILITIES,
            CompilationInputPath.OPERATING_MODEL_REQUIRED_ROLES,
            CompilationInputPath.OPERATING_MODEL_ESCALATION_CONDITIONS,
            CompilationInputPath.ASSURANCE_REQUIRED_MODES,
            CompilationInputPath.ASSURANCE_REQUIRED_EVIDENCE,
            CompilationInputPath.TOPOLOGY_SELECTED_ROLES,
            CompilationInputPath.CAPABILITY_MIN_EXTERNAL_EFFECT,
        }
        required_item_paths = item_paths - {
            CompilationInputPath.ASSURANCE_REQUIRED_MODES,
            CompilationInputPath.ASSURANCE_REQUIRED_EVIDENCE,
        }
        if self.path in required_item_paths and not self.item:
            raise ValueError(f"{self.path.value} requires an item locator")
        if self.path not in item_paths and self.item is not None:
            raise ValueError(f"{self.path.value} does not support an item locator")
        if self.item is not None and not self.item.strip():
            raise ValueError("CompilationInputLocator.item must not be blank")
        return self

    def render(self) -> str:
        return f"{self.path.value}[{self.item}]" if self.item is not None else self.path.value


CompilationPredicateValue = str | bool | int | float | tuple[str, ...]


class CompilationPredicate(FoundryModel):
    """Structured operator/value predicate evaluated against a typed input."""

    operator: CompilationPredicateOperator
    value: CompilationPredicateValue | None = None

    @model_validator(mode="after")
    def _validate_value_shape(self) -> "CompilationPredicate":
        if self.operator in {
            CompilationPredicateOperator.EMPTY,
            CompilationPredicateOperator.NON_EMPTY,
        }:
            if self.value is not None:
                raise ValueError(f"{self.operator.value} predicates do not take a value")
            return self
        if self.value is None:
            raise ValueError(f"{self.operator.value} predicates require a value")
        if isinstance(self.value, str) and not self.value.strip():
            raise ValueError("CompilationPredicate.value must not be blank")
        if self.operator in {
            CompilationPredicateOperator.IN,
            CompilationPredicateOperator.NOT_IN,
        } and not isinstance(self.value, tuple):
            raise ValueError(f"{self.operator.value} predicates require a tuple value")
        return self

    def render(self) -> str:
        if self.value is None:
            return self.operator.value
        return f"{self.operator.value} {self.value!r}"


class CompilationCause(FoundryModel):
    """One independently inspectable compiler input/policy evaluation."""

    locator: CompilationInputLocator
    predicate: CompilationPredicate
    evaluated: bool
    consequence: CompilationCauseConsequence


class CompiledCapabilityRequirement(FoundryModel):
    """One logical capability requirement and its independently tracked statuses."""

    capability_id: str
    declared: bool
    available: bool | None = None
    verified: bool | None = None
    authorized: bool | None = None
    minimum_external_effect: ExternalEffectClass
    causes: tuple[CompilationCause, ...] = Field(default_factory=tuple)


class RoleDecision(FoundryModel):
    """Selection or material exclusion of one logical role."""

    role_id: str
    selected: bool
    rationale: str
    causes: tuple[CompilationCause, ...] = Field(default_factory=tuple)
    policy_refs: tuple[str, ...] = Field(default_factory=tuple)


class AssuranceDecision(FoundryModel):
    """Selection or material exclusion of one assurance mode/evidence floor."""

    component: str
    component_id: str
    selected: bool
    rationale: str
    causes: tuple[CompilationCause, ...] = Field(default_factory=tuple)
    policy_refs: tuple[str, ...] = Field(default_factory=tuple)


class EscalationRequirement(FoundryModel):
    """Typed escalation with the condition that caused it."""

    id: str
    trigger: ControlTrigger
    reason: str
    action: str
    causes: tuple[CompilationCause, ...] = Field(default_factory=tuple)


class UnresolvedPrerequisite(FoundryModel):
    """A missing or denied prerequisite; no equivalent is substituted."""

    id: str
    reason: str
    causes: tuple[CompilationCause, ...] = Field(default_factory=tuple)


class LogicalRoleTopology(FoundryModel):
    """Minimum logical responsibility topology, not a process or agent graph."""

    selected_roles: tuple[str, ...] = Field(default_factory=tuple)
    excluded_roles: tuple[str, ...] = Field(default_factory=tuple)
    required_roles: tuple[str, ...] = Field(default_factory=tuple)
    writer_role: str | None = None
    single_writer: bool = True
    edges: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _validate_writer(self) -> "LogicalRoleTopology":
        if self.writer_role is not None and self.writer_role not in self.selected_roles:
            raise ValueError("LogicalRoleTopology: writer_role must be selected")
        if len([role for role in self.selected_roles if role == "builder"]) > 1:
            raise ValueError("LogicalRoleTopology: logical topology has multiple writers")
        missing_required = set(self.required_roles) - set(self.selected_roles)
        if missing_required:
            raise ValueError(
                "LogicalRoleTopology: required_roles must be a subset of selected_roles: "
                + ", ".join(sorted(missing_required))
            )
        return self


class CompilationTraceEntry(FoundryModel):
    """Structured cause trace for a selection or material non-selection."""

    component: str
    component_id: str
    selected: bool
    rationale: str
    causes: tuple[CompilationCause, ...] = Field(default_factory=tuple)
    policy_refs: tuple[str, ...] = Field(default_factory=tuple)


class CompilationExplanationReport(FoundryModel):
    """Result of validating compiler trace coverage."""

    valid: bool
    findings: tuple[str, ...] = Field(default_factory=tuple)

    def accepted(self) -> bool:
        return self.valid and not self.findings


class RoleAssuranceCompilation(VersionedContract):
    """Complete deterministic output of SUE-583 compilation.

    SUE-583 guarantees deterministic compilation and structural/internal
    consistency for the emitted assurance floors, required gates, selected and
    excluded role topology (including its deterministic edges), role and
    assurance selection flags, capability declaration statuses, authority
    dimensions and ``policy_evidence_refs``, and prerequisite/escalation
    identities, triggers, causes, reasons, and actions. Cause records resolve to
    typed retained inputs and are recomputed; each component-local role,
    assurance, and capability cause tuple must equal its corresponding trace
    tuple. A missing applicable DecisionRights ceiling remains a typed refusal
    with ``authority-refused``.
    The retained ``canonical_*`` fields are trusted internal-consistency
    anchors, not authenticity evidence for an externally persisted artifact;
    canonical-origin binding belongs to SUE-596 provenance / ExecutionBundle
    lineage.
    """

    __requires_current_schema__ = True

    work_item_id: str | None = None
    project_profile_ref: str | None = None
    work: WorkCharacteristics
    decision_rights: DecisionRights
    # Minimum provider-neutral policy input needed to recompute the effective
    # authority ceiling; this is trusted artifact state, not origin evidence.
    operating_constraints: OperatingConstraints
    # Minimum provider-neutral policy inputs needed to recompute assurance and
    # role-separation floors; these are trusted artifact state, not origin
    # evidence.
    assurance_profile: AssuranceProfile
    role_separation: RoleSeparation
    escalation_conditions: tuple[ControlCondition, ...] = Field(default_factory=tuple)
    # Internal-consistency anchor for the emitted role trace. This retained field
    # is trusted artifact state, not authenticity evidence for canonical origin;
    # SUE-596 owns provenance / ExecutionBundle lineage.
    canonical_role_ids: tuple[str, ...]
    # Internal-consistency anchor for the retained required-role input. This
    # field is not proof of canonical OperatingModel origin for persistence.
    canonical_required_roles: tuple[str, ...]
    # Internal-consistency anchor for the emitted capability trace. This field
    # is not proof of canonical capability-registry origin for persistence.
    canonical_capability_ids: tuple[str, ...]
    topology: LogicalRoleTopology
    assurance_requirement: AssuranceRequirement
    authority_ceiling: AuthorityCeiling
    required_gates: tuple[str, ...] = Field(default_factory=tuple)
    capability_requirements: tuple[CompiledCapabilityRequirement, ...] = Field(
        default_factory=tuple
    )
    escalations: tuple[EscalationRequirement, ...] = Field(default_factory=tuple)
    unresolved_prerequisites: tuple[UnresolvedPrerequisite, ...] = Field(default_factory=tuple)
    role_decisions: tuple[RoleDecision, ...] = Field(default_factory=tuple)
    assurance_decisions: tuple[AssuranceDecision, ...] = Field(default_factory=tuple)
    explanation_trace: tuple[CompilationTraceEntry, ...] = Field(default_factory=tuple)

    @property
    def selected_roles(self) -> tuple[str, ...]:
        return self.topology.selected_roles

    @property
    def excluded_roles(self) -> tuple[str, ...]:
        return self.topology.excluded_roles

    @property
    def assurance(self) -> AssuranceRequirement:
        return self.assurance_requirement

    @property
    def escalation(self) -> tuple[EscalationRequirement, ...]:
        return self.escalations

    @model_validator(mode="after")
    def _validate_current_schema(self) -> "RoleAssuranceCompilation":
        if self.schema_version != FOUNDRY_SCHEMA_VERSION:
            raise SchemaCompatibilityError(
                "RoleAssuranceCompilation: schema_version "
                f"{self.schema_version!r} is not supported; this contract was "
                f"introduced in schema_version {FOUNDRY_SCHEMA_VERSION} and has no "
                "legacy migration"
            )
        return self

    @model_validator(mode="after")
    def _validate_canonical_role_ids_are_unique(self) -> "RoleAssuranceCompilation":
        if len(self.canonical_role_ids) != len(set(self.canonical_role_ids)):
            raise ValueError(
                "RoleAssuranceCompilation: canonical_role_ids must not contain duplicates"
            )
        return self

    @model_validator(mode="after")
    def _validate_canonical_required_roles_are_unique(self) -> "RoleAssuranceCompilation":
        if len(self.canonical_required_roles) != len(set(self.canonical_required_roles)):
            raise ValueError(
                "RoleAssuranceCompilation: canonical_required_roles must not contain duplicates"
            )
        return self

    @model_validator(mode="after")
    def _validate_canonical_capability_ids_are_unique(self) -> "RoleAssuranceCompilation":
        if len(self.canonical_capability_ids) != len(set(self.canonical_capability_ids)):
            raise ValueError(
                "RoleAssuranceCompilation: canonical_capability_ids must not contain duplicates"
            )
        return self


_MISSING_COMPILATION_INPUT = object()

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


def _work_blast_radius(compilation: RoleAssuranceCompilation) -> BlastRadius:
    work = compilation.work
    return BlastRadius(
        consequence=work.consequence,
        uncertainty=work.uncertainty,
        coupling=work.coupling,
        reversibility=work.reversibility,
        observability=work.observability,
    )


def _expected_assurance_requirement(
    compilation: RoleAssuranceCompilation,
) -> AssuranceRequirement:
    """Recompute assurance floors from retained policy and work inputs."""

    work = compilation.work
    base = compilation.assurance_profile.for_blast_radius(_work_blast_radius(compilation))
    modes = set(base.required_modes)
    modes.update(work.required_assurance_modes)
    evidence = set(base.required_evidence)
    evidence.update(work.required_evidence)
    if work.consequence in {ConsequenceClass.HIGH, ConsequenceClass.CRITICAL}:
        modes.add(AssuranceMode.INDEPENDENT_REVIEW)
        evidence.add(EvidenceClass.INDEPENDENT_REVIEW)
    if work.requires_sit:
        modes.add(AssuranceMode.RUNTIME_READBACK)
        evidence.add(EvidenceClass.INTEGRATION_PROOF)
    if work.requires_runtime_readback:
        modes.add(AssuranceMode.RUNTIME_READBACK)
        evidence.add(EvidenceClass.RUNTIME_READBACK)

    independent = (
        base.independent_review
        or AssuranceMode.INDEPENDENT_REVIEW in modes
        or compilation.role_separation.independent_review_required
    )
    human = base.human_required or AssuranceMode.HUMAN_ACCEPTANCE in modes
    minimum_actors = max(
        base.minimum_distinct_actors,
        compilation.role_separation.minimum_distinct_actors,
        2 if independent else 1,
    )
    return AssuranceRequirement(
        blast_radius=_work_blast_radius(compilation),
        minimum_evidence_strength=base.minimum_evidence_strength,
        required_evidence=tuple(item for item in EvidenceClass if item in evidence),
        required_modes=tuple(mode for mode in AssuranceMode if mode in modes),
        independent_review=independent,
        human_required=human,
        minimum_distinct_actors=minimum_actors,
        relaxation_evidence_refs=base.relaxation_evidence_refs,
    )


def _expected_required_gates(
    compilation: RoleAssuranceCompilation,
    assurance: AssuranceRequirement | None = None,
) -> set[str]:
    assurance = assurance or _expected_assurance_requirement(compilation)
    work = compilation.work
    gates: set[str] = set()
    if (
        AssuranceMode.DETERMINISTIC_TESTS in assurance.required_modes
        or EvidenceClass.DETERMINISTIC_TEST in assurance.required_evidence
    ):
        gates.add("deterministic-validation")
    if assurance.independent_review:
        gates.add("independent-review")
    if assurance.human_required:
        gates.add("human-acceptance")
    if work.requires_sit:
        gates.update(("sit", "runtime-readback"))
    if work.requires_runtime_readback:
        gates.add("runtime-readback")
    return gates


def _expected_role_topology(
    compilation: RoleAssuranceCompilation,
    assurance: AssuranceRequirement | None = None,
) -> tuple[set[str], set[str], set[str]]:
    """Recompute the minimum role topology from retained policy and work."""

    assurance = assurance or _expected_assurance_requirement(compilation)
    work = compilation.work
    canonical_roles = set(compilation.canonical_role_ids)
    selected: set[str] = set()
    if work.external_effect is not ExternalEffectClass.READ_ONLY:
        selected.add("builder")
    if (
        work.external_effect is not ExternalEffectClass.READ_ONLY
        or assurance.required_modes
        or work.requires_sit
    ):
        selected.add("validator")
    if assurance.independent_review:
        selected.add("reviewer")
    if work.requires_sit or work.requires_runtime_readback or AssuranceMode.RUNTIME_READBACK in assurance.required_modes:
        selected.add("runtime-verifier")
    if work.reserved_authority:
        selected.update(("integrator", "manager"))
    selected.update(compilation.role_separation.required_roles)
    if compilation.role_separation.minimum_distinct_actors > 1:
        selected.add("reviewer")

    required = set(compilation.role_separation.required_roles)
    if assurance.independent_review or compilation.role_separation.independent_review_required:
        required.update(compilation.role_separation.reviewer_roles or ("reviewer",))
    selected &= canonical_roles
    return selected, canonical_roles - selected, required


def _expected_authority_dimensions(
    compilation: RoleAssuranceCompilation,
) -> tuple[ConsequenceClass, ExternalEffectClass, Autonomy, ApprovalClass]:
    """Recompute authority from the retained policy and work inputs."""

    work = compilation.work
    declared = compilation.decision_rights.ceiling_for(work.consequence)
    if declared is None:
        # A missing ceiling is a refusal, regardless of DecisionRights' unknown
        # presentation setting. This is the compiler's typed fail-closed rule.
        return (
            work.consequence,
            ExternalEffectClass.READ_ONLY,
            Autonomy.SUGGEST,
            ApprovalClass.REFUSED,
        )

    effect = min(
        declared.max_external_effect,
        compilation.operating_constraints.max_external_effect,
        key=_EFFECT_RANK.__getitem__,
    )
    autonomy = min(
        declared.max_autonomy,
        compilation.operating_constraints.max_autonomy,
        key=_AUTONOMY_RANK.__getitem__,
    )
    approval = declared.approval_class
    if work.reserved_authority and approval is ApprovalClass.AUTOMATIC:
        approval = ApprovalClass.APPROVAL_REQUIRED
    if _EFFECT_RANK[work.external_effect] > _EFFECT_RANK[effect]:
        approval = ApprovalClass.REFUSED
    if (
        work.requested_autonomy is not None
        and _AUTONOMY_RANK[work.requested_autonomy] > _AUTONOMY_RANK[autonomy]
    ):
        approval = ApprovalClass.REFUSED
    return work.consequence, effect, autonomy, approval


def _expected_authority_causes(
    compilation: RoleAssuranceCompilation,
) -> tuple[CompilationCause, ...]:
    """Recompute the causes used to derive the retained authority ceiling."""

    work = compilation.work
    decision_rights = compilation.decision_rights
    causes = [
        CompilationCause(
            locator=CompilationInputLocator(path=CompilationInputPath.WORK_CONSEQUENCE),
            predicate=CompilationPredicate(
                operator=CompilationPredicateOperator.EQUALS,
                value=work.consequence.value,
            ),
            evaluated=True,
            consequence=CompilationCauseConsequence.SELECTED,
        ),
        CompilationCause(
            locator=CompilationInputLocator(path=CompilationInputPath.WORK_EXTERNAL_EFFECT),
            predicate=CompilationPredicate(
                operator=CompilationPredicateOperator.EQUALS,
                value=work.external_effect.value,
            ),
            evaluated=True,
            consequence=CompilationCauseConsequence.SELECTED,
        ),
        CompilationCause(
            locator=CompilationInputLocator(
                path=CompilationInputPath.DECISION_RIGHTS_SCHEMA_VERSION
            ),
            predicate=CompilationPredicate(
                operator=CompilationPredicateOperator.EQUALS,
                value=decision_rights.schema_version,
            ),
            evaluated=True,
            consequence=CompilationCauseConsequence.SELECTED,
        ),
    ]
    declared = decision_rights.ceiling_for(work.consequence)
    if declared is None:
        causes.append(
            CompilationCause(
                locator=CompilationInputLocator(
                    path=CompilationInputPath.DECISION_RIGHTS_AUTHORITY_CEILINGS
                ),
                predicate=CompilationPredicate(
                    operator=CompilationPredicateOperator.CONTAINS,
                    value=work.consequence.value,
                ),
                evaluated=False,
                consequence=CompilationCauseConsequence.SELECTED,
            )
        )
        return tuple(causes)

    effect = min(
        declared.max_external_effect,
        compilation.operating_constraints.max_external_effect,
        key=_EFFECT_RANK.__getitem__,
    )
    autonomy = min(
        declared.max_autonomy,
        compilation.operating_constraints.max_autonomy,
        key=_AUTONOMY_RANK.__getitem__,
    )
    if work.reserved_authority and declared.approval_class is ApprovalClass.AUTOMATIC:
        causes.append(
            CompilationCause(
                locator=CompilationInputLocator(path=CompilationInputPath.WORK_RESERVED_AUTHORITY),
                predicate=CompilationPredicate(
                    operator=CompilationPredicateOperator.IS,
                    value=True,
                ),
                evaluated=True,
                consequence=CompilationCauseConsequence.SELECTED,
            )
        )
    if _EFFECT_RANK[work.external_effect] > _EFFECT_RANK[effect]:
        causes.append(
            CompilationCause(
                locator=CompilationInputLocator(
                    path=CompilationInputPath.AUTHORITY_CEILING_MAX_EFFECT
                ),
                predicate=CompilationPredicate(
                    operator=CompilationPredicateOperator.WITHIN,
                    value=effect.value,
                ),
                evaluated=True,
                consequence=CompilationCauseConsequence.SELECTED,
            )
        )
    if (
        work.requested_autonomy is not None
        and _AUTONOMY_RANK[work.requested_autonomy] > _AUTONOMY_RANK[autonomy]
    ):
        causes.append(
            CompilationCause(
                locator=CompilationInputLocator(
                    path=CompilationInputPath.AUTHORITY_CEILING_MAX_AUTONOMY
                ),
                predicate=CompilationPredicate(
                    operator=CompilationPredicateOperator.WITHIN,
                    value=autonomy.value,
                ),
                evaluated=True,
                consequence=CompilationCauseConsequence.SELECTED,
            )
        )
    return tuple(causes)


def _expected_authority_policy_evidence_refs(
    compilation: RoleAssuranceCompilation,
) -> tuple[str, ...]:
    """Recompute the authority evidence references from retained inputs."""

    causes = _expected_authority_causes(compilation)
    declared = compilation.decision_rights.ceiling_for(compilation.work.consequence)
    cause_refs = tuple(
        f"{cause.locator.render()}:{cause.predicate.render()}" for cause in causes
    )
    if declared is None:
        # The compiler records the missing-ceiling evidence from only the base
        # inputs; the false membership cause is an explanation, not evidence.
        cause_refs = cause_refs[:3]
        return cause_refs
    return tuple(sorted({*declared.policy_evidence_refs, *cause_refs}))


def _ordered_role_ids(role_ids: set[str]) -> tuple[str, ...]:
    """Return the compiler's deterministic role ordering for a selected set."""

    return tuple(
        [role_id for role_id in _ROLE_ORDER if role_id in role_ids]
        + sorted(role_ids - set(_ROLE_ORDER))
    )


def _expected_topology_edges(compilation: RoleAssuranceCompilation) -> tuple[str, ...]:
    """Recompute the emitted edge sequence from retained selected topology."""

    selected, _, _ = _expected_role_topology(compilation)
    ordered = _ordered_role_ids(selected)
    return tuple(f"{left}->{right}" for left, right in zip(ordered, ordered[1:]))


def _expected_prerequisite_reason(item_id: str) -> str | None:
    """Return the deterministic reason for a known prerequisite identity."""

    if item_id.startswith("role:"):
        return "required logical role is absent from the supplied registry"
    prefix, separator, _ = item_id.partition(":")
    if not separator:
        return None
    if prefix == "capability-availability":
        return "required capability is not declared available; no equivalent is substituted"
    if prefix == "capability-authority":
        return "required capability exceeds the compiled authority ceiling"
    return None


_BUILTIN_ESCALATION_TEXT = {
    "authority-refused": (
        "requested work cannot fit the declared authority ceiling",
        "stop and request explicit authority or a narrower work item",
    ),
    "authority-approval": (
        "apply authority is reserved and approval is required",
        "hold preview until the reserved authority decision is recorded",
    ),
    "review-failure": (
        "independent review is a compiled assurance floor",
        "stop and escalate unresolved review findings",
    ),
    "required-evidence-missing": (
        "compiled assurance requires typed evidence",
        "do not advance until the required evidence is present",
    ),
    "external-state-unobservable": (
        "the work requires system-level read-back",
        "hold and escalate when the declared read-back is unavailable",
    ),
}


def _declared_capability(
    compilation: RoleAssuranceCompilation,
    capability_id: str,
) -> CapabilityDeclaration | None:
    return next(
        (
            declaration
            for declaration in compilation.work.capability_declarations
            if declaration.capability_id == capability_id
        ),
        None,
    )


def _expected_capability_authorization(
    compilation: RoleAssuranceCompilation,
    requirement: CompiledCapabilityRequirement,
    authority: tuple[ConsequenceClass, ExternalEffectClass, Autonomy, ApprovalClass],
) -> bool:
    """Recompute capability authorization without trusting emitted status."""

    _, authority_effect, _, approval = authority
    effective_effect = min(
        authority_effect,
        compilation.work.external_effect,
        key=_EFFECT_RANK.__getitem__,
    )
    within_ceiling = (
        _EFFECT_RANK[requirement.minimum_external_effect]
        <= _EFFECT_RANK[effective_effect]
        and approval is not ApprovalClass.REFUSED
    )
    declaration = _declared_capability(compilation, requirement.capability_id)
    return within_ceiling and not (
        declaration is not None and declaration.authorized is False
    )


def _validate_retained_compilation_state(
    compilation: RoleAssuranceCompilation,
    findings: list[str],
) -> None:
    """Close the explicitly enumerated SUE-583 retained output state."""

    expected_assurance = _expected_assurance_requirement(compilation)
    actual_assurance = compilation.assurance_requirement
    if actual_assurance.blast_radius != expected_assurance.blast_radius:
        findings.append(
            "assurance blast radius does not match retained work characteristics"
        )
    for field in (
        "minimum_evidence_strength",
        "independent_review",
        "human_required",
        "minimum_distinct_actors",
    ):
        actual = getattr(actual_assurance, field)
        expected = getattr(expected_assurance, field)
        if actual != expected:
            findings.append(
                f"assurance floor {field} {actual!r} does not match retained "
                f"policy/work inputs {expected!r}"
            )
    for field in ("required_modes", "required_evidence", "relaxation_evidence_refs"):
        actual = getattr(actual_assurance, field)
        expected = getattr(expected_assurance, field)
        if len(actual) != len(set(actual)):
            findings.append(f"assurance floor {field} contains duplicates")
        if set(actual) != set(expected):
            findings.append(
                f"assurance floor {field} {actual!r} does not match retained "
                f"policy/work inputs {expected!r}"
            )

    expected_gates = _expected_required_gates(compilation, expected_assurance)
    actual_gates = set(compilation.required_gates)
    if len(compilation.required_gates) != len(actual_gates):
        findings.append("required_gates contains duplicates")
    if actual_gates != expected_gates:
        findings.append(
            f"required_gates {sorted(actual_gates)!r} does not match retained "
            f"assurance/work inputs {sorted(expected_gates)!r}"
        )

    expected_selected, expected_excluded, expected_required = _expected_role_topology(
        compilation,
        expected_assurance,
    )
    actual_selected = set(compilation.topology.selected_roles)
    actual_excluded = set(compilation.topology.excluded_roles)
    actual_required = set(compilation.topology.required_roles)
    if actual_selected != expected_selected:
        findings.append(
            f"selected role topology {sorted(actual_selected)!r} does not match "
            f"retained assurance/work inputs {sorted(expected_selected)!r}"
        )
    if actual_excluded != expected_excluded:
        findings.append(
            f"excluded role topology {sorted(actual_excluded)!r} does not match "
            f"retained assurance/work inputs {sorted(expected_excluded)!r}"
        )
    if actual_required != expected_required:
        findings.append(
            f"required role topology {sorted(actual_required)!r} does not match "
            f"retained assurance/work inputs {sorted(expected_required)!r}"
        )
    expected_writer = "builder" if "builder" in expected_selected else None
    if compilation.topology.writer_role != expected_writer:
        findings.append(
            f"writer role {compilation.topology.writer_role!r} does not match "
            f"retained work topology {expected_writer!r}"
        )
    if compilation.topology.single_writer != compilation.work.single_writer:
        findings.append("topology single_writer does not match retained work")
    expected_edges = _expected_topology_edges(compilation)
    if compilation.topology.edges != expected_edges:
        findings.append(
            f"topology edges {compilation.topology.edges!r} do not match retained "
            f"selected topology {expected_edges!r}"
        )
    if set(compilation.canonical_required_roles) != set(
        compilation.role_separation.required_roles
    ):
        findings.append(
            "canonical required-role input does not match retained role-separation policy"
        )

    expected_authority = _expected_authority_dimensions(compilation)
    expected_authority_fields = {
        "consequence": expected_authority[0],
        "max_external_effect": expected_authority[1],
        "max_autonomy": expected_authority[2],
        "approval_class": expected_authority[3],
    }
    for field, expected in expected_authority_fields.items():
        actual = getattr(compilation.authority_ceiling, field)
        if actual != expected:
            actual_value = getattr(actual, "value", actual)
            expected_value = getattr(expected, "value", expected)
            findings.append(
                f"authority ceiling {field} {actual_value!r} does not match "
                f"retained compilation inputs {expected_value!r}"
            )
    expected_policy_evidence_refs = _expected_authority_policy_evidence_refs(compilation)
    if compilation.authority_ceiling.policy_evidence_refs != expected_policy_evidence_refs:
        findings.append(
            "authority ceiling policy_evidence_refs "
            f"{compilation.authority_ceiling.policy_evidence_refs!r} does not match "
            f"retained compilation inputs {expected_policy_evidence_refs!r}"
        )

    requirement_by_id: dict[str, CompiledCapabilityRequirement] = {}
    for requirement in compilation.capability_requirements:
        if requirement.capability_id not in requirement_by_id:
            requirement_by_id[requirement.capability_id] = requirement

    expected_prerequisites: set[str] = set()
    for requirement in requirement_by_id.values():
        declaration = _declared_capability(compilation, requirement.capability_id)
        expected_available = declaration.available if declaration is not None else None
        expected_verified = declaration.verified if declaration is not None else None
        expected_authorized = _expected_capability_authorization(
            compilation,
            requirement,
            expected_authority,
        )
        for field, expected in (
            ("declared", True),
            ("available", expected_available),
            ("verified", expected_verified),
            ("authorized", expected_authorized),
        ):
            actual = getattr(requirement, field)
            if actual != expected:
                findings.append(
                    f"capability {requirement.capability_id!r} {field} {actual!r} "
                    f"does not match retained compilation inputs {expected!r}"
                )
        if expected_available is not True:
            expected_prerequisites.add(
                f"capability-availability:{requirement.capability_id}"
            )
        if not expected_authorized:
            expected_prerequisites.add(
                f"capability-authority:{requirement.capability_id}"
            )

    unresolved_ids = [item.id for item in compilation.unresolved_prerequisites]
    for item_id, count in Counter(unresolved_ids).items():
        if count > 1:
            findings.append(f"duplicate unresolved prerequisite {item_id!r}")
    actual_prerequisites = set(unresolved_ids)
    for item_id in sorted(expected_prerequisites - actual_prerequisites):
        findings.append(f"missing unresolved prerequisite {item_id!r}")
    for item_id in sorted(actual_prerequisites - expected_prerequisites):
        findings.append(f"unresolved prerequisite {item_id!r} is not justified by retained inputs")
    for item in compilation.unresolved_prerequisites:
        if not item.causes:
            findings.append(f"unresolved prerequisite {item.id!r} has no structured causes")
        expected_reason = _expected_prerequisite_reason(item.id)
        if expected_reason is not None and item.reason != expected_reason:
            findings.append(
                f"unresolved prerequisite {item.id!r} reason {item.reason!r} does not "
                f"match its deterministic reason {expected_reason!r}"
            )

    escalation_ids = [item.id for item in compilation.escalations]
    for item_id, count in Counter(escalation_ids).items():
        if count > 1:
            findings.append(f"duplicate escalation {item_id!r}")
    actual_escalations = set(escalation_ids)
    required_escalations = {
        "authority-refused": expected_authority[3] is ApprovalClass.REFUSED,
        "authority-approval": expected_authority[3] is ApprovalClass.APPROVAL_REQUIRED,
        "review-failure": expected_assurance.independent_review,
        "required-evidence-missing": bool(expected_assurance.required_evidence),
        "external-state-unobservable": (
            compilation.work.requires_sit or compilation.work.requires_runtime_readback
        ),
    }
    for escalation_id, required in required_escalations.items():
        present = escalation_id in actual_escalations
        if present != required:
            state = "missing" if required else "unexpected"
            findings.append(
                f"{state} required escalation {escalation_id!r} for retained compilation inputs"
            )
    expected_prerequisite_escalations = {
        f"escalate:{item_id}" for item_id in expected_prerequisites
    }
    for escalation_id in sorted(expected_prerequisite_escalations - actual_escalations):
        findings.append(f"missing escalation {escalation_id!r} for unresolved prerequisite")
    for escalation_id in sorted(
        item_id
        for item_id in actual_escalations
        if item_id.startswith("escalate:")
        and item_id not in expected_prerequisite_escalations
    ):
        findings.append(f"escalation {escalation_id!r} has no unresolved prerequisite")
    for item in compilation.escalations:
        if not item.causes:
            findings.append(f"escalation {item.id!r} has no structured causes")
        if item.id.startswith("escalate:"):
            prerequisite_id = item.id.removeprefix("escalate:")
            expected_reason = _expected_prerequisite_reason(prerequisite_id)
            if expected_reason is not None and item.reason != expected_reason:
                findings.append(
                    f"escalation {item.id!r} reason {item.reason!r} does not match "
                    f"its deterministic prerequisite reason {expected_reason!r}"
                )
            expected_action = "stop; obtain the missing declared prerequisite"
            if item.action != expected_action:
                findings.append(
                    f"escalation {item.id!r} action {item.action!r} does not match "
                    f"its deterministic action {expected_action!r}"
                )
        elif item.id in _BUILTIN_ESCALATION_TEXT:
            expected_reason, expected_action = _BUILTIN_ESCALATION_TEXT[item.id]
            if item.reason != expected_reason:
                findings.append(
                    f"escalation {item.id!r} reason {item.reason!r} does not match "
                    f"its deterministic reason {expected_reason!r}"
                )
            if item.action != expected_action:
                findings.append(
                    f"escalation {item.id!r} action {item.action!r} does not match "
                    f"its deterministic action {expected_action!r}"
                )
        else:
            condition = next(
                (
                    condition
                    for condition in compilation.escalation_conditions
                    if condition.id == item.id
                ),
                None,
            )
            if condition is not None:
                expected_action = "follow operating-model escalation condition"
                if item.reason != condition.reason:
                    findings.append(
                        f"escalation {item.id!r} reason {item.reason!r} does not match "
                        "the retained ControlCondition reason"
                    )
                if item.action != expected_action:
                    findings.append(
                        f"escalation {item.id!r} action {item.action!r} does not match "
                        f"its deterministic action {expected_action!r}"
                    )
    prerequisites_by_id = {
        item.id: item for item in compilation.unresolved_prerequisites
    }
    for item in compilation.unresolved_prerequisites:
        _validate_prerequisite_causes(compilation, item, findings)
    for item in compilation.escalations:
        _validate_escalation_causes(
            compilation,
            item,
            prerequisites_by_id,
            findings,
        )


def _resolve_compilation_input(
    compilation: RoleAssuranceCompilation,
    path: CompilationInputPath,
    item: str | None,
) -> tuple[object, type[Enum] | None]:
    """Resolve one cause locator to an input retained by the compilation."""

    work = compilation.work
    decision_rights = compilation.decision_rights
    assurance = _expected_assurance_requirement(compilation)
    expected_authority = _expected_authority_dimensions(compilation)
    authority_effect = expected_authority[1]
    authority_autonomy = expected_authority[2]
    authority_approval = expected_authority[3]
    values: dict[CompilationInputPath, tuple[object, type[Enum] | None]] = {
        CompilationInputPath.WORK_CONSEQUENCE: (work.consequence, ConsequenceClass),
        CompilationInputPath.WORK_EXTERNAL_EFFECT: (
            work.external_effect,
            ExternalEffectClass,
        ),
        CompilationInputPath.WORK_REQUIRED_ASSURANCE_MODES: (
            work.required_assurance_modes,
            AssuranceMode,
        ),
        CompilationInputPath.WORK_REQUIRED_EVIDENCE: (work.required_evidence, EvidenceClass),
        CompilationInputPath.WORK_REQUIRED_CAPABILITIES: (work.required_capabilities, None),
        CompilationInputPath.WORK_REQUIRES_SIT: (work.requires_sit, None),
        CompilationInputPath.WORK_REQUIRES_RUNTIME_READBACK: (
            work.requires_runtime_readback,
            None,
        ),
        CompilationInputPath.WORK_RESERVED_AUTHORITY: (work.reserved_authority, None),
        CompilationInputPath.WORK_REQUESTED_AUTONOMY: (work.requested_autonomy, Autonomy),
        CompilationInputPath.OPERATING_MODEL_ROLE_MINIMUM_ACTORS: (
            compilation.role_separation.minimum_distinct_actors,
            None,
        ),
        CompilationInputPath.OPERATING_MODEL_REQUIRED_ROLES: (
            compilation.role_separation.required_roles,
            None,
        ),
        CompilationInputPath.OPERATING_MODEL_ESCALATION_CONDITIONS: (
            tuple(item.id for item in compilation.escalation_conditions),
            None,
        ),
        CompilationInputPath.ASSURANCE_INDEPENDENT_REVIEW: (
            assurance.independent_review,
            None,
        ),
        CompilationInputPath.ASSURANCE_REQUIRED_MODES: (
            assurance.required_modes,
            AssuranceMode,
        ),
        CompilationInputPath.ASSURANCE_REQUIRED_EVIDENCE: (
            assurance.required_evidence,
            EvidenceClass,
        ),
        CompilationInputPath.DECISION_RIGHTS_SCHEMA_VERSION: (
            decision_rights.schema_version,
            None,
        ),
        CompilationInputPath.DECISION_RIGHTS_AUTHORITY_CEILINGS: (
            tuple(item.consequence for item in decision_rights.authority_ceilings),
            ConsequenceClass,
        ),
        CompilationInputPath.AUTHORITY_CEILING_APPROVAL_CLASS: (
            authority_approval,
            ApprovalClass,
        ),
        CompilationInputPath.AUTHORITY_CEILING: (
            authority_effect,
            ExternalEffectClass,
        ),
        CompilationInputPath.AUTHORITY_CEILING_MAX_EFFECT: (
            authority_effect,
            ExternalEffectClass,
        ),
        CompilationInputPath.AUTHORITY_CEILING_MAX_AUTONOMY: (
            authority_autonomy,
            Autonomy,
        ),
        CompilationInputPath.TOPOLOGY_SELECTED_ROLES: (
            tuple(sorted(_expected_role_topology(compilation, assurance)[0])),
            None,
        ),
    }
    if path is CompilationInputPath.CAPABILITY_MIN_EXTERNAL_EFFECT:
        requirement = next(
            (
                requirement
                for requirement in compilation.capability_requirements
                if requirement.capability_id == item
            ),
            None,
        )
        if requirement is None:
            return _MISSING_COMPILATION_INPUT, None
        return requirement.minimum_external_effect, ExternalEffectClass
    return values.get(path, (_MISSING_COMPILATION_INPUT, None))


def _enum_value(value: object, enum_type: type[Enum] | None) -> object:
    if enum_type is not None and isinstance(value, enum_type):
        return value.value
    return value


def _evaluate_compilation_predicate(
    *,
    actual: object,
    enum_type: type[Enum] | None,
    predicate: CompilationPredicate,
    item: str | None,
) -> tuple[bool | None, str | None]:
    """Validate predicate domains and recompute its result against ``actual``."""

    operator = predicate.operator
    value = predicate.value
    if not isinstance(operator, CompilationPredicateOperator):
        return None, "unknown cause predicate operator"
    if isinstance(actual, bool):
        if type(value) is not bool:
            return None, "boolean inputs require a boolean predicate value"
        if operator not in {
            CompilationPredicateOperator.EQUALS,
            CompilationPredicateOperator.DOES_NOT_EQUAL,
            CompilationPredicateOperator.IS,
            CompilationPredicateOperator.IS_NOT,
        }:
            return None, f"operator {operator.value!r} is invalid for a boolean input"
        result = actual is value
        if operator in {
            CompilationPredicateOperator.DOES_NOT_EQUAL,
            CompilationPredicateOperator.IS_NOT,
        }:
            result = not result
        return result, None

    if enum_type is not None and isinstance(actual, Enum):
        domain = tuple(member.value for member in enum_type)
        if operator in {
            CompilationPredicateOperator.IN,
            CompilationPredicateOperator.NOT_IN,
        }:
            if type(value) is not tuple or not value or any(
                type(item_value) is not str or item_value not in domain
                for item_value in value
            ):
                return None, "enum membership predicates require values from the enum domain"
            result = actual.value in value
            return (
                not result if operator is CompilationPredicateOperator.NOT_IN else result,
                None,
            )
        if type(value) is not str or value not in domain:
            return None, "enum predicates require a value from the enum domain"
        actual_rank = domain.index(actual.value)
        value_rank = domain.index(value)
        if operator in {
            CompilationPredicateOperator.EQUALS,
            CompilationPredicateOperator.IS,
        }:
            return actual.value == value, None
        if operator in {
            CompilationPredicateOperator.DOES_NOT_EQUAL,
            CompilationPredicateOperator.IS_NOT,
        }:
            return actual.value != value, None
        if operator is CompilationPredicateOperator.WITHIN:
            return actual_rank <= value_rank, None
        return None, f"operator {operator.value!r} is invalid for an enum input"

    if isinstance(actual, tuple):
        actual_values = tuple(_enum_value(item_value, enum_type) for item_value in actual)
        domain = (
            tuple(member.value for member in enum_type)
            if enum_type is not None
            else None
        )
        if operator in {
            CompilationPredicateOperator.EMPTY,
            CompilationPredicateOperator.NON_EMPTY,
        }:
            if value is not None:
                return None, f"operator {operator.value!r} does not take a value"
            return (
                (not actual_values)
                if operator is CompilationPredicateOperator.EMPTY
                else bool(actual_values),
                None,
            )
        if operator not in {
            CompilationPredicateOperator.CONTAINS,
            CompilationPredicateOperator.DOES_NOT_CONTAIN,
        }:
            return None, f"operator {operator.value!r} is invalid for a collection input"
        if type(value) is not str:
            return None, "collection membership predicates require a scalar string value"
        if domain is not None and value not in domain:
            return None, "enum collection predicates require a value from the enum domain"
        if item is not None and value != item:
            return None, "the predicate value must match its item locator"
        result = value in actual_values
        if operator is CompilationPredicateOperator.DOES_NOT_CONTAIN:
            result = not result
        return result, None

    if isinstance(actual, (int, float)) and not isinstance(actual, bool):
        if type(value) not in {int, float} or isinstance(value, bool):
            return None, "numeric inputs require a numeric predicate value"
        if operator is CompilationPredicateOperator.EXCEEDS:
            return actual > value, None
        if operator is CompilationPredicateOperator.WITHIN:
            return actual <= value, None
        if operator in {
            CompilationPredicateOperator.EQUALS,
            CompilationPredicateOperator.IS,
        }:
            return actual == value, None
        if operator in {
            CompilationPredicateOperator.DOES_NOT_EQUAL,
            CompilationPredicateOperator.IS_NOT,
        }:
            return actual != value, None
        return None, f"operator {operator.value!r} is invalid for a numeric input"

    if isinstance(actual, str):
        if type(value) is not str:
            return None, "string inputs require a string predicate value"
        if operator in {
            CompilationPredicateOperator.EQUALS,
            CompilationPredicateOperator.IS,
        }:
            return actual == value, None
        if operator in {
            CompilationPredicateOperator.DOES_NOT_EQUAL,
            CompilationPredicateOperator.IS_NOT,
        }:
            return actual != value, None
        return None, f"operator {operator.value!r} is invalid for a string input"

    return None, "cause locator resolved to an unsupported or absent input"


def _validate_referenced_causes(
    compilation: RoleAssuranceCompilation,
    *,
    component: str,
    component_id: str,
    causes: tuple[CompilationCause, ...],
    allowed_paths: set[CompilationInputPath],
    findings: list[str],
    expected_consequences: set[CompilationCauseConsequence] | None = None,
    expected_consequences_by_path: dict[
        CompilationInputPath, set[CompilationCauseConsequence]
    ] | None = None,
    required_item: str | None = None,
    capability_id: str | None = None,
) -> None:
    """Validate prerequisite/escalation causes with the trace evaluator rules."""

    if not causes:
        findings.append(f"{component} {component_id!r} has no structured causes")
        return
    for cause in causes:
        if not isinstance(cause.locator, CompilationInputLocator):
            findings.append(f"{component} {component_id!r} has an untyped cause locator")
            continue
        if not isinstance(cause.locator.path, CompilationInputPath):
            findings.append(f"{component} {component_id!r} has an unknown cause input path")
            continue
        if not isinstance(cause.predicate, CompilationPredicate):
            findings.append(f"{component} {component_id!r} has an unstructured cause predicate")
            continue
        if not isinstance(cause.predicate.operator, CompilationPredicateOperator):
            findings.append(f"{component} {component_id!r} has an unknown cause predicate operator")
            continue
        if not isinstance(cause.consequence, CompilationCauseConsequence):
            findings.append(f"{component} {component_id!r} has an unknown cause consequence")
            continue
        if not isinstance(cause.evaluated, bool):
            findings.append(f"{component} {component_id!r} has a non-boolean predicate result")
            continue
        path = cause.locator.path
        if path not in allowed_paths:
            findings.append(
                f"{component} {component_id!r} has a cause from unrelated input "
                f"{path.value!r}"
            )
            continue
        if required_item is not None and cause.locator.item != required_item:
            findings.append(
                f"{component} {component_id!r} has a cause for a different item"
            )
            continue
        if (
            path is CompilationInputPath.TOPOLOGY_SELECTED_ROLES
            and cause.locator.item not in _expected_role_topology(compilation)[0]
        ):
            findings.append(
                f"{component} {component_id!r} names a role outside the retained topology"
            )
            continue
        if (
            path is CompilationInputPath.WORK_REQUIRED_CAPABILITIES
            and cause.locator.item not in compilation.work.required_capabilities
        ):
            findings.append(
                f"{component} {component_id!r} names a capability outside retained work"
            )
            continue
        if (
        path is CompilationInputPath.CAPABILITY_MIN_EXTERNAL_EFFECT
            and cause.locator.item != (capability_id or component_id)
        ):
            findings.append(
                f"{component} {component_id!r} has a cause for a different capability"
            )
            continue
        actual, enum_type = _resolve_compilation_input(
            compilation,
            path,
            cause.locator.item,
        )
        if actual is _MISSING_COMPILATION_INPUT:
            findings.append(
                f"{component} {component_id!r} has a locator that does not resolve "
                f"to a compilation input: {cause.locator.render()!r}"
            )
            continue
        predicate_result, predicate_error = _evaluate_compilation_predicate(
            actual=actual,
            enum_type=enum_type,
            predicate=cause.predicate,
            item=cause.locator.item,
        )
        if predicate_error is not None:
            findings.append(
                f"{component} {component_id!r} has an invalid predicate for "
                f"{cause.locator.render()!r}: {predicate_error}"
            )
            continue
        if predicate_result is not cause.evaluated:
            findings.append(
                f"{component} {component_id!r} records predicate result "
                f"{cause.evaluated!r}, but recomputation produced {predicate_result!r}"
            )
        allowed_consequences = expected_consequences
        if expected_consequences_by_path is not None:
            allowed_consequences = expected_consequences_by_path.get(path)
        if allowed_consequences is not None and cause.consequence not in allowed_consequences:
            findings.append(
                f"{component} {component_id!r} records consequence "
                f"{cause.consequence.value!r}, which is not valid for this component"
            )


def _validate_prerequisite_causes(
    compilation: RoleAssuranceCompilation,
    item: UnresolvedPrerequisite,
    findings: list[str],
) -> None:
    if item.id.startswith("role:"):
        _validate_referenced_causes(
            compilation,
            component="unresolved prerequisite",
            component_id=item.id,
            causes=item.causes,
            allowed_paths={CompilationInputPath.OPERATING_MODEL_REQUIRED_ROLES},
            required_item=item.id.removeprefix("role:"),
            expected_consequences={CompilationCauseConsequence.SELECTED},
            findings=findings,
        )
        return
    prefix, separator, capability_id = item.id.partition(":")
    if prefix not in {"capability-availability", "capability-authority"} or not separator:
        return
    if not any(
        requirement.capability_id == capability_id
        for requirement in compilation.capability_requirements
    ):
        findings.append(
            f"unresolved prerequisite {item.id!r} has no retained capability requirement"
        )
    allowed_paths = {
        CompilationInputPath.TOPOLOGY_SELECTED_ROLES,
        CompilationInputPath.WORK_REQUIRED_CAPABILITIES,
    }
    expected_consequences = {CompilationCauseConsequence.SELECTED}
    expected_consequences_by_path = None
    if prefix == "capability-authority":
        allowed_paths.update(
            {
                CompilationInputPath.AUTHORITY_CEILING,
                CompilationInputPath.AUTHORITY_CEILING_APPROVAL_CLASS,
                CompilationInputPath.CAPABILITY_MIN_EXTERNAL_EFFECT,
            }
        )
        # Requirement causes establish why the capability is required; authority
        # causes establish why it cannot be selected. These are different paths
        # in one prerequisite and must not share a union of consequences.
        expected_consequences = None
        expected_consequences_by_path = {
            CompilationInputPath.TOPOLOGY_SELECTED_ROLES: {
                CompilationCauseConsequence.SELECTED
            },
            CompilationInputPath.WORK_REQUIRED_CAPABILITIES: {
                CompilationCauseConsequence.SELECTED
            },
            CompilationInputPath.AUTHORITY_CEILING: {
                CompilationCauseConsequence.EXCLUDED
            },
            CompilationInputPath.AUTHORITY_CEILING_APPROVAL_CLASS: {
                CompilationCauseConsequence.EXCLUDED
            },
            CompilationInputPath.CAPABILITY_MIN_EXTERNAL_EFFECT: {
                CompilationCauseConsequence.EXCLUDED
            },
        }
    _validate_referenced_causes(
        compilation,
        component="unresolved prerequisite",
        component_id=item.id,
        causes=item.causes,
        allowed_paths=allowed_paths,
        expected_consequences=expected_consequences,
        expected_consequences_by_path=expected_consequences_by_path,
        capability_id=capability_id,
        findings=findings,
    )
    if prefix == "capability-authority" and not any(
        cause.locator.path is CompilationInputPath.CAPABILITY_MIN_EXTERNAL_EFFECT
        for cause in item.causes
        if isinstance(cause.locator, CompilationInputLocator)
    ):
        findings.append(
            f"unresolved prerequisite {item.id!r} has no capability-ceiling cause"
        )


def _validate_escalation_causes(
    compilation: RoleAssuranceCompilation,
    item: EscalationRequirement,
    prerequisites: dict[str, UnresolvedPrerequisite],
    findings: list[str],
) -> None:
    if item.id.startswith("escalate:"):
        prerequisite_id = item.id.removeprefix("escalate:")
        prerequisite = prerequisites.get(prerequisite_id)
        if prerequisite is None:
            findings.append(
                f"escalation {item.id!r} has no matching unresolved prerequisite"
            )
            return
        expected_trigger = (
            ControlTrigger.AUTHORITY_UNKNOWN
            if prerequisite_id.startswith("capability-authority")
            else ControlTrigger.CREDENTIAL_UNAVAILABLE
        )
        if item.trigger is not expected_trigger:
            findings.append(
                f"escalation {item.id!r} has trigger {item.trigger.value!r}, "
                f"expected {expected_trigger.value!r}"
            )
        if item.causes != prerequisite.causes:
            findings.append(
                f"escalation {item.id!r} causes do not match its unresolved prerequisite"
            )
        _validate_prerequisite_causes(compilation, prerequisite, findings)
        return

    builtin_paths: dict[str, set[CompilationInputPath]] = {
        "authority-refused": {CompilationInputPath.AUTHORITY_CEILING_APPROVAL_CLASS},
        "authority-approval": {CompilationInputPath.AUTHORITY_CEILING_APPROVAL_CLASS},
        "review-failure": {CompilationInputPath.ASSURANCE_INDEPENDENT_REVIEW},
        "required-evidence-missing": {CompilationInputPath.ASSURANCE_REQUIRED_EVIDENCE},
        "external-state-unobservable": {
            CompilationInputPath.WORK_REQUIRES_SIT,
            CompilationInputPath.WORK_REQUIRES_RUNTIME_READBACK,
        },
    }
    expected_triggers = {
        "authority-refused": ControlTrigger.AUTHORITY_UNKNOWN,
        "authority-approval": ControlTrigger.AUTHORITY_UNKNOWN,
        "review-failure": ControlTrigger.REVIEW_FAILED,
        "required-evidence-missing": ControlTrigger.REQUIRED_EVIDENCE_MISSING,
        "external-state-unobservable": ControlTrigger.EXTERNAL_STATE_UNOBSERVABLE,
    }
    if item.id in builtin_paths:
        expected_trigger = expected_triggers[item.id]
        if item.trigger is not expected_trigger:
            findings.append(
                f"escalation {item.id!r} has trigger {item.trigger.value!r}, "
                f"expected {expected_trigger.value!r}"
            )
        _validate_referenced_causes(
            compilation,
            component="escalation",
            component_id=item.id,
            causes=item.causes,
            allowed_paths=builtin_paths[item.id],
            expected_consequences={CompilationCauseConsequence.SELECTED},
            findings=findings,
        )
        return

    condition = next(
        (condition for condition in compilation.escalation_conditions if condition.id == item.id),
        None,
    )
    if condition is None:
        findings.append(f"escalation {item.id!r} is not retained by the operating model")
        return
    if item.trigger is not condition.trigger:
        findings.append(
            f"escalation {item.id!r} has trigger {item.trigger.value!r}, "
            f"expected {condition.trigger.value!r}"
        )
    _validate_referenced_causes(
        compilation,
        component="escalation",
        component_id=item.id,
        causes=item.causes,
        allowed_paths={CompilationInputPath.OPERATING_MODEL_ESCALATION_CONDITIONS},
        required_item=item.id,
        expected_consequences={CompilationCauseConsequence.SELECTED},
        findings=findings,
    )


def _canonical_material_selections(
    compilation: RoleAssuranceCompilation,
    findings: list[str],
) -> dict[tuple[str, str], bool]:
    """Derive material trace keys and selection from canonical compiler state."""

    expected: dict[tuple[str, str], bool] = {}
    topology = compilation.topology
    selected_roles = set(topology.selected_roles)
    excluded_roles = set(topology.excluded_roles)
    topology_roles = selected_roles | excluded_roles
    expected_selected_roles, expected_excluded_roles, expected_required_roles = (
        _expected_role_topology(compilation)
    )
    if selected_roles != expected_selected_roles:
        findings.append(
            "compiled selected role topology does not match retained assurance/work inputs"
        )
    if excluded_roles != expected_excluded_roles:
        findings.append(
            "compiled excluded role topology does not match retained assurance/work inputs"
        )
    if set(topology.required_roles) != expected_required_roles:
        findings.append(
            "compiled required role topology does not match retained assurance/work inputs"
        )
    canonical_role_ids = set(compilation.canonical_role_ids)
    unexpected_topology_roles = sorted(topology_roles - canonical_role_ids)
    missing_topology_roles = sorted(canonical_role_ids - topology_roles)
    if unexpected_topology_roles:
        findings.append(
            "compiled topology contains role ids outside retained canonical role input: "
            + ", ".join(unexpected_topology_roles)
        )
    if missing_topology_roles:
        findings.append(
            "compiled topology omits retained canonical role ids: "
            + ", ".join(missing_topology_roles)
        )

    topology_role_ids = (*topology.selected_roles, *topology.excluded_roles)
    duplicate_topology_roles = sorted(
        role_id for role_id, count in Counter(topology_role_ids).items() if count > 1
    )
    if duplicate_topology_roles:
        findings.append(
            "compiled topology repeats role ids: "
            + ", ".join(duplicate_topology_roles)
        )
    overlapping_roles = sorted(selected_roles & excluded_roles)
    if overlapping_roles:
        findings.append(
            "compiled topology marks roles both selected and excluded: "
            + ", ".join(overlapping_roles)
        )
    missing_required = sorted(set(topology.required_roles) - selected_roles)
    if missing_required:
        findings.append(
            "compiled topology required roles are not selected: "
            + ", ".join(missing_required)
        )

    for role_id in sorted(canonical_role_ids):
        expected[("role", role_id)] = role_id in expected_selected_roles

    role_decisions: dict[str, RoleDecision] = {}
    for decision in compilation.role_decisions:
        if decision.role_id in role_decisions:
            findings.append(f"duplicate canonical role decision for {decision.role_id!r}")
            continue
        role_decisions[decision.role_id] = decision
        if decision.role_id not in canonical_role_ids:
            findings.append(
                f"canonical role decision {decision.role_id!r} is outside retained canonical role input"
            )
            continue
        if decision.role_id not in topology_roles:
            findings.append(
                f"canonical role decision {decision.role_id!r} is outside the compiled topology"
            )
            continue
        canonical_selected = decision.role_id in expected_selected_roles
        if decision.selected is not canonical_selected:
            findings.append(
                f"canonical role decision {decision.role_id!r} records selected="
                f"{decision.selected!r}, expected {canonical_selected!r} from the compiled topology"
            )
    for role_id in sorted(canonical_role_ids):
        if role_id not in role_decisions:
            findings.append(f"compiled role {role_id!r} has no canonical role decision")

    expected_assurance = _expected_assurance_requirement(compilation)
    assurance_selections: dict[tuple[str, str], bool] = {
        **{
            ("assurance-mode", mode.value): mode in expected_assurance.required_modes
            for mode in AssuranceMode
        },
        **{
            ("assurance-evidence", evidence.value): evidence
            in expected_assurance.required_evidence
            for evidence in EvidenceClass
        },
    }
    expected.update(assurance_selections)
    assurance_decisions: dict[tuple[str, str], AssuranceDecision] = {}
    for decision in compilation.assurance_decisions:
        key = (decision.component, decision.component_id)
        if key in assurance_decisions:
            findings.append(f"duplicate canonical assurance decision for {key!r}")
            continue
        assurance_decisions[key] = decision
        canonical_selected = assurance_selections.get(key)
        if canonical_selected is None:
            findings.append(f"canonical assurance decision {key!r} is unknown")
            continue
        if decision.selected is not canonical_selected:
            findings.append(
                f"canonical assurance decision {key!r} records selected="
                f"{decision.selected!r}, expected {canonical_selected!r} from the assurance requirement"
            )
    for key in sorted(assurance_selections):
        if key not in assurance_decisions:
            findings.append(f"compiled assurance component {key!r} has no canonical decision")

    canonical_capability_ids = set(compilation.canonical_capability_ids)
    expected_authority = _expected_authority_dimensions(compilation)
    requirement_ids: set[str] = set()
    for requirement in compilation.capability_requirements:
        if requirement.capability_id in requirement_ids:
            findings.append(
                f"duplicate canonical capability requirement for {requirement.capability_id!r}"
            )
            continue
        requirement_ids.add(requirement.capability_id)
        if requirement.capability_id not in canonical_capability_ids:
            findings.append(
                f"canonical capability requirement {requirement.capability_id!r} is outside "
                "retained canonical capability input"
            )
            continue
        declaration = _declared_capability(compilation, requirement.capability_id)
        expected[("capability", requirement.capability_id)] = (
            _expected_capability_authorization(compilation, requirement, expected_authority)
            and (declaration is not None and declaration.available is True)
        )
    for capability_id in sorted(canonical_capability_ids - requirement_ids):
        findings.append(
            f"compiled capability {capability_id!r} has no canonical capability requirement"
        )
    if compilation.authority_ceiling.consequence is not compilation.work.consequence:
        findings.append(
            "authority ceiling consequence "
            f"{compilation.authority_ceiling.consequence.value!r} does not match "
            f"canonical work consequence {compilation.work.consequence.value!r}"
        )
    expected[("authority-ceiling", compilation.work.consequence.value)] = True
    return expected


def validate_compilation_explainability(
    compilation: RoleAssuranceCompilation,
) -> CompilationExplanationReport:
    """Validate SUE-583's structural/internal explainability guarantee.

    The compiler/validator contract covers deterministic compilation, every
    material trace component, retained assurance/role-separation floors and
    required gates, deterministic role topology edges, typed and recomputed
    causes against retained compilation state, component-local cause equality
    with the trace, all authority-ceiling dimensions and policy evidence refs,
    deterministic prerequisite/escalation reasons and actions, retained custom
    escalation reasons, refusal/approval closure against retained policy/work
    inputs, and capability authorization plus prerequisite/escalation closure
    against the effective ceiling. The retained
    ``canonical_*`` fields are internal-consistency anchors trusted as part of
    the artifact, not authenticity evidence that an externally persisted,
    hand-edited artifact has canonical origin. That binding belongs to SUE-596
    provenance / ExecutionBundle lineage.
    """

    findings: list[str] = []
    trace = compilation.explanation_trace
    _validate_retained_compilation_state(compilation, findings)
    expected = _canonical_material_selections(compilation, findings)
    trace_keys = [(entry.component, entry.component_id) for entry in trace]
    duplicate_trace_keys = sorted(
        key for key, count in Counter(trace_keys).items() if count > 1
    )
    for key in duplicate_trace_keys:
        findings.append(f"duplicate material trace entry for {key!r}")
    material = {
        (entry.component, entry.component_id): entry
        for entry in trace
    }
    for key in sorted(set(material) - set(expected)):
        findings.append(f"unknown material trace entry {key!r}")

    for decision in compilation.role_decisions:
        trace_entry = material.get(("role", decision.role_id))
        if trace_entry is not None and decision.causes != trace_entry.causes:
            findings.append(
                f"role decision {decision.role_id!r} causes do not match its "
                "canonical explanation trace"
            )
    for decision in compilation.assurance_decisions:
        trace_entry = material.get((decision.component, decision.component_id))
        if trace_entry is not None and decision.causes != trace_entry.causes:
            findings.append(
                f"assurance decision {(decision.component, decision.component_id)!r} "
                "causes do not match its canonical explanation trace"
            )
    for requirement in compilation.capability_requirements:
        trace_entry = material.get(("capability", requirement.capability_id))
        if trace_entry is not None and requirement.causes != trace_entry.causes:
            findings.append(
                f"capability requirement {requirement.capability_id!r} causes do not "
                "match its canonical explanation trace"
            )

    allowed_paths = {
        "role": {
            CompilationInputPath.WORK_EXTERNAL_EFFECT,
            CompilationInputPath.WORK_REQUIRES_SIT,
            CompilationInputPath.WORK_REQUIRES_RUNTIME_READBACK,
            CompilationInputPath.WORK_RESERVED_AUTHORITY,
            CompilationInputPath.OPERATING_MODEL_ROLE_MINIMUM_ACTORS,
            CompilationInputPath.OPERATING_MODEL_REQUIRED_ROLES,
            CompilationInputPath.ASSURANCE_INDEPENDENT_REVIEW,
            CompilationInputPath.ASSURANCE_REQUIRED_MODES,
        },
        "assurance-mode": {
            CompilationInputPath.WORK_REQUIRED_ASSURANCE_MODES,
            CompilationInputPath.WORK_CONSEQUENCE,
            CompilationInputPath.WORK_REQUIRES_SIT,
            CompilationInputPath.WORK_REQUIRES_RUNTIME_READBACK,
            CompilationInputPath.ASSURANCE_REQUIRED_MODES,
        },
        "assurance-evidence": {
            CompilationInputPath.WORK_REQUIRED_EVIDENCE,
            CompilationInputPath.WORK_CONSEQUENCE,
            CompilationInputPath.WORK_REQUIRES_SIT,
            CompilationInputPath.WORK_REQUIRES_RUNTIME_READBACK,
            CompilationInputPath.ASSURANCE_REQUIRED_EVIDENCE,
        },
        "capability": {
            CompilationInputPath.TOPOLOGY_SELECTED_ROLES,
            CompilationInputPath.WORK_REQUIRED_CAPABILITIES,
            CompilationInputPath.AUTHORITY_CEILING,
            CompilationInputPath.CAPABILITY_MIN_EXTERNAL_EFFECT,
        },
        "authority-ceiling": {
            CompilationInputPath.WORK_CONSEQUENCE,
            CompilationInputPath.WORK_EXTERNAL_EFFECT,
            CompilationInputPath.WORK_RESERVED_AUTHORITY,
            CompilationInputPath.DECISION_RIGHTS_SCHEMA_VERSION,
            CompilationInputPath.DECISION_RIGHTS_AUTHORITY_CEILINGS,
            CompilationInputPath.AUTHORITY_CEILING_MAX_EFFECT,
            CompilationInputPath.AUTHORITY_CEILING_MAX_AUTONOMY,
        },
    }
    role_specific_paths = {
        "builder": {CompilationInputPath.WORK_EXTERNAL_EFFECT},
        "manager": {CompilationInputPath.WORK_RESERVED_AUTHORITY},
        "integrator": {CompilationInputPath.WORK_RESERVED_AUTHORITY},
        "reviewer": {
            CompilationInputPath.ASSURANCE_INDEPENDENT_REVIEW,
            CompilationInputPath.OPERATING_MODEL_ROLE_MINIMUM_ACTORS,
        },
        "validator": {
            CompilationInputPath.WORK_EXTERNAL_EFFECT,
            CompilationInputPath.ASSURANCE_INDEPENDENT_REVIEW,
            CompilationInputPath.ASSURANCE_REQUIRED_MODES,
            CompilationInputPath.WORK_REQUIRES_SIT,
        },
        "runtime-verifier": {
            CompilationInputPath.WORK_REQUIRES_SIT,
            CompilationInputPath.WORK_REQUIRES_RUNTIME_READBACK,
            CompilationInputPath.ASSURANCE_REQUIRED_MODES,
        },
    }
    for component, component_id in sorted(expected):
        entry = material.get((component, component_id))
        if entry is None or not entry.causes:
            findings.append(f"{component} {component_id!r} has no structured cause trace")
            continue
        canonical_selected = expected[(component, component_id)]
        if entry.selected is not canonical_selected:
            findings.append(
                f"{component} {component_id!r} records selected={entry.selected!r}, expected "
                f"{canonical_selected!r} from canonical compilation state"
            )
        for cause in entry.causes:
            if not isinstance(cause.locator, CompilationInputLocator):
                findings.append(
                    f"{component} {component_id!r} has an untyped cause locator"
                )
                continue
            if not isinstance(cause.locator.path, CompilationInputPath):
                findings.append(
                    f"{component} {component_id!r} has an unknown cause input path"
                )
                continue
            if not isinstance(cause.predicate, CompilationPredicate):
                findings.append(
                    f"{component} {component_id!r} has an unstructured cause predicate"
                )
                continue
            if not isinstance(cause.predicate.operator, CompilationPredicateOperator):
                findings.append(
                    f"{component} {component_id!r} has an unknown cause predicate operator"
                )
                continue
            if not isinstance(cause.consequence, CompilationCauseConsequence):
                findings.append(
                    f"{component} {component_id!r} has an unknown cause consequence"
                )
                continue
            if not isinstance(cause.evaluated, bool):
                findings.append(
                    f"{component} {component_id!r} has a non-boolean predicate result"
                )
                continue
            component_paths = allowed_paths.get(component)
            if component_paths is None:
                findings.append(
                    f"{component} {component_id!r} has no validator for its material component"
                )
                continue
            if cause.locator.path not in component_paths:
                findings.append(
                    f"{component} {component_id!r} has a cause from unrelated input "
                    f"{cause.locator.path.value!r}"
                )
                continue
            if component == "role":
                causal_paths = role_specific_paths.get(
                    component_id,
                    set(),
                ) | {CompilationInputPath.OPERATING_MODEL_REQUIRED_ROLES}
                if cause.locator.path not in causal_paths:
                    findings.append(
                        f"role {component_id!r} has a cause that cannot affect its "
                        f"selection: {cause.locator.path.value!r}"
                    )
                    continue
                if (
                    cause.locator.path is CompilationInputPath.OPERATING_MODEL_REQUIRED_ROLES
                    and cause.locator.item != component_id
                ):
                    findings.append(
                        f"role {component_id!r} has a cause for a different required role"
                    )
                    continue
            if (
                component == "capability"
                and cause.locator.path
                in {
                    CompilationInputPath.WORK_REQUIRED_CAPABILITIES,
                    CompilationInputPath.CAPABILITY_MIN_EXTERNAL_EFFECT,
                }
                and cause.locator.item != component_id
            ):
                findings.append(
                    f"capability {component_id!r} has a cause for a different capability"
                )
                continue
            if (
                cause.locator.path is CompilationInputPath.TOPOLOGY_SELECTED_ROLES
                and cause.locator.item not in compilation.topology.selected_roles
            ):
                findings.append(
                    f"{component} {component_id!r} names a role outside the compiled topology"
                )
                continue
            if (
                cause.locator.path
                in {
                    CompilationInputPath.WORK_REQUIRED_ASSURANCE_MODES,
                    CompilationInputPath.WORK_REQUIRED_EVIDENCE,
                    CompilationInputPath.WORK_REQUIRED_CAPABILITIES,
                }
                and cause.locator.item
                not in {
                    _enum_value(item, None)
                    for item in _resolve_compilation_input(
                        compilation,
                        cause.locator.path,
                        cause.locator.item,
                    )[0]
                }
            ):
                findings.append(
                    f"{component} {component_id!r} has an item locator absent from "
                    f"the compilation input: {cause.locator.render()!r}"
                )
                continue
            if (
                component == "assurance-mode"
                and cause.locator.path
                in {
                    CompilationInputPath.WORK_REQUIRED_ASSURANCE_MODES,
                    CompilationInputPath.ASSURANCE_REQUIRED_MODES,
                }
                and cause.locator.item != component_id
            ):
                findings.append(
                    f"assurance-mode {component_id!r} has a cause for a different mode"
                )
                continue
            if (
                component == "assurance-evidence"
                and cause.locator.path
                in {
                    CompilationInputPath.WORK_REQUIRED_EVIDENCE,
                    CompilationInputPath.ASSURANCE_REQUIRED_EVIDENCE,
                }
                and cause.locator.item != component_id
            ):
                findings.append(
                    f"assurance-evidence {component_id!r} has a cause for different evidence"
                )
                continue
            actual, enum_type = _resolve_compilation_input(
                compilation,
                cause.locator.path,
                cause.locator.item,
            )
            if actual is _MISSING_COMPILATION_INPUT:
                findings.append(
                    f"{component} {component_id!r} has a locator that does not resolve "
                    f"to a compilation input: {cause.locator.render()!r}"
                )
                continue
            predicate_result, predicate_error = _evaluate_compilation_predicate(
                actual=actual,
                enum_type=enum_type,
                predicate=cause.predicate,
                item=cause.locator.item,
            )
            if predicate_error is not None:
                findings.append(
                    f"{component} {component_id!r} has an invalid predicate for "
                    f"{cause.locator.render()!r}: {predicate_error}"
                )
                continue
            if predicate_result is not cause.evaluated:
                findings.append(
                    f"{component} {component_id!r} records predicate result "
                    f"{cause.evaluated!r}, but recomputation produced {predicate_result!r}"
                )
                continue
            if component != "capability":
                expected_consequence = (
                    CompilationCauseConsequence.SELECTED
                    if canonical_selected
                    else CompilationCauseConsequence.EXCLUDED
                )
                if cause.consequence is not expected_consequence:
                    findings.append(
                        f"{component} {component_id!r} records consequence "
                        f"{cause.consequence.value!r}, expected "
                        f"{expected_consequence.value!r}"
                    )
    return CompilationExplanationReport(valid=not findings, findings=tuple(findings))


__all__ = [
    "AssuranceDecision",
    "CapabilityDeclaration",
    "CompilationCause",
    "CompilationExplanationReport",
    "CompilationInputLocator",
    "CompilationInputPath",
    "CompilationPredicate",
    "CompilationPredicateOperator",
    "CompilationTraceEntry",
    "CompiledCapabilityRequirement",
    "EscalationRequirement",
    "LogicalRoleTopology",
    "RoleAssuranceCompilation",
    "RoleDecision",
    "UnresolvedPrerequisite",
    "WorkCharacteristics",
    "validate_compilation_explainability",
]
