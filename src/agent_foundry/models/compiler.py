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
from agent_foundry.models.policy import AssuranceRequirement, AuthorityCeiling, DecisionRights


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
    consistency of the emitted role, assurance, and authority trace: material
    components are covered, causes resolve to typed inputs and are recomputed
    against retained compilation state, the authority consequence is checked
    against retained canonical work consequence, and a missing applicable
    DecisionRights ceiling remains a typed refusal with ``authority-refused``.
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


def _resolve_compilation_input(
    compilation: RoleAssuranceCompilation,
    path: CompilationInputPath,
    item: str | None,
) -> tuple[object, type[Enum] | None]:
    """Resolve one cause locator to an input retained by the compilation."""

    work = compilation.work
    decision_rights = compilation.decision_rights
    assurance = compilation.assurance_requirement
    authority = compilation.authority_ceiling
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
            assurance.minimum_distinct_actors,
            None,
        ),
        CompilationInputPath.OPERATING_MODEL_REQUIRED_ROLES: (
            compilation.canonical_required_roles,
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
        CompilationInputPath.AUTHORITY_CEILING: (
            authority.max_external_effect,
            ExternalEffectClass,
        ),
        CompilationInputPath.AUTHORITY_CEILING_MAX_EFFECT: (
            authority.max_external_effect,
            ExternalEffectClass,
        ),
        CompilationInputPath.AUTHORITY_CEILING_MAX_AUTONOMY: (
            authority.max_autonomy,
            Autonomy,
        ),
        CompilationInputPath.TOPOLOGY_SELECTED_ROLES: (
            compilation.topology.selected_roles,
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
        expected[("role", role_id)] = role_id in selected_roles

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
        canonical_selected = decision.role_id in selected_roles
        if decision.selected is not canonical_selected:
            findings.append(
                f"canonical role decision {decision.role_id!r} records selected="
                f"{decision.selected!r}, expected {canonical_selected!r} from the compiled topology"
            )
    for role_id in sorted(canonical_role_ids):
        if role_id not in role_decisions:
            findings.append(f"compiled role {role_id!r} has no canonical role decision")

    assurance_selections: dict[tuple[str, str], bool] = {
        **{
            ("assurance-mode", mode.value): mode in compilation.assurance_requirement.required_modes
            for mode in AssuranceMode
        },
        **{
            ("assurance-evidence", evidence.value): evidence
            in compilation.assurance_requirement.required_evidence
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
        expected[("capability", requirement.capability_id)] = (
            requirement.authorized is True and requirement.available is True
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
    material trace component, typed and recomputed causes against retained
    compilation state, the authority-ceiling consequence against retained
    canonical work consequence, and typed ``REFUSED`` plus ``authority-refused``
    when an applicable DecisionRights ceiling is missing. The retained
    ``canonical_*`` fields are internal-consistency anchors trusted as part of
    the artifact, not authenticity evidence that an externally persisted,
    hand-edited artifact has canonical origin. That binding belongs to SUE-596
    provenance / ExecutionBundle lineage.
    """

    findings: list[str] = []
    trace = compilation.explanation_trace
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
