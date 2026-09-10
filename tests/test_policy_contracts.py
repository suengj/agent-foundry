"""SUE-582 contract tests: authority, assurance, control, and mutation policy."""

from __future__ import annotations

import inspect
import re
import pytest
from pathlib import Path
from pydantic import ValidationError

from agent_foundry.models import (
    Ambiguity,
    ApprovalClass,
    AssuranceMode,
    AssuranceProfile,
    AssuranceRequirement,
    Autonomy,
    AuthorityRequirement,
    AuthorityCeiling,
    BlastRadius,
    ContextSkillPolicy,
    ControlTrigger,
    CorrectnessObservability,
    Coupling,
    DecisionRights,
    EvidenceClass,
    EvidenceStrength,
    ExternalEffectClass,
    MutationObligation,
    OperatingModel,
    PermissionProfile,
    PolicySource,
    RestorationTarget,
    RetryPolicy,
    RoleSeparation,
    Reversibility,
    dump_json,
    dump_yaml,
    FOUNDRY_SCHEMA_VERSION,
    VerificationBudget,
    load_json,
    load_yaml,
)
import agent_foundry.models.policy as policy_models


def _radius(
    consequence: str,
    *,
    uncertainty: Ambiguity = Ambiguity.PROCEDURAL,
    coupling: Coupling = Coupling.LOW,
    reversibility: Reversibility = Reversibility.TRIVIAL,
    observability: CorrectnessObservability = CorrectnessObservability.HIGH,
) -> BlastRadius:
    return BlastRadius(
        consequence=consequence,
        uncertainty=uncertainty,
        coupling=coupling,
        reversibility=reversibility,
        observability=observability,
    )


def _assurance_matrix() -> list[AssuranceRequirement]:
    """Low, high, and critical fixtures exercise the independent dimensions."""
    return [
        AssuranceRequirement(
            blast_radius=_radius("low"),
            minimum_evidence_strength=EvidenceStrength.MODERATE,
            required_modes=[AssuranceMode.DETERMINISTIC_TESTS],
            required_evidence=[EvidenceClass.DETERMINISTIC_TEST],
        ),
        AssuranceRequirement(
            blast_radius=_radius(
                "high",
                uncertainty=Ambiguity.DESIGN_TRADE_OFF,
                coupling=Coupling.HIGH,
                reversibility=Reversibility.ROLLBACK_REQUIRED,
                observability=CorrectnessObservability.PARTIAL,
            ),
            minimum_evidence_strength=EvidenceStrength.STRONG,
            required_modes=[
                AssuranceMode.DETERMINISTIC_TESTS,
                AssuranceMode.INDEPENDENT_REVIEW,
            ],
            required_evidence=[
                EvidenceClass.DETERMINISTIC_TEST,
                EvidenceClass.INDEPENDENT_REVIEW,
            ],
            independent_review=True,
            minimum_distinct_actors=2,
        ),
        AssuranceRequirement(
            blast_radius=_radius(
                "critical",
                uncertainty=Ambiguity.EXPLORATORY,
                coupling=Coupling.UNKNOWN,
                reversibility=Reversibility.EFFECTIVELY_IRREVERSIBLE,
                observability=CorrectnessObservability.UNKNOWN,
            ),
            minimum_evidence_strength=EvidenceStrength.DECISIVE,
            required_modes=[
                AssuranceMode.DETERMINISTIC_TESTS,
                AssuranceMode.INDEPENDENT_REVIEW,
                AssuranceMode.HUMAN_ACCEPTANCE,
            ],
            required_evidence=[
                EvidenceClass.DETERMINISTIC_TEST,
                EvidenceClass.INDEPENDENT_REVIEW,
                EvidenceClass.HUMAN_ACCEPTANCE,
            ],
            independent_review=True,
            human_required=True,
            minimum_distinct_actors=2,
        ),
    ]


def test_assurance_matrix_supports_simple_and_high_assurance_topologies() -> None:
    profile = AssuranceProfile(requirements=_assurance_matrix())

    low = profile.for_blast_radius(_radius("low"))
    high = profile.for_blast_radius(
        _radius(
            "high",
            uncertainty=Ambiguity.DESIGN_TRADE_OFF,
            coupling=Coupling.HIGH,
            reversibility=Reversibility.ROLLBACK_REQUIRED,
            observability=CorrectnessObservability.PARTIAL,
        )
    )
    assert low is not None and not low.independent_review
    assert high is not None and high.independent_review
    assert high.minimum_evidence_strength is EvidenceStrength.STRONG


@pytest.mark.parametrize(
    ("case_id", "blast_radius", "effect"),
    [
        pytest.param(
            "governance-document-change",
            _radius(
                "high",
                uncertainty=Ambiguity.BOUNDED_JUDGMENT,
                coupling=Coupling.HIGH,
                observability=CorrectnessObservability.PARTIAL,
            ),
            ExternalEffectClass.REPOSITORY_WRITE,
            id="governance-document-change",
        ),
        pytest.param(
            "low-impact-deterministic-edit",
            _radius("low"),
            ExternalEffectClass.REPOSITORY_WRITE,
            id="low-impact-deterministic-edit",
        ),
        pytest.param(
            "ambiguous-architecture-decision",
            _radius(
                "high",
                uncertainty=Ambiguity.DESIGN_TRADE_OFF,
                coupling=Coupling.HIGH,
                observability=CorrectnessObservability.PARTIAL,
            ),
            ExternalEffectClass.READ_ONLY,
            id="ambiguous-architecture-decision",
        ),
        pytest.param(
            "external-write-action",
            _radius(
                "high",
                coupling=Coupling.HIGH,
                reversibility=Reversibility.ROLLBACK_REQUIRED,
                observability=CorrectnessObservability.PARTIAL,
            ),
            ExternalEffectClass.SHARED_SERVICE_WRITE,
            id="external-write-action",
        ),
    ],
)
def test_explicit_case_matrix_keeps_control_strength_proportional(
    case_id: str,
    blast_radius: BlastRadius,
    effect: ExternalEffectClass,
) -> None:
    rights = DecisionRights(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        authority_ceilings=[
            AuthorityCeiling(
                consequence="low",
                max_external_effect=ExternalEffectClass.REPOSITORY_WRITE,
                max_autonomy="bounded-external-write",
                approval_class=ApprovalClass.AUTOMATIC,
            ),
            AuthorityCeiling(
                consequence="high",
                max_external_effect=ExternalEffectClass.REPOSITORY_WRITE,
                max_autonomy="approved-apply",
                approval_class=ApprovalClass.APPROVAL_REQUIRED,
                policy_evidence_refs=["policy:high-approval"],
            ),
        ],
    )
    permission = PermissionProfile(
        id=f"permission-{case_id}",
        external_effect=effect,
        write_requires=(
            AuthorityRequirement.NONE
            if effect is ExternalEffectClass.READ_ONLY
            else AuthorityRequirement.EXPLICIT_AUTHORITY
        ),
    )
    decision = rights.evaluate(
        consequence=blast_radius.consequence,
        requested_effect=effect,
        requested_autonomy="bounded-external-write",
    )
    requirement = AssuranceProfile(
        requirements=_assurance_matrix(),
        verification_budget=VerificationBudget(
            max_checks=16,
            max_evidence_items=6,
            allowed_modes=tuple(AssuranceMode),
        ),
    ).for_blast_radius(blast_radius)
    assert permission.external_effect is effect, case_id
    assert requirement.required_modes
    if case_id == "low-impact-deterministic-edit":
        assert not requirement.independent_review
        assert decision.approval_class is ApprovalClass.AUTOMATIC
        assert decision.permitted
    elif case_id == "external-write-action":
        assert decision.approval_class is ApprovalClass.REFUSED
        assert not decision.permitted
    else:
        assert requirement.independent_review
        assert decision.approval_class is ApprovalClass.APPROVAL_REQUIRED
        assert decision.permitted
    if case_id == "external-write-action":
        obligation = MutationObligation(
            external_effect=effect,
            rollback_required=True,
            restoration_target=RestorationTarget.PRIOR_ADOPTED_POLICY_VERSION,
            read_back_required=True,
        )
        assert obligation.preview_required and obligation.read_back_required


def test_permission_profile_is_a_real_compiled_authority_bound() -> None:
    from agent_foundry.compile.authority import compute_compiled_authority
    from agent_foundry.models import (
        CapabilityRegistry,
        CapabilitySpec,
        ProjectAccess,
        ProjectAssurance,
        ProjectExecution,
        ProjectImpact,
        ProjectInfo,
        ProjectManifest,
        ProjectState,
        RoleContract,
        TaskToolkit,
        WorkItemContract,
    )

    manifest = ProjectManifest(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        project=ProjectInfo(name="permission-bound"),
        state=ProjectState(),
        impact=ProjectImpact(external_effect=ExternalEffectClass.PUBLICATION),
        execution=ProjectExecution(),
        assurance=ProjectAssurance(),
        access=ProjectAccess(),
        authority={"write_scope": ["src"]},
    )
    work_item = WorkItemContract(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        id="WI-PERMISSION-BOUND",
        title="Exercise permission intersection",
        work_class="capability",
        objective="Prove the permission profile reaches compilation",
        current_facts=["compiler is the authority chokepoint"],
        scope=["src"],
        out_of_scope=["runtime"],
        acceptance_criteria=["permission narrowing narrows compiled authority"],
        authority_class=ExternalEffectClass.PUBLICATION,
        consequence_class="low",
        required_evidence=["deterministic-test"],
        stop_conditions=["profile is not consumed"],
    )
    role = RoleContract(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        id="writer",
        version="1.0.0",
        description="Synthetic write-capable role for the chokepoint test",
        allowed_capabilities=["publish-capability"],
        write_scope=["src"],
    )
    registry = CapabilityRegistry(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        foundry_compat=">=0.2,<0.3",
        capabilities=[
            CapabilitySpec(
                schema_version=FOUNDRY_SCHEMA_VERSION,
                id="publish-capability",
                version="1.0.0",
                description="Synthetic capability that permits the broad effect",
                min_external_effect=ExternalEffectClass.PUBLICATION,
            )
        ],
        roles=[role],
    )
    task_toolkit = TaskToolkit(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        work_item_id=work_item.id,
        capability_ids=["publish-capability"],
    )
    broad = PermissionProfile(
        id="broad",
        external_effect=ExternalEffectClass.PUBLICATION,
        write_requires=AuthorityRequirement.EXPLICIT_AUTHORITY,
    )
    narrow = PermissionProfile(
        id="narrow",
        external_effect=ExternalEffectClass.READ_ONLY,
        write_requires=AuthorityRequirement.NONE,
    )

    broad_authority = compute_compiled_authority(
        work_item, manifest, task_toolkit, role, broad, registry
    )
    narrow_authority = compute_compiled_authority(
        work_item, manifest, task_toolkit, role, narrow, registry
    )

    assert broad_authority.external_effect is ExternalEffectClass.PUBLICATION
    assert narrow_authority.external_effect is ExternalEffectClass.READ_ONLY


def test_uncertainty_and_observability_raise_assurance_without_control_loss() -> None:
    low = AssuranceRequirement(
        blast_radius=_radius("low"),
        required_evidence=[EvidenceClass.DETERMINISTIC_TEST],
        required_modes=[AssuranceMode.DETERMINISTIC_TESTS],
    )
    high_uncertainty = AssuranceRequirement(
        blast_radius=_radius("low", uncertainty=Ambiguity.EXPLORATORY),
        minimum_evidence_strength=EvidenceStrength.STRONG,
        required_evidence=[EvidenceClass.DETERMINISTIC_TEST, EvidenceClass.INDEPENDENT_REVIEW],
        required_modes=[AssuranceMode.DETERMINISTIC_TESTS, AssuranceMode.INDEPENDENT_REVIEW],
        independent_review=True,
    )
    profile = AssuranceProfile(requirements=[low, high_uncertainty])
    baseline = profile.for_blast_radius(_radius("low"))
    raised = profile.for_blast_radius(
        _radius("low", uncertainty=Ambiguity.EXPLORATORY)
    )
    assert AssuranceProfile._at_least_as_strict(raised, baseline)

    unknown = profile.for_blast_radius(
        _radius("low", observability=CorrectnessObservability.UNKNOWN)
    )
    assert unknown.minimum_evidence_strength is EvidenceStrength.DECISIVE
    assert unknown.human_required and unknown.independent_review


def test_assurance_profile_rejects_an_incomparable_cover_weakening() -> None:
    strong_cover = AssuranceRequirement(
        blast_radius=_radius("high"),
        minimum_evidence_strength=EvidenceStrength.STRONG,
        required_evidence=[EvidenceClass.DETERMINISTIC_TEST, EvidenceClass.INDEPENDENT_REVIEW],
        required_modes=[AssuranceMode.DETERMINISTIC_TESTS, AssuranceMode.INDEPENDENT_REVIEW],
        independent_review=True,
        minimum_distinct_actors=2,
    )
    weak_cover = AssuranceRequirement(
        blast_radius=_radius("low", uncertainty=Ambiguity.EXPLORATORY),
        minimum_evidence_strength=EvidenceStrength.MODERATE,
        required_evidence=[EvidenceClass.DETERMINISTIC_TEST],
        required_modes=[AssuranceMode.DETERMINISTIC_TESTS],
    )

    with pytest.raises(ValidationError, match="effective assurance weakens"):
        AssuranceProfile(requirements=[strong_cover, weak_cover])


def test_compiler_does_not_advertise_an_unwired_decision_rights_bypass() -> None:
    from agent_foundry.compile.authority import (
        compute_compiled_authority,
        validate_execution_bundle_authority,
    )

    assert "decision_rights" not in inspect.signature(compute_compiled_authority).parameters
    assert "decision_rights" not in inspect.signature(validate_execution_bundle_authority).parameters


def test_verification_budget_cannot_skip_required_controls() -> None:
    requirement = AssuranceRequirement(
        blast_radius=_radius("high"),
        required_evidence=[EvidenceClass.DETERMINISTIC_TEST, EvidenceClass.INDEPENDENT_REVIEW],
        required_modes=[AssuranceMode.DETERMINISTIC_TESTS, AssuranceMode.INDEPENDENT_REVIEW],
        independent_review=True,
        minimum_distinct_actors=2,
    )
    budget = VerificationBudget(
        max_checks=4,
        max_evidence_items=2,
        allowed_modes=[AssuranceMode.DETERMINISTIC_TESTS, AssuranceMode.INDEPENDENT_REVIEW],
    )
    assert budget.allocate(requirement) == requirement
    with pytest.raises(ValueError, match="outside the budget"):
        VerificationBudget(allowed_modes=[AssuranceMode.DETERMINISTIC_TESTS]).allocate(requirement)
    with pytest.raises(ValueError, match="exceed the budget"):
        VerificationBudget(max_checks=1).allocate(requirement)


def test_higher_blast_radius_cannot_weaken_assurance_without_policy_evidence() -> None:
    low = AssuranceRequirement(
        blast_radius=_radius("low"),
        minimum_evidence_strength=EvidenceStrength.STRONG,
        required_modes=[AssuranceMode.INDEPENDENT_REVIEW],
        independent_review=True,
    )
    high = AssuranceRequirement(
        blast_radius=_radius("high"),
        minimum_evidence_strength=EvidenceStrength.MODERATE,
    )
    with pytest.raises(ValidationError, match="relaxation_evidence_refs"):
        AssuranceProfile(requirements=[low, high])

    relaxed = high.model_copy(update={"relaxation_evidence_refs": ("policy:exception-1",)})
    assert AssuranceProfile(requirements=[low, relaxed]).requirements[-1] == relaxed


def test_unknown_authority_and_credential_availability_never_widen_decisions() -> None:
    rights = DecisionRights(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        authority_ceilings=[
            AuthorityCeiling(
                consequence="low",
                max_external_effect=ExternalEffectClass.REPOSITORY_WRITE,
                approval_class=ApprovalClass.AUTOMATIC,
            )
        ]
    )
    unknown = rights.evaluate(
        consequence="high",
        requested_effect=ExternalEffectClass.REPOSITORY_WRITE,
        credential_available=True,
    )
    assert unknown.approval_class is ApprovalClass.REFUSED
    assert not unknown.permitted

    with_credential = rights.evaluate(
        consequence="low",
        requested_effect=ExternalEffectClass.REPOSITORY_WRITE,
        credential_available=True,
    )
    without_credential = rights.evaluate(
        consequence="low",
        requested_effect=ExternalEffectClass.REPOSITORY_WRITE,
        credential_available=False,
    )
    assert with_credential == without_credential

    inferred_widening = rights.evaluate(
        consequence="low",
        requested_effect=ExternalEffectClass.READ_ONLY,
        inferred_effect=ExternalEffectClass.PUBLICATION,
    )
    assert inferred_widening.approval_class is ApprovalClass.REFUSED
    assert not inferred_widening.permitted


def test_automatic_authority_and_mutation_obligations_fail_closed() -> None:
    with pytest.raises(ValidationError, match="cannot be granted beyond"):
        AuthorityCeiling(
            consequence="high",
            max_external_effect=ExternalEffectClass.RUNTIME_MUTATION,
            approval_class=ApprovalClass.AUTOMATIC,
        )
    with pytest.raises(ValidationError, match="require preview and read-back"):
        MutationObligation(
            external_effect=ExternalEffectClass.SHARED_SERVICE_WRITE,
            preview_required=False,
        )
    with pytest.raises(ValidationError, match="prior adopted policy version"):
        MutationObligation(
            external_effect=ExternalEffectClass.REPOSITORY_WRITE,
            rollback_required=True,
            restoration_target=RestorationTarget.NONE,
            read_back_required=True,
        )

    valid = MutationObligation(
        external_effect=ExternalEffectClass.REPOSITORY_WRITE,
        rollback_required=True,
        restoration_target=RestorationTarget.PRIOR_ADOPTED_POLICY_VERSION,
        read_back_required=True,
    )
    assert valid.read_back_required and valid.preview_required


def test_context_skill_precedence_cannot_override_project_policy() -> None:
    policy = ContextSkillPolicy()
    assert not policy.can_override(PolicySource.SKILL, PolicySource.PROJECT)
    assert not policy.can_override(PolicySource.INFERENCE, PolicySource.CONTEXT)
    with pytest.raises(ValidationError, match="cannot be overridden"):
        ContextSkillPolicy(
            overrides=[
                {"source": "skill", "target": "project", "allowed": True, "evidence_refs": ["x"]}
            ]
        )
    explicit = ContextSkillPolicy(
        overrides=[
            {"source": "policy", "target": "context", "allowed": True, "evidence_refs": ["policy:x"]}
        ]
    )
    assert explicit.can_override(PolicySource.POLICY, PolicySource.CONTEXT)


@pytest.mark.parametrize(
    "precedence",
    [
        [PolicySource.HUMAN, PolicySource.PROJECT],
        [PolicySource.PROJECT, PolicySource.HUMAN, *tuple(PolicySource)[2:]],
        [*tuple(PolicySource)[:-1]],
    ],
)
def test_context_skill_precedence_requires_the_complete_canonical_order(precedence) -> None:
    with pytest.raises(ValidationError, match="complete canonical order"):
        ContextSkillPolicy(precedence=precedence)

    with pytest.raises(ValidationError, match="complete non-overridable set"):
        ContextSkillPolicy(non_overridable=[PolicySource.HUMAN])


def test_context_skill_non_overridable_set_rejects_supersets() -> None:
    with pytest.raises(ValidationError, match="complete non-overridable set"):
        ContextSkillPolicy(
            non_overridable=[
                PolicySource.HUMAN,
                PolicySource.PROJECT,
                PolicySource.POLICY,
            ]
        )


def test_retry_policy_does_not_turn_missing_authority_into_retry_permission() -> None:
    with pytest.raises(ValidationError, match="not retryable"):
        RetryPolicy(
            max_attempts=3,
            retryable_triggers=[ControlTrigger.AUTHORITY_UNKNOWN],
        )
    assert RetryPolicy(max_attempts=1, retryable_triggers=[ControlTrigger.VALIDATION_FAILED])


def test_role_separation_is_a_floor_without_selecting_roles() -> None:
    with pytest.raises(ValidationError, match="reviewer role"):
        RoleSeparation(independent_review_required=True, minimum_distinct_actors=2)
    roles = RoleSeparation(
        required_roles=["builder", "reviewer"],
        independent_review_required=True,
        minimum_distinct_actors=2,
        reviewer_roles=["reviewer"],
    )
    assert roles.required_roles == ("builder", "reviewer")


def test_operating_model_is_versioned_and_round_trips_as_one_canonical_contract() -> None:
    model = OperatingModel(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        id="bounded-contract-work",
        description="Generic bounded operating model",
        project_profile_ref="profile://generic/rev-1",
        assurance=AssuranceProfile(requirements=_assurance_matrix()),
        role_separation=RoleSeparation(
            required_roles=["builder"],
            forbid_self_approval=True,
        ),
        mutation_obligations=[
            MutationObligation(external_effect=ExternalEffectClass.READ_ONLY, read_back_required=False)
        ],
    )
    assert load_yaml(OperatingModel, dump_yaml(model)) == model


def test_new_policy_contract_versions_are_explicit_and_current() -> None:
    valid = OperatingModel(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        id="versioned",
        description="explicit schema",
    )
    assert load_json(OperatingModel, dump_json(valid)) == valid

    with pytest.raises(ValidationError):
        OperatingModel(id="missing", description="schema is required")
    with pytest.raises(Exception, match="introduced in schema_version"):
        OperatingModel(schema_version="0.1", id="old", description="old schema")
    with pytest.raises(Exception, match="introduced in schema_version"):
        DecisionRights(schema_version="0.1")
    with pytest.raises(Exception):
        OperatingModel(schema_version="not-a-version", id="bad", description="bad schema")
    with pytest.raises(Exception, match="introduced in schema_version"):
        OperatingModel(
            schema_version=FOUNDRY_SCHEMA_VERSION,
            id="nested-old",
            description="nested schema",
            decision_rights={"schema_version": "0.1"},
        )
    with pytest.raises(Exception, match="introduced in schema_version"):
        load_yaml(
            OperatingModel,
            "schema_version: '0.1'\nid: old-yaml\ndescription: old schema\n",
        )
    with pytest.raises(Exception):
        load_json(
            OperatingModel,
            '{"schema_version":"0.3","id":"future-json","description":"future schema"}',
        )
    with pytest.raises(Exception):
        load_yaml(
            DecisionRights,
            "schema_version: not-a-version\nauthority_ceilings: []\n",
        )
    with pytest.raises(ValidationError):
        load_yaml(
            DecisionRights,
            "schema_version: '0.2'\nauthority_ceilings: not-a-sequence\n",
        )
    with pytest.raises(ValidationError):
        DecisionRights(
            schema_version=FOUNDRY_SCHEMA_VERSION,
            authority_ceilings=[{"consequence": "low", "max_external_effect": "invalid"}],
        )


def test_validated_policy_collections_cannot_be_mutated_to_widen_policy() -> None:
    rights = DecisionRights(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        authority_ceilings=[AuthorityCeiling(consequence="low")]
    )
    with pytest.raises((AttributeError, TypeError)):
        rights.authority_ceilings.append(  # type: ignore[attr-defined]
            AuthorityCeiling(consequence="high", max_external_effect="publication")
        )


def test_governance_document_covers_the_canonical_policy_surface() -> None:
    document = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "foundry"
        / "01-governance-and-control.md"
    ).read_text(encoding="utf-8")
    section = document[document.index("### 3.1 Canonical SUE-582 policy contracts") :]
    schema_section = document[document.index("#### 3.2 SUE-582 wire schema and closed vocabularies") :]
    for name in (
        "PermissionProfile",
        "OperatingConstraints",
        "AuthorityCeiling",
        "AuthorityDecision",
        "DecisionRights",
        "BlastRadius",
        "AssuranceRequirement",
        "VerificationBudget",
        "AssuranceProfile",
        "RoleSeparation",
        "OverrideRule",
        "ContextSkillPolicy",
        "ControlCondition",
        "RetryPolicy",
        "MutationObligation",
        "OperatingModel",
    ):
        line = next(
            line for line in schema_section.splitlines() if line.startswith(f"| `{name}` |")
        )

        documented_fields: dict[str, str] = {}
        for clause in line.split("|", 2)[2].rsplit("|", 1)[0].split(";"):
            match = re.match(
                r"\s*`?([a-z_][a-z0-9_]*)`?\s*(?:=|required\b)", clause
            )
            if match is None:
                continue
            field_name = match.group(1)
            if "=" not in clause:
                descriptor = "required"
            else:
                descriptor = clause.split("=", 1)[1].strip().rstrip("`")
                if descriptor.startswith("required"):
                    descriptor = "required"
                elif descriptor.startswith("factory"):
                    descriptor = "factory"
            documented_fields[field_name] = descriptor

        source_fields: dict[str, str] = {}
        for field_name, field in getattr(policy_models, name).model_fields.items():
            if field.is_required():
                descriptor = "required"
            elif field.default_factory is not None:
                descriptor = "factory"
            else:
                default = field.default
                if hasattr(default, "value"):
                    default = default.value
                if default is None:
                    default = "null"
                descriptor = str(default).lower()
            source_fields[field_name] = descriptor

        assert documented_fields == source_fields, (name, source_fields, documented_fields)
    for enum in (
        ExternalEffectClass,
        Autonomy,
        AssuranceMode,
        EvidenceClass,
        ControlTrigger,
        ApprovalClass,
        Coupling,
        CorrectnessObservability,
        EvidenceStrength,
        PolicySource,
        RestorationTarget,
    ):
        line = next(
            line
            for line in schema_section.splitlines()
            if line.startswith(f"| `{enum.__name__}` |")
        )
        documented_values = set(re.findall(r"`([^`]+)`", line.split("|", 2)[2]))
        source_values = {member.value for member in enum}
        assert documented_values == source_values, (enum.__name__, source_values, documented_values)
