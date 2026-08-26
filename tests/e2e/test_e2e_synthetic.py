"""The V0.1 vertical slice over a controlled fixture repository.

The gate this file exists for: a stage that exits without raising has proved nothing.
Every assertion below is about whether the artifact a stage produced is *usable* --
whether the manifest carries the project's declared characteristics, whether the
toolkit selected components and said why, whether the compiled bundle authorizes a
change it could actually make, and whether the rendered Markdown says what the
structured contract says.
"""

from __future__ import annotations

import pytest

from agent_foundry.compile import CompileError
from agent_foundry.models import (
    AdoptionAction,
    AdoptionChangeStatus,
    AssuranceMode,
    EvidenceClass,
    ExternalEffectClass,
    IntakeMode,
    PrimaryArtifactState,
    PrimaryWorkMode,
    ProvenanceKind,
    ValidationOutcome,
)
from agent_foundry.models.io import dump_json
from agent_foundry.secrets import (
    ConfidenceTier,
    raise_on_embedded_secrets,
    scan_for_embedded_secrets,
)
from agent_foundry.verify import VALIDATOR_IDS

from tests.e2e import support
from tests.e2e.pipeline import PipelineResult, run_pipeline

# The adoption item whose evidence names real files, so its compiled bundle carries a
# real write scope. Ids are digests of the causal group key and are therefore stable.
TEST_HARNESS_ITEM = "wi-dcc714550913"
INSTRUCTION_SURFACES_ITEM = "wi-9faa032e39cd"
# The item whose adoption change has no located evidence, so it has no repository
# path to bound a write with. Its bundle is the useless-but-valid case.
UNLOCATED_ITEM = "wi-38a82847d273"


@pytest.fixture(scope="module")
def result() -> PipelineResult:
    return run_pipeline(
        support.SYNTHETIC,
        work_item_id=TEST_HARNESS_ITEM,
        integrations=[support.tracker_integration()],
        desired_integration_ids=[support.TRACKER_INTEGRATION_ID],
        observed_health=[support.tracker_health()],
    )


# --- stage 1: inspect ---------------------------------------------------------


def test_inspection_sees_the_repository_within_its_own_bounds(result: PipelineResult) -> None:
    stats = result.intake.traversal_stats
    assert not stats.entry_limit_reached, (
        "traversal stopped at the entry limit; every 'not observed' finding below it "
        "is an artifact of truncation, not evidence of absence"
    )
    assert not stats.depth_limit_reached
    subjects = {observation.subject for observation in result.intake.observations}
    assert {
        "agent-instruction-surface",
        "package-metadata",
        "test-entrypoint",
        "ci-entrypoint",
        "runtime-deploy-hint",
        "integration-config",
        "foundry-declaration",
    } <= subjects


def test_every_observation_and_finding_carries_provenance(result: PipelineResult) -> None:
    for observation in result.intake.observations:
        assert observation.provenance.kind is not None
        assert observation.provenance.kind is not ProvenanceKind.NORMATIVE
    for finding in result.intake.classification_findings:
        assert finding.provenance.kind is not ProvenanceKind.NORMATIVE
        if finding.value is None:
            assert finding.reason, f"{finding.dimension} is unset without saying why"


def test_conventions_are_evidenced_by_the_line_that_produced_them(
    result: PipelineResult,
) -> None:
    """Every convention quotes a line that is actually in the file it cites.

    The name claims the evidence *is* the producing line, so the evidence text is read
    back out of the cited source rather than merely checked for being non-empty. The
    defect this guards against is real and already happened once: a `git-policy`
    convention matched "commit … not" and quoted the first line containing "commit",
    so an instruction surface was cited by its opposite.
    """
    conventions = {convention.subject for convention in result.intake.conventions}
    assert {"test-runner", "test-invocation", "ci-checkout", "git-policy"} <= conventions
    for convention in result.intake.conventions:
        assert convention.evidence.strip()
        assert 0.0 < convention.confidence <= 1.0
        assert convention.provenance.kind is not ProvenanceKind.NORMATIVE

        source = (support.SYNTHETIC / convention.source_ref).read_text(encoding="utf-8")
        assert convention.evidence in source, (
            f"{convention.subject} quotes {convention.evidence!r}, which does not "
            f"appear in {convention.source_ref}"
        )
        assert any(
            line.strip() == convention.evidence.strip() for line in source.splitlines()
        ), f"{convention.subject} evidence is not a whole line of {convention.source_ref}"


# --- stage 2: manifest and adoption change set --------------------------------


def test_manifest_carries_every_declared_characteristic(result: PipelineResult) -> None:
    manifest = result.manifest
    assert manifest.project.name == "orders-service"
    assert manifest.project.intake_mode is IntakeMode.BROWNFIELD
    assert manifest.project.primary_artifact is PrimaryArtifactState.CODE
    assert manifest.project.work_modes is not None
    assert manifest.project.work_modes.primary is PrimaryWorkMode.BUILD
    assert manifest.project.work_modes.secondary == [PrimaryWorkMode.ANALYZE]
    assert manifest.impact.external_effect is ExternalEffectClass.REPOSITORY_WRITE
    assert manifest.impact.consequence is not None
    assert manifest.impact.reversibility is not None
    assert manifest.state.persistence is not None
    assert manifest.state.temporal_mode is not None
    assert manifest.execution.autonomy is not None
    assert manifest.execution.ambiguity is not None
    assert manifest.execution.concurrency is not None
    assert manifest.access.sensitivity is not None
    assert AssuranceMode.DETERMINISTIC_TESTS in manifest.assurance.required
    assert AssuranceMode.INDEPENDENT_REVIEW in manifest.assurance.required


def test_current_truth_and_proposed_change_stay_distinct(result: PipelineResult) -> None:
    """The manifest is what is; the change set is what is proposed. Neither is the other.

    A change that says the project already satisfies a control (`KEEP`) is
    auto-applicable and demands no authority. A change that would edit the repository
    is `PROPOSED` and names the authority it needs. The manifest is unchanged by the
    existence of either.
    """
    by_action = {change.action: change for change in result.change_set.changes}
    assert AdoptionAction.KEEP in by_action
    assert AdoptionAction.HARDEN in by_action
    assert AdoptionAction.CONSOLIDATE in by_action
    assert AdoptionAction.DEFER in by_action

    for change in result.change_set.changes:
        if change.action is AdoptionAction.KEEP:
            assert change.status is AdoptionChangeStatus.AUTO_APPLICABLE
        else:
            assert change.status is not AdoptionChangeStatus.AUTO_APPLICABLE, (
                f"{change.target} proposes a change and must not apply itself"
            )
            assert change.authority_requirement.value != "none"
        assert change.evidence.summary
        if change.evidence.evidence_refs:
            assert change.evidence.provenance.source_ref is not None


def test_adoption_never_widens_authority_by_inference(result: PipelineResult) -> None:
    """The autonomy proposal is deferred, not applied, and says so."""
    autonomy = [
        change
        for change in result.change_set.changes
        if change.target == "execution.autonomy"
    ]
    assert autonomy, "fixture has tests and CI, so an autonomy proposal is expected"
    for change in autonomy:
        assert change.action is AdoptionAction.DEFER
        assert change.authority_requirement.value == "explicit-authority"
        assert change.status is AdoptionChangeStatus.PROPOSED


def test_this_fixture_produces_five_of_the_seven_brownfield_actions(
    result: PipelineResult,
) -> None:
    """`docs/foundry/02` §7 lists seven categories; this fixture exercises five.

    The name says five rather than "every action the contract names", because the
    other two are not produced here and one is not produced anywhere. MIGRATE needs a
    project with no owner declaration — covered in the brownfield tests. BLOCK has no
    observable trigger at all: `assess_readiness` never sets `blocker=True`, so it is
    reachable only through a hand-built intake, and gap §5.12 reports it as unverified
    rather than as coverage. Both absences are asserted so this test fails if either
    starts appearing without the report being updated.
    """
    emitted = {change.action for change in result.change_set.changes}
    assert emitted == {
        AdoptionAction.KEEP,
        AdoptionAction.CONSOLIDATE,
        AdoptionAction.WRAP,
        AdoptionAction.HARDEN,
        AdoptionAction.DEFER,
    }
    assert AdoptionAction.MIGRATE not in emitted
    assert AdoptionAction.BLOCK not in emitted


def test_wrap_retains_the_surface_and_changes_only_how_it_is_reached(
    result: PipelineResult,
) -> None:
    """WRAP per the contract: "existing tool/runtime retained behind a Foundry adapter".

    The fixture carries an `env.example` naming credential positions and declares no
    `IntegrationSpec`, so nothing states how an agent reaches it or what health it
    needs. Wrapping changes the access path; it does not consolidate, harden, or move
    the surface, which is what separates it from its sibling actions.
    """
    wraps = [
        change for change in result.change_set.changes if change.action is AdoptionAction.WRAP
    ]
    assert len(wraps) == 1
    wrap = wraps[0]
    assert wrap.target == "integration-surfaces"
    assert wrap.evidence.evidence_refs == ["env.example"]
    assert wrap.status is AdoptionChangeStatus.PROPOSED
    assert wrap.authority_requirement.value == "explicit-authority"
    assert "behind a declared Foundry integration adapter" in wrap.evidence.summary


# --- stage 3: causal work ------------------------------------------------------


def test_work_items_are_causal_and_independently_closable(result: PipelineResult) -> None:
    assert result.work_plan.work_items
    assert not result.work_plan.quality_issues, [
        issue.message for issue in result.work_plan.quality_issues
    ]
    for item in result.work_plan.work_items:
        assert item.objective
        assert item.acceptance_criteria
        assert item.stop_conditions
        assert item.current_facts
        assert item.required_evidence
        for requirement in item.required_evidence:
            assert requirement in {member.value for member in EvidenceClass}, (
                f"{item.id} requires {requirement!r}, which no evidence class names, "
                "so nothing can ever satisfy it"
            )
    packaged = {
        item_id
        for package in result.work_plan.packages
        for item_id in package.work_item_ids
    }
    assert packaged == {item.id for item in result.work_plan.work_items}


def test_work_item_is_not_an_execution_run(result: PipelineResult) -> None:
    """Three lifecycles, three records. The receipt keeps them apart."""
    receipt = result.receipt
    assert receipt.work_lifecycle_state.value not in {
        receipt.execution_state.value,
        *[state.value for state in receipt.attained_evidence_states],
    }
    assert receipt.attained_evidence_states
    assert not set(receipt.attained_evidence_states) & set(
        receipt.not_required_evidence_states
    )
    assert receipt.run_id != receipt.work_item_id


# --- stage 4: toolkit ----------------------------------------------------------


def test_project_toolkit_selects_components_and_explains_each_decision(
    result: PipelineResult,
) -> None:
    lock = result.project_lock
    assert lock.project_name == "orders-service"
    assert lock.capability_ids and lock.skill_ids and lock.role_ids
    assert "builder" in lock.role_ids
    assert "reviewer" in lock.role_ids, "independent-review assurance must staff a reviewer"
    assert lock.workflow_ids == ["builder-reviewer"]
    for component_id, version in lock.skill_versions.items():
        assert component_id in lock.skill_ids
        assert version
    for decision in lock.decisions:
        assert decision.rationale
        assert (
            decision.project_fact
            or decision.policy_id
            or decision.source.value == "registry"
        ), f"{decision.component_kind}/{decision.component_id} cites no cause"


def test_task_toolkit_is_a_subset_that_can_staff_the_workflow_it_pins(
    result: PipelineResult,
) -> None:
    task = result.task_toolkit
    lock = result.project_lock
    assert set(task.capability_ids) <= set(lock.capability_ids)
    assert set(task.skill_ids) <= set(lock.skill_ids)
    assert set(task.role_ids) <= set(lock.role_ids)
    if task.workflow_id is not None:
        workflow = next(
            item for item in result.registry.workflows if item.id == task.workflow_id
        )
        assert set(workflow.required_skills) <= set(task.skill_ids), (
            "a pinned workflow whose skills the task cannot carry declares a "
            "collaboration it cannot staff"
        )


def test_a_positively_observed_integration_is_pinned_and_carries_its_state(
    result: PipelineResult,
) -> None:
    """The positive case only.

    That a *non*-positive observation is refused is proved in
    `test_e2e_broken_fixtures.py`, whole-path and per-validator. The previous name here
    ("reports positive health only") claimed that negative half, which this body has
    never checked.
    """
    assert result.project_lock.integration_ids == [support.TRACKER_INTEGRATION_ID]
    assert [health.integration_id for health in result.integration_health] == [
        support.TRACKER_INTEGRATION_ID
    ]
    assert result.integration_health[0].state.value == "authorized"


# --- stage 5: compiled bundle --------------------------------------------------


def test_compiled_bundle_authorizes_a_change_it_could_actually_make(
    result: PipelineResult,
) -> None:
    bundle = result.bundle
    assert bundle.authority is not None
    assert bundle.authority.external_effect is ExternalEffectClass.REPOSITORY_WRITE
    assert bundle.write_scope, (
        "a repository-write bundle with no write path is valid and useless"
    )
    assert "repository.write" in bundle.allowed_capabilities
    assert not set(bundle.allowed_capabilities) & set(bundle.forbidden_capabilities)
    assert set(bundle.allowed_capabilities) <= set(bundle.task_toolkit.capability_ids)
    for granted in bundle.write_scope:
        assert any(
            granted == scope or granted.startswith(scope.rstrip("/") + "/")
            for scope in result.work_item.scope
        ), f"{granted!r} is granted but is not inside the work item scope"
    assert bundle.objective and bundle.acceptance_criteria and bundle.stop_conditions
    assert bundle.required_evidence
    assert bundle.provenance


def test_bundle_provenance_names_the_fact_behind_every_selection(
    result: PipelineResult,
) -> None:
    for record in result.bundle.provenance:
        assert record.rationale
        assert record.project_fact or record.policy_id, (
            f"{record.component_kind}/{record.component_id} was "
            f"{'selected' if record.selected else 'excluded'} with no attributable cause"
        )


def test_selected_context_is_a_relevant_subset_not_the_whole_repository(
    result: PipelineResult,
) -> None:
    """Progressive disclosure: refs not contents, fewer than observed, and *why*.

    "Relevant" is the load-bearing word in the name, so it is asserted: every selection
    carries a provenance record naming the Work Item fields that caused it. A subset
    chosen for no stated reason is a smaller context, not a relevant one.
    """
    selected = set(result.bundle.selected_observations)
    observed = {observation.subject for observation in result.intake.observations}
    assert selected < observed, "context selection must narrow, not pass everything through"

    selection_causes = {
        record.component_id: record
        for record in result.bundle.provenance
        if record.component_kind in {"observation", "convention"} and record.selected
    }
    assert selection_causes, "context selection recorded no reason for anything"
    for component_id, record in selection_causes.items():
        assert record.project_fact, f"{component_id} was selected with no stated cause"
        assert "work_item_fields=" in record.project_fact, (
            f"{component_id} names no work item field as the cause of its relevance"
        )

    for summary in result.bundle.skill_summaries:
        assert summary.skill_id in result.task_toolkit.skill_ids
        assert summary.description and summary.relevance


# --- stage 6: rendered Markdown ------------------------------------------------


def test_markdown_is_concise_and_derived_from_the_structured_bundle(
    result: PipelineResult,
) -> None:
    markdown = result.markdown
    assert markdown.startswith(f"# Execution Contract — {result.bundle.work_item_id}")
    for section in (
        "## Objective",
        "## Scope",
        "## Acceptance criteria",
        "## Allowed capabilities",
        "## Write scope",
        "## Required evidence",
        "## Stop conditions",
    ):
        assert section in markdown, f"rendered contract omits {section}"
    for path in result.bundle.write_scope:
        assert path in markdown
    for capability in result.bundle.allowed_capabilities:
        assert capability in markdown
    # Concise means bounded, and the bound is checked rather than asserted.
    assert len(markdown.encode("utf-8")) < 4000
    # A projection, never canonical state: it carries no schema version to load back.
    assert "schema_version" not in markdown


def _artifacts(result: PipelineResult) -> dict[str, object]:
    return {
        "manifest": result.manifest,
        "project_lock": result.project_lock,
        "task_toolkit": result.task_toolkit,
        "bundle": result.bundle,
        "receipt": result.receipt,
        "evidence_bundle": result.evidence_bundle,
    }


def test_no_raw_secret_reaches_any_serialized_artifact(result: PipelineResult) -> None:
    """Proved through the SUE-318 boundary, over the real serialized payloads.

    Tier A is the enforcing tier — `raise_on_embedded_secrets` refuses construction on
    a Tier A hit and lets a Tier B entropy hit through — so the boundary claim is a
    claim about Tier A. Tier B is measured separately below rather than folded in here,
    because a heuristic tier that fires on ordinary text would otherwise make this test
    fail for a reason that has nothing to do with secrets.
    """
    for name, model in _artifacts(result).items():
        findings = [
            finding
            for finding in scan_for_embedded_secrets(model.model_dump(mode="json"))
            if finding.confidence_tier is ConfidenceTier.TIER_A
        ]
        assert not findings, f"{name} carries secret-shaped values: {findings}"
        assert support.TRACKER_CREDENTIAL_REF.split(":", 1)[1] not in dump_json(model).decode()

    raise_on_embedded_secrets(result.bundle.model_dump(mode="json"))
    raise_on_embedded_secrets({"markdown": result.markdown})


def test_entropy_tier_false_positives_are_measured_not_assumed_absent(
    result: PipelineResult,
) -> None:
    """AF8 measurement, pinned so a change to the heuristic is visible.

    The Tier B entropy rule fires on ordinary structured provenance text: strings like
    `work_item.work_class=ADOPTION` are long, mixed-case and punctuated, which is what
    the rule looks for. Nothing is leaked — Tier B does not gate anything — but a
    consumer running the scanner over its own artifacts sees findings that are not
    secrets, so the count is recorded rather than left as an unexamined "clean".
    """
    tier_b = [
        finding
        for name, model in _artifacts(result).items()
        for finding in scan_for_embedded_secrets(model.model_dump(mode="json"))
        if finding.confidence_tier is ConfidenceTier.TIER_B
    ]
    assert tier_b, "if the heuristic stops firing here, this measurement is stale"
    assert all(finding.rule_name == "high-entropy" for finding in tier_b)
    # Every hit lands on prose a human wrote to explain a decision: the fact behind a
    # selection, or the reason a receipt records a limitation. None is a credential
    # position, and none is on a field that could hold one.
    explanatory_fields = {"project_fact", "reason"}
    assert all(
        finding.path_segments[-1] in explanatory_fields for finding in tier_b
    ), sorted({finding.json_path for finding in tier_b})
    assert len(tier_b) > 20, "the noise is substantial, not incidental"

    # The rendered Markdown is one long string, so the whole contract reads as one
    # high-entropy value. Scanning a projection is not how the boundary is enforced.
    rendered = scan_for_embedded_secrets({"markdown": result.markdown})
    assert [finding.confidence_tier for finding in rendered] == [ConfidenceTier.TIER_B]


def test_integration_config_carries_a_reference_not_a_value() -> None:
    spec = support.tracker_integration()
    assert spec.auth is not None
    payload = spec.model_dump(mode="json")
    assert payload["auth"]["credential_ref"] == {"provider": "env", "name": "ORDERS_TRACKER_TOKEN"}
    assert not scan_for_embedded_secrets(payload)


# --- stage 7: validation, evidence, receipt, reconciliation --------------------


def test_validation_runs_every_published_validator_and_accepts(
    result: PipelineResult,
) -> None:
    """Coverage first, verdict second — in that order, because the reverse misleads.

    An acceptance over a subset of the checks is not an acceptance of the slice. An
    earlier version of this harness aggregated four artifact validators and reported
    True for a run whose required integration was unavailable, so what is asserted here
    is that the verdict covers the whole published catalog and nothing was skipped.
    """
    assert set(result.ran()) == set(VALIDATOR_IDS)
    assert result.validation.not_run == []
    assert result.accepted(), result.rejecting()
    for report in result.validation_reports:
        assert report.findings, "a report with no findings is not an acceptance"
        assert report.outcome() in {ValidationOutcome.PASS, ValidationOutcome.NOT_REQUIRED}


def test_receipt_binds_to_the_exact_artifacts_the_run_consumed(
    result: PipelineResult,
) -> None:
    from agent_foundry.verify import artifact_digest

    identities = {identity.kind: identity for identity in result.receipt.artifact_identities}
    assert "execution-bundle" in identities
    assert identities["execution-bundle"].digest == artifact_digest(result.bundle)
    assert result.receipt.limitations, "a receipt must record what it did not establish"
    assert result.receipt.permission_profile_id == result.project_lock.permission_profile_ids[0]
    assert result.receipt.review_decision is not None
    assert (
        result.receipt.review_decision.reviewer_role
        != result.receipt.review_decision.implementing_role_id
    )


def test_reconciliation_reports_agreement_without_applying_anything(
    result: PipelineResult,
) -> None:
    report = result.reconciliation
    assert report.work_item_id == result.work_item.id
    for proposal in report.proposals:
        assert proposal.requires_human or proposal.authority.value == "foundry"
    for finding in report.findings:
        assert finding.dimension is not None
        assert finding.message


# --- the useless-bundle case, caught rather than passed -----------------------


def test_compilation_refuses_a_write_bundle_with_no_write_path() -> None:
    """The completion gate's own failure mode, refused by the producer.

    `instruction-surface-mentions` is a readiness finding with no located evidence, so
    the change carries no repository path and the Work Item bounds a write with a
    logical name rather than a file. Everything about the resulting bundle would be
    internally consistent — capabilities drawn from the toolkit, containment holding
    vacuously, provenance complete — and an executor holding it could not change a
    single file.

    Compilation refuses rather than emitting it. Leaving that to a later `validate`
    call means `agent-foundry compile` reports success for work that cannot be done.
    """
    with pytest.raises(CompileError) as excinfo:
        run_pipeline(support.SYNTHETIC, work_item_id=UNLOCATED_ITEM)

    message = str(excinfo.value)
    assert "no write path" in message
    # The message has to be actionable: it names the scope that found no bound, and
    # the bounds it was checked against.
    assert "instruction-surface-mentions" in message
    assert "authority.write_scope" in message


def test_the_declared_envelope_narrows_a_work_item_scope() -> None:
    """The project permits writing its canonical instruction surface, not the mirror.

    The change is evidenced by both `AGENTS.md` and `CLAUDE.md`, so the Work Item is
    scoped to both. `.foundry/project.yaml` declares only the first as writable, and
    the compiled grant is the intersection — which is the envelope doing its job
    rather than the Work Item getting what it asked for.
    """
    result = run_pipeline(support.SYNTHETIC, work_item_id=INSTRUCTION_SURFACES_ITEM)
    assert sorted(result.work_item.scope) == ["AGENTS.md", "CLAUDE.md"]
    assert "CLAUDE.md" not in result.manifest.authority.write_scope
    assert result.bundle.write_scope == ["AGENTS.md"]
    assert result.accepted(), result.rejecting()
