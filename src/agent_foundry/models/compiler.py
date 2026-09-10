"""Contracts produced by the role, assurance, and authority compiler.

These contracts describe logical responsibility and prerequisites.  They do not
describe process topology, provider/model choices, dispatch, or execution state.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from agent_foundry.models.base import FoundryModel, VersionedContract
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


class CompiledCapabilityRequirement(FoundryModel):
    """One logical capability requirement and its independently tracked statuses."""

    capability_id: str
    declared: bool
    available: bool | None = None
    verified: bool | None = None
    authorized: bool | None = None
    minimum_external_effect: ExternalEffectClass
    causes: tuple[str, ...] = Field(default_factory=tuple)


class RoleDecision(FoundryModel):
    """Selection or material exclusion of one logical role."""

    role_id: str
    selected: bool
    rationale: str
    causes: tuple[str, ...] = Field(default_factory=tuple)
    policy_refs: tuple[str, ...] = Field(default_factory=tuple)


class AssuranceDecision(FoundryModel):
    """Selection or material exclusion of one assurance mode/evidence floor."""

    component: str
    component_id: str
    selected: bool
    rationale: str
    causes: tuple[str, ...] = Field(default_factory=tuple)
    policy_refs: tuple[str, ...] = Field(default_factory=tuple)


class EscalationRequirement(FoundryModel):
    """Typed escalation with the condition that caused it."""

    id: str
    trigger: ControlTrigger
    reason: str
    action: str
    causes: tuple[str, ...] = Field(default_factory=tuple)


class UnresolvedPrerequisite(FoundryModel):
    """A missing or denied prerequisite; no equivalent is substituted."""

    id: str
    reason: str
    causes: tuple[str, ...] = Field(default_factory=tuple)


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
    causes: tuple[str, ...] = Field(default_factory=tuple)
    policy_refs: tuple[str, ...] = Field(default_factory=tuple)


class CompilationExplanationReport(FoundryModel):
    """Result of validating compiler trace coverage."""

    valid: bool
    findings: tuple[str, ...] = Field(default_factory=tuple)

    def accepted(self) -> bool:
        return self.valid and not self.findings


class RoleAssuranceCompilation(VersionedContract):
    """Complete deterministic output of SUE-583 compilation."""

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


def validate_compilation_explainability(
    compilation: RoleAssuranceCompilation,
) -> CompilationExplanationReport:
    """Validate that every material role and assurance decision has a cause."""

    findings: list[str] = []
    trace = compilation.explanation_trace
    role_trace = {entry.component_id: entry for entry in trace if entry.component == "role"}
    for role_id in (*compilation.topology.selected_roles, *compilation.topology.excluded_roles):
        entry = role_trace.get(role_id)
        if entry is None or not entry.causes:
            findings.append(f"role {role_id!r} has no structured cause trace")

    assurance_ids = {
        (entry.component, entry.component_id): entry
        for entry in trace
        if entry.component in {"assurance-mode", "assurance-evidence"}
    }
    selected_modes = {mode.value for mode in compilation.assurance_requirement.required_modes}
    selected_evidence = {item.value for item in compilation.assurance_requirement.required_evidence}
    for component, values in (
        ("assurance-mode", selected_modes),
        ("assurance-evidence", selected_evidence),
    ):
        for item in values:
            entry = assurance_ids.get((component, item))
            if entry is None or not entry.causes:
                findings.append(f"{component} {item!r} has no structured cause trace")

    for requirement in compilation.capability_requirements:
        entries = [
            entry
            for entry in trace
            if entry.component == "capability" and entry.component_id == requirement.capability_id
        ]
        if not entries or any(not entry.causes for entry in entries):
            findings.append(
                f"capability {requirement.capability_id!r} has no structured cause trace"
            )
    return CompilationExplanationReport(valid=not findings, findings=tuple(findings))


__all__ = [
    "AssuranceDecision",
    "CapabilityDeclaration",
    "CompilationExplanationReport",
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
