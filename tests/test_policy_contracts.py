"""SUE-582 contract tests: authority, assurance, control, and mutation policy."""

from __future__ import annotations

import pytest
from pathlib import Path
from pydantic import ValidationError

from agent_foundry.models import (
    Ambiguity,
    ApprovalClass,
    AssuranceMode,
    AssuranceProfile,
    AssuranceRequirement,
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
    PolicySource,
    RestorationTarget,
    RetryPolicy,
    RoleSeparation,
    Reversibility,
    dump_yaml,
    load_yaml,
)


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
    requirement = AssuranceProfile(requirements=_assurance_matrix()).for_blast_radius(
        blast_radius
    )
    assert requirement is not None, case_id
    if case_id == "low-impact-deterministic-edit":
        assert not requirement.independent_review
    else:
        assert requirement.independent_review
    if case_id == "external-write-action":
        obligation = MutationObligation(
            external_effect=effect,
            rollback_required=True,
            restoration_target=RestorationTarget.PRIOR_ADOPTED_POLICY_VERSION,
            read_back_required=True,
        )
        assert obligation.preview_required and obligation.read_back_required


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


def test_validated_policy_collections_cannot_be_mutated_to_widen_policy() -> None:
    rights = DecisionRights(
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
    for name in (
        "OperatingModel",
        "DecisionRights",
        "AuthorityCeiling",
        "BlastRadius",
        "AssuranceProfile",
        "RoleSeparation",
        "RetryPolicy",
        "ContextSkillPolicy",
        "MutationObligation",
    ):
        assert f"`{name}`" in section
    for enum in (
        ApprovalClass,
        Coupling,
        CorrectnessObservability,
        EvidenceStrength,
    ):
        for member in enum:
            assert f"`{member.value}`" in section
