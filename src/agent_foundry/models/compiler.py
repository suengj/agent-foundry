"""Contracts produced by the role, assurance, and authority compiler.

These contracts describe logical responsibility and prerequisites.  They do not
describe process topology, provider/model choices, dispatch, or execution state.
"""

from __future__ import annotations

from enum import StrEnum

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
from agent_foundry.models.policy import AssuranceRequirement, AuthorityCeiling


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


class CompilationInputLocator(FoundryModel):
    """Typed locator for one closed compiler input path and optional item."""

    path: CompilationInputPath
    item: str | None = None

    @model_validator(mode="after")
    def _validate_item_shape(self) -> "CompilationInputLocator":
        item_paths = {
            CompilationInputPath.WORK_REQUIRED_ASSURANCE_MODES,
            CompilationInputPath.WORK_REQUIRED_EVIDENCE,
            CompilationInputPath.OPERATING_MODEL_REQUIRED_ROLES,
            CompilationInputPath.OPERATING_MODEL_ESCALATION_CONDITIONS,
            CompilationInputPath.TOPOLOGY_SELECTED_ROLES,
        }
        if self.path in item_paths and not self.item:
            raise ValueError(f"{self.path.value} requires an item locator")
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
    """Complete deterministic output of SUE-583 compilation."""

    __requires_current_schema__ = True

    work_item_id: str | None = None
    project_profile_ref: str | None = None
    work: WorkCharacteristics
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


def validate_compilation_explainability(
    compilation: RoleAssuranceCompilation,
) -> CompilationExplanationReport:
    """Validate complete, structured cause coverage for material decisions."""

    findings: list[str] = []
    trace = compilation.explanation_trace
    material = {
        (entry.component, entry.component_id): entry
        for entry in trace
        if entry.component
        in {"role", "assurance-mode", "assurance-evidence", "capability"}
    }
    expected = {
        ("role", role_id)
        for role_id in (*compilation.topology.selected_roles, *compilation.topology.excluded_roles)
    }
    expected.update(
        ("assurance-mode", decision.component_id)
        for decision in compilation.assurance_decisions
        if decision.component == "assurance-mode"
    )
    expected.update(
        ("assurance-evidence", item.component_id)
        for item in compilation.assurance_decisions
        if item.component == "assurance-evidence"
    )
    expected.update(
        ("capability", requirement.capability_id)
        for requirement in compilation.capability_requirements
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
            CompilationInputPath.OPERATING_MODEL_ASSURANCE,
            CompilationInputPath.WORK_REQUIRED_ASSURANCE_MODES,
            CompilationInputPath.WORK_CONSEQUENCE,
            CompilationInputPath.WORK_REQUIRES_SIT,
            CompilationInputPath.WORK_REQUIRES_RUNTIME_READBACK,
            CompilationInputPath.ASSURANCE_REQUIRED_MODES,
        },
        "assurance-evidence": {
            CompilationInputPath.OPERATING_MODEL_ASSURANCE,
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
        },
    }
    for component, component_id in sorted(expected):
        entry = material.get((component, component_id))
        if entry is None or not entry.causes:
            findings.append(f"{component} {component_id!r} has no structured cause trace")
            continue
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
            if cause.locator.path not in allowed_paths[component]:
                findings.append(
                    f"{component} {component_id!r} has a cause from unrelated input "
                    f"{cause.locator.path.value!r}"
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
