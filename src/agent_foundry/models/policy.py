"""Authority, assurance, and operating policy contracts.

The classes in this module are declarations. They do not select roles, resolve
Skills, or execute mutations. Those later stages consume this canonical policy
surface and may only narrow it.
"""

from __future__ import annotations

from itertools import product
from typing import Literal, Self

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
    ControlTrigger,
    CorrectnessObservability,
    Coupling,
    AuthorityRequirement,
    ConsequenceClass,
    EvidenceClass,
    EvidenceStrength,
    ExternalEffectClass,
    PolicySource,
    RestorationTarget,
    Reversibility,
)


_EFFECT_RANK = {
    ExternalEffectClass.READ_ONLY: 0,
    ExternalEffectClass.REPOSITORY_WRITE: 1,
    ExternalEffectClass.SHARED_SERVICE_WRITE: 2,
    ExternalEffectClass.DATA_MUTATION: 3,
    ExternalEffectClass.RUNTIME_MUTATION: 4,
    ExternalEffectClass.PUBLICATION: 5,
}

_CONSEQUENCE_RANK = {
    ConsequenceClass.LOW: 0,
    ConsequenceClass.MEDIUM: 1,
    ConsequenceClass.HIGH: 2,
    ConsequenceClass.CRITICAL: 3,
}

_AUTONOMY_RANK = {
    Autonomy.SUGGEST: 0,
    Autonomy.PREPARE: 1,
    Autonomy.ISOLATED_EXECUTE: 2,
    Autonomy.BOUNDED_EXTERNAL_WRITE: 3,
    Autonomy.APPROVED_APPLY: 4,
    Autonomy.CONTINUOUS_OPERATION: 5,
}

_AMBIGUITY_RANK = {
    Ambiguity.PROCEDURAL: 0,
    Ambiguity.BOUNDED_JUDGMENT: 1,
    Ambiguity.DESIGN_TRADE_OFF: 2,
    Ambiguity.EXPLORATORY: 3,
}

_COUPLING_RANK = {
    Coupling.LOW: 0,
    Coupling.MEDIUM: 1,
    Coupling.HIGH: 2,
    Coupling.CRITICAL: 3,
    Coupling.UNKNOWN: 4,
}

_REVERSIBILITY_RANK = {
    Reversibility.TRIVIAL: 0,
    Reversibility.VERSIONED: 1,
    Reversibility.ROLLBACK_REQUIRED: 2,
    Reversibility.PARTIAL: 3,
    Reversibility.EFFECTIVELY_IRREVERSIBLE: 4,
}

_OBSERVABILITY_RANK = {
    CorrectnessObservability.HIGH: 0,
    CorrectnessObservability.PARTIAL: 1,
    CorrectnessObservability.LOW: 2,
    CorrectnessObservability.UNKNOWN: 3,
}

_EVIDENCE_RANK = {
    EvidenceStrength.NONE: 0,
    EvidenceStrength.WEAK: 1,
    EvidenceStrength.MODERATE: 2,
    EvidenceStrength.STRONG: 3,
    EvidenceStrength.DECISIVE: 4,
}

_APPROVAL_RANK = {
    ApprovalClass.AUTOMATIC: 0,
    ApprovalClass.APPROVAL_REQUIRED: 1,
    ApprovalClass.REFUSED: 2,
}


class PermissionProfile(FoundryModel):
    """Scoped permission boundary for external writes."""

    id: str
    version: str = "1.0.0"
    external_effect: ExternalEffectClass
    write_requires: AuthorityRequirement
    preview_required: bool = True
    apply_requires: AuthorityRequirement = AuthorityRequirement.EXPLICIT_AUTHORITY


class BudgetProfile(FoundryModel):
    """Resource budget boundary."""

    id: str
    version: str = "1.0.0"
    max_parallel_runs: int | None = None
    max_retry_budget: int | None = None
    token_budget: int | None = None


class OperatingConstraints(FoundryModel):
    """Project-wide upper bounds that policy consumers must intersect."""

    max_external_effect: ExternalEffectClass = ExternalEffectClass.READ_ONLY
    max_autonomy: Autonomy = Autonomy.SUGGEST
    preview_required: bool = True
    unknown_authority: ApprovalClass = ApprovalClass.REFUSED
    unknown_impact_requires_human: bool = True


class AuthorityCeiling(FoundryModel):
    """Maximum effect/autonomy and approval class for one consequence level."""

    consequence: ConsequenceClass
    max_external_effect: ExternalEffectClass = ExternalEffectClass.READ_ONLY
    max_autonomy: Autonomy = Autonomy.SUGGEST
    approval_class: ApprovalClass = ApprovalClass.REFUSED
    policy_evidence_refs: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _forbid_automatic_high_consequence_mutations(self) -> Self:
        if (
            self.approval_class is ApprovalClass.AUTOMATIC
            and self.max_external_effect
            not in {
                ExternalEffectClass.READ_ONLY,
                ExternalEffectClass.REPOSITORY_WRITE,
            }
        ):
            raise ValueError(
                "AuthorityCeiling: automatic approval cannot be granted beyond "
                "read-only or "
                "repository-write effects; live, deploy, publication, data, and "
                "capital-style effects require approval"
            )
        return self


class AuthorityDecision(FoundryModel):
    """Fail-closed result of checking a requested action against DecisionRights."""

    approval_class: ApprovalClass
    permitted: bool
    max_external_effect: ExternalEffectClass = ExternalEffectClass.READ_ONLY
    max_autonomy: Autonomy = Autonomy.SUGGEST
    reason: str


class DecisionRights(VersionedContract):
    """Owner-declared decision ceilings; absence never becomes permission."""

    __requires_current_schema__ = True
    schema_version: str
    authority_ceilings: tuple[AuthorityCeiling, ...] = Field(default_factory=tuple)
    unknown_authority: ApprovalClass = ApprovalClass.REFUSED

    @model_validator(mode="after")
    def _validate_unique_consequences(self) -> Self:
        if self.schema_version != FOUNDRY_SCHEMA_VERSION:
            raise SchemaCompatibilityError(
                "DecisionRights: schema_version "
                f"{self.schema_version!r} is not supported; this contract was "
                f"introduced in schema_version {FOUNDRY_SCHEMA_VERSION} and has no "
                "legacy migration"
            )
        consequences = [ceiling.consequence for ceiling in self.authority_ceilings]
        if len(consequences) != len(set(consequences)):
            raise ValueError("DecisionRights: one authority ceiling per consequence class")
        for higher in self.authority_ceilings:
            for lower in self.authority_ceilings:
                if _CONSEQUENCE_RANK[higher.consequence] <= _CONSEQUENCE_RANK[lower.consequence]:
                    continue
                weakens = (
                    _EFFECT_RANK[higher.max_external_effect]
                    > _EFFECT_RANK[lower.max_external_effect]
                    or _AUTONOMY_RANK[higher.max_autonomy]
                    > _AUTONOMY_RANK[lower.max_autonomy]
                    or _APPROVAL_RANK[higher.approval_class]
                    < _APPROVAL_RANK[lower.approval_class]
                )
                if weakens and not higher.policy_evidence_refs:
                    raise ValueError(
                        "DecisionRights: higher consequence weakens the lower "
                        "consequence ceiling without policy_evidence_refs"
                    )
        return self

    def ceiling_for(self, consequence: ConsequenceClass) -> AuthorityCeiling | None:
        """Return the exact declared ceiling; no default is inferred."""
        return next(
            (item for item in self.authority_ceilings if item.consequence is consequence),
            None,
        )

    def evaluate(
        self,
        *,
        consequence: ConsequenceClass | str | None,
        requested_effect: ExternalEffectClass | None,
        requested_autonomy: Autonomy | None = None,
        inferred_effect: ExternalEffectClass | None = None,
        tool_effect: ExternalEffectClass | None = None,
        credential_available: bool = False,
    ) -> AuthorityDecision:
        """Evaluate authority without allowing inference, tools, or credentials to widen it."""
        del credential_available  # availability is evidence of capability, never authority
        if consequence is None or requested_effect is None:
            return AuthorityDecision(
                approval_class=self.unknown_authority,
                permitted=False,
                reason="authority or requested effect is unknown; no permission is inferred",
            )
        try:
            consequence = ConsequenceClass(consequence)
        except ValueError:
            consequence = None
        if consequence is None:
            return AuthorityDecision(
                approval_class=self.unknown_authority,
                permitted=False,
                reason="consequence authority is unknown; no permission is inferred",
            )
        ceiling = self.ceiling_for(consequence)
        if ceiling is None:
            return AuthorityDecision(
                approval_class=self.unknown_authority,
                permitted=False,
                reason=f"no authority ceiling declared for consequence {consequence.value}",
            )
        required_effect = requested_effect
        for observed in (inferred_effect, tool_effect):
            if observed is not None and _EFFECT_RANK[observed] > _EFFECT_RANK[required_effect]:
                required_effect = observed
        if _EFFECT_RANK[required_effect] > _EFFECT_RANK[ceiling.max_external_effect]:
            return AuthorityDecision(
                approval_class=ApprovalClass.REFUSED,
                permitted=False,
                max_external_effect=ceiling.max_external_effect,
                max_autonomy=ceiling.max_autonomy,
                reason="requested or inferred effect exceeds the declared authority ceiling",
            )
        if requested_autonomy is not None and _AUTONOMY_RANK[requested_autonomy] > _AUTONOMY_RANK[ceiling.max_autonomy]:
            return AuthorityDecision(
                approval_class=ApprovalClass.REFUSED,
                permitted=False,
                max_external_effect=ceiling.max_external_effect,
                max_autonomy=ceiling.max_autonomy,
                reason="requested autonomy exceeds the declared authority ceiling",
            )
        return AuthorityDecision(
            approval_class=ceiling.approval_class,
            permitted=ceiling.approval_class is not ApprovalClass.REFUSED,
            max_external_effect=ceiling.max_external_effect,
            max_autonomy=ceiling.max_autonomy,
            reason="within the declared consequence-specific ceiling",
        )


class BlastRadius(FoundryModel):
    """Composed impact dimensions used by assurance, not a project-type taxonomy."""

    consequence: ConsequenceClass
    uncertainty: Ambiguity
    coupling: Coupling
    reversibility: Reversibility
    observability: CorrectnessObservability

    def dominates(self, other: "BlastRadius") -> bool:
        """Whether every risk dimension is at least as demanding as ``other``."""
        return (
            _CONSEQUENCE_RANK[self.consequence] >= _CONSEQUENCE_RANK[other.consequence]
            and _AMBIGUITY_RANK[self.uncertainty] >= _AMBIGUITY_RANK[other.uncertainty]
            and _COUPLING_RANK[self.coupling] >= _COUPLING_RANK[other.coupling]
            and _REVERSIBILITY_RANK[self.reversibility] >= _REVERSIBILITY_RANK[other.reversibility]
            and _OBSERVABILITY_RANK[self.observability] >= _OBSERVABILITY_RANK[other.observability]
        )


class AssuranceRequirement(FoundryModel):
    """Evidence and separation floor for one composed blast-radius point."""

    blast_radius: BlastRadius
    minimum_evidence_strength: EvidenceStrength = EvidenceStrength.MODERATE
    required_evidence: tuple[EvidenceClass, ...] = Field(default_factory=tuple)
    required_modes: tuple[AssuranceMode, ...] = Field(default_factory=tuple)
    independent_review: bool = False
    human_required: bool = False
    minimum_distinct_actors: int = Field(default=1, ge=1)
    relaxation_evidence_refs: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _separation_implies_review(self) -> Self:
        if self.minimum_distinct_actors > 1 and not self.independent_review:
            raise ValueError(
                "AssuranceRequirement: multiple distinct actors require independent_review"
            )
        if self.human_required and AssuranceMode.HUMAN_ACCEPTANCE not in self.required_modes:
            raise ValueError(
                "AssuranceRequirement: human_required requires human-acceptance evidence"
            )
        return self


class VerificationBudget(FoundryModel):
    """A cap on verification resources that cannot waive required controls."""

    max_checks: int | None = Field(default=None, ge=0)
    max_evidence_items: int | None = Field(default=None, ge=0)
    allowed_modes: tuple[AssuranceMode, ...] | None = None

    def allocate(self, requirement: AssuranceRequirement) -> AssuranceRequirement:
        """Validate capacity and return every required control unchanged."""
        if self.allowed_modes is not None and not set(requirement.required_modes) <= set(
            self.allowed_modes
        ):
            raise ValueError("VerificationBudget: required assurance mode is outside the budget")
        if (
            self.max_evidence_items is not None
            and len(requirement.required_evidence) > self.max_evidence_items
        ):
            raise ValueError("VerificationBudget: required evidence exceeds the budget")
        if self.max_checks is not None:
            checks = len(requirement.required_modes) + len(requirement.required_evidence)
            if checks > self.max_checks:
                raise ValueError("VerificationBudget: required controls exceed the budget")
        return requirement


class AssuranceProfile(FoundryModel):
    """Blast-radius-indexed assurance floors with explicit relaxation evidence."""

    requirements: tuple[AssuranceRequirement, ...] = Field(default_factory=tuple)
    default_requirement: AssuranceRequirement | None = None
    verification_budget: VerificationBudget | None = None

    @model_validator(mode="after")
    def _validate_monotonic_assurance(self) -> Self:
        # Check the effective resolver over the closed dimension lattice, not just
        # declared points that happen to dominate one another. This catches a rule
        # switch where a higher uncertainty/coupling point would otherwise select a
        # weaker incomparable covering point.
        dimensions = (
            tuple(ConsequenceClass),
            tuple(Ambiguity),
            tuple(Coupling),
            tuple(Reversibility),
            tuple(CorrectnessObservability),
        )
        for left in self.requirements:
            for right in self.requirements:
                if left is right or not left.blast_radius.dominates(right.blast_radius):
                    continue
                if not self._at_least_as_strict(left, right) and not left.relaxation_evidence_refs:
                    raise ValueError(
                        "AssuranceProfile: higher blast-radius requirement weakens "
                        "assurance without explicit relaxation_evidence_refs"
                    )
        for coordinates in product(*(range(len(values)) for values in dimensions)):
            point = BlastRadius(
                consequence=dimensions[0][coordinates[0]],
                uncertainty=dimensions[1][coordinates[1]],
                coupling=dimensions[2][coordinates[2]],
                reversibility=dimensions[3][coordinates[3]],
                observability=dimensions[4][coordinates[4]],
            )
            current = self._resolve_without_validation(point)
            for dimension_index, values in enumerate(dimensions):
                if coordinates[dimension_index] + 1 >= len(values):
                    continue
                higher_coordinates = list(coordinates)
                higher_coordinates[dimension_index] += 1
                higher = BlastRadius(
                    consequence=dimensions[0][higher_coordinates[0]],
                    uncertainty=dimensions[1][higher_coordinates[1]],
                    coupling=dimensions[2][higher_coordinates[2]],
                    reversibility=dimensions[3][higher_coordinates[3]],
                    observability=dimensions[4][higher_coordinates[4]],
                )
                stronger = self._resolve_without_validation(higher)
                if not self._at_least_as_strict(stronger, current) and not (
                    stronger.relaxation_evidence_refs
                ):
                    raise ValueError(
                        "AssuranceProfile: effective assurance weakens as blast radius "
                        "increases without explicit relaxation_evidence_refs"
                    )
        return self

    @staticmethod
    def _strictness(requirement: AssuranceRequirement) -> tuple[int, int, int, int]:
        return (
            _EVIDENCE_RANK[requirement.minimum_evidence_strength],
            len(requirement.required_modes),
            int(requirement.independent_review),
            int(requirement.human_required),
        )

    @staticmethod
    def _at_least_as_strict(
        left: AssuranceRequirement,
        right: AssuranceRequirement,
    ) -> bool:
        """Compare control floors structurally, not only by a scalar score."""
        return (
            _EVIDENCE_RANK[left.minimum_evidence_strength]
            >= _EVIDENCE_RANK[right.minimum_evidence_strength]
            and set(right.required_modes) <= set(left.required_modes)
            and set(right.required_evidence) <= set(left.required_evidence)
            and left.independent_review >= right.independent_review
            and left.human_required >= right.human_required
            and left.minimum_distinct_actors >= right.minimum_distinct_actors
        )

    @staticmethod
    def _fail_closed_requirement(blast_radius: BlastRadius) -> AssuranceRequirement:
        return AssuranceRequirement(
            blast_radius=blast_radius,
            minimum_evidence_strength=EvidenceStrength.DECISIVE,
            required_evidence=tuple(EvidenceClass),
            required_modes=tuple(AssuranceMode),
            independent_review=True,
            human_required=True,
            minimum_distinct_actors=2,
        )

    @classmethod
    def _merge_requirements(
        cls,
        blast_radius: BlastRadius,
        requirements: list[AssuranceRequirement],
    ) -> AssuranceRequirement:
        """Combine applicable floors so an incomparable point cannot remove controls."""
        return AssuranceRequirement(
            blast_radius=blast_radius,
            minimum_evidence_strength=max(
                requirements,
                key=lambda item: _EVIDENCE_RANK[item.minimum_evidence_strength],
            ).minimum_evidence_strength,
            required_evidence=tuple(
                sorted(
                    {evidence for item in requirements for evidence in item.required_evidence},
                    key=lambda item: item.value,
                )
            ),
            required_modes=tuple(
                sorted(
                    {mode for item in requirements for mode in item.required_modes},
                    key=lambda item: item.value,
                )
            ),
            independent_review=any(item.independent_review for item in requirements),
            human_required=any(item.human_required for item in requirements),
            minimum_distinct_actors=max(item.minimum_distinct_actors for item in requirements),
            relaxation_evidence_refs=tuple(
                sorted(
                    {
                        ref
                        for item in requirements
                        for ref in item.relaxation_evidence_refs
                    }
                )
            ),
        )

    def _resolve_without_validation(self, blast_radius: BlastRadius) -> AssuranceRequirement:
        if (
            blast_radius.coupling is Coupling.UNKNOWN
            or blast_radius.observability is CorrectnessObservability.UNKNOWN
        ):
            return self._fail_closed_requirement(blast_radius)
        upper = [
            requirement
            for requirement in self.requirements
            if requirement.blast_radius.dominates(blast_radius)
        ]
        minimal_upper = [
            candidate
            for candidate in upper
            if not any(
                other is not candidate
                and other.blast_radius != candidate.blast_radius
                and candidate.blast_radius.dominates(other.blast_radius)
                for other in upper
            )
        ]
        lower = [
            requirement
            for requirement in self.requirements
            if blast_radius.dominates(requirement.blast_radius)
            and requirement not in minimal_upper
        ]
        applicable = [*minimal_upper, *lower]
        if applicable:
            if not minimal_upper:
                applicable.extend(
                    requirement
                    for requirement in self.requirements
                    if requirement not in applicable
                )
                if self.default_requirement is not None:
                    applicable.append(self.default_requirement)
            return self._merge_requirements(blast_radius, applicable)
        if self.default_requirement is not None:
            return self.default_requirement.model_copy(update={"blast_radius": blast_radius})
        return self._fail_closed_requirement(blast_radius)

    def for_blast_radius(self, blast_radius: BlastRadius) -> AssuranceRequirement:
        """Resolve the union of all applicable floors, failing closed when uncovered."""
        requirement = self._resolve_without_validation(blast_radius)
        if self.verification_budget is not None:
            self.verification_budget.allocate(requirement)
        return requirement


class RoleSeparation(FoundryModel):
    """Logical role boundaries; staffing/selection remains a later compiler concern."""

    required_roles: tuple[str, ...] = Field(default_factory=tuple)
    independent_review_required: bool = False
    forbid_self_approval: bool = True
    minimum_distinct_actors: int = Field(default=1, ge=1)
    reviewer_roles: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _validate_separation_floor(self) -> Self:
        if self.independent_review_required and self.minimum_distinct_actors < 2:
            raise ValueError(
                "RoleSeparation: independent review requires at least two distinct actors"
            )
        if self.independent_review_required and not self.reviewer_roles:
            raise ValueError(
                "RoleSeparation: independent review requires a reviewer role declaration"
            )
        return self


class OverrideRule(FoundryModel):
    """Explicit, evidence-bearing exception between precedence layers."""

    source: PolicySource
    target: PolicySource
    allowed: bool = False
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)


class ContextSkillPolicy(FoundryModel):
    """Deterministic precedence metadata for context and Skills."""

    precedence: tuple[PolicySource, ...] = Field(
        default_factory=lambda: (
            PolicySource.HUMAN,
            PolicySource.PROJECT,
            PolicySource.POLICY,
            PolicySource.WORK_ITEM,
            PolicySource.ROLE,
            PolicySource.CONTEXT,
            PolicySource.SKILL,
            PolicySource.INFERENCE,
            PolicySource.CREDENTIAL,
        )
    )
    non_overridable: tuple[PolicySource, ...] = Field(
        default_factory=lambda: (PolicySource.HUMAN, PolicySource.PROJECT)
    )
    overrides: tuple[OverrideRule, ...] = Field(default_factory=tuple)
    credential_availability_grants_authority: Literal[False] = False

    @model_validator(mode="after")
    def _validate_precedence(self) -> Self:
        canonical = tuple(PolicySource)
        if self.precedence != canonical:
            raise ValueError(
                "ContextSkillPolicy: precedence must be the complete canonical order"
            )
        if set(self.non_overridable) != {PolicySource.HUMAN, PolicySource.PROJECT}:
            raise ValueError(
                "ContextSkillPolicy: human and project must be the complete non-overridable set"
            )
        for rule in self.overrides:
            if rule.target in self.non_overridable:
                raise ValueError("ContextSkillPolicy: human/project policy cannot be overridden")
            if rule.source not in self.precedence or rule.target not in self.precedence:
                raise ValueError("ContextSkillPolicy: override names an absent precedence layer")
            if self.precedence.index(rule.source) > self.precedence.index(rule.target):
                raise ValueError("ContextSkillPolicy: lower-precedence source cannot override higher source")
            if rule.allowed and not rule.evidence_refs:
                raise ValueError("ContextSkillPolicy: allowed override requires evidence_refs")
        return self

    def can_override(self, source: PolicySource, target: PolicySource) -> bool:
        """Return whether an explicitly evidenced override is contract-valid."""
        return any(
            rule.source is source
            and rule.target is target
            and rule.allowed
            and bool(rule.evidence_refs)
            for rule in self.overrides
        )


class ControlCondition(FoundryModel):
    """One typed control trigger with an auditable explanation."""

    id: str
    trigger: ControlTrigger
    reason: str
    requires_fresh_evidence: bool = True


class RetryPolicy(FoundryModel):
    """Bounded retry policy; authority/policy failures are never retry grants."""

    max_attempts: int = Field(default=0, ge=0)
    retryable_triggers: tuple[ControlTrigger, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _never_retry_authority_failures(self) -> Self:
        forbidden = {
            ControlTrigger.AUTHORITY_UNKNOWN,
            ControlTrigger.POLICY_CONFLICT,
            ControlTrigger.REQUIRED_EVIDENCE_MISSING,
        }
        if forbidden.intersection(self.retryable_triggers):
            raise ValueError("RetryPolicy: authority, policy, and missing-evidence failures are not retryable")
        return self


class MutationObligation(FoundryModel):
    """Preview, apply, rollback, and read-back obligations for one effect class."""

    external_effect: ExternalEffectClass
    preview_required: bool = True
    apply_approval: ApprovalClass = ApprovalClass.APPROVAL_REQUIRED
    rollback_required: bool = False
    restoration_target: RestorationTarget = RestorationTarget.NONE
    read_back_required: bool = False
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _validate_mutation_obligations(self) -> Self:
        if self.external_effect is ExternalEffectClass.READ_ONLY:
            if self.rollback_required or self.read_back_required:
                raise ValueError("MutationObligation: read-only effects cannot require mutation read-back/rollback")
            return self
        if not self.preview_required or not self.read_back_required:
            raise ValueError("MutationObligation: mutations require preview and read-back")
        if self.rollback_required and self.restoration_target is not RestorationTarget.PRIOR_ADOPTED_POLICY_VERSION:
            raise ValueError("MutationObligation: rollback must restore the prior adopted policy version")
        if not self.rollback_required and self.restoration_target is not RestorationTarget.NONE:
            raise ValueError("MutationObligation: restoration target requires rollback_required")
        if self.external_effect in {
            ExternalEffectClass.SHARED_SERVICE_WRITE,
            ExternalEffectClass.DATA_MUTATION,
            ExternalEffectClass.RUNTIME_MUTATION,
            ExternalEffectClass.PUBLICATION,
        } and self.apply_approval is ApprovalClass.AUTOMATIC:
            raise ValueError("MutationObligation: external/live/publication mutations cannot be automatic")
        return self


class OperatingModel(VersionedContract):
    """Composable project operating policy consumed by later compilation stages."""

    __requires_current_schema__ = True
    schema_version: str
    id: str
    version: str = "1.0.0"
    description: str
    project_profile_ref: str | None = None
    constraints: OperatingConstraints = Field(default_factory=OperatingConstraints)
    decision_rights: DecisionRights = Field(
        default_factory=lambda: DecisionRights(schema_version=FOUNDRY_SCHEMA_VERSION)
    )
    assurance: AssuranceProfile = Field(default_factory=AssuranceProfile)
    role_separation: RoleSeparation = Field(default_factory=RoleSeparation)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    stop_conditions: tuple[ControlCondition, ...] = Field(default_factory=tuple)
    escalation_conditions: tuple[ControlCondition, ...] = Field(default_factory=tuple)
    human_required_conditions: tuple[ControlCondition, ...] = Field(default_factory=tuple)
    context_skill_policy: ContextSkillPolicy = Field(default_factory=ContextSkillPolicy)
    mutation_obligations: tuple[MutationObligation, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _decision_rights_fit_constraints(self) -> Self:
        if self.schema_version != FOUNDRY_SCHEMA_VERSION:
            raise SchemaCompatibilityError(
                "OperatingModel: schema_version "
                f"{self.schema_version!r} is not supported; this contract was "
                f"introduced in schema_version {FOUNDRY_SCHEMA_VERSION} and has no "
                "legacy migration"
            )
        for ceiling in self.decision_rights.authority_ceilings:
            if _EFFECT_RANK[ceiling.max_external_effect] > _EFFECT_RANK[self.constraints.max_external_effect]:
                raise ValueError(
                    "OperatingModel: DecisionRights effect exceeds OperatingConstraints"
                )
            if _AUTONOMY_RANK[ceiling.max_autonomy] > _AUTONOMY_RANK[self.constraints.max_autonomy]:
                raise ValueError(
                    "OperatingModel: DecisionRights autonomy exceeds OperatingConstraints"
                )
        return self


class PolicyPredicate(FoundryModel):
    """Composable when-clause for declarative toolkit policy — no named project types."""

    consequence: ConsequenceClass | None = None
    external_effect: ExternalEffectClass | None = None
    authority_class: ExternalEffectClass | None = None
    assurance: str | None = None


class PolicyRule(FoundryModel):
    """Declarative policy rule applied during toolkit resolution."""

    id: str
    version: str = "1.0.0"
    description: str
    when: PolicyPredicate = Field(default_factory=PolicyPredicate)
    require_skills: list[str] = Field(default_factory=list)
    require_workflows: list[str] = Field(default_factory=list)
    require_roles: list[str] = Field(default_factory=list)
    require_capabilities: list[str] = Field(default_factory=list)
    forbid_skills: list[str] = Field(default_factory=list)
    forbid_workflows: list[str] = Field(default_factory=list)
    forbid_roles: list[str] = Field(default_factory=list)
    forbid_capabilities: list[str] = Field(default_factory=list)
    forbid_permission_profiles: list[str] = Field(default_factory=list)
