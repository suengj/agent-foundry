"""Deliberately broken runs, and the verdict that has to reject each one.

A validation layer that passes everything is not evidence — and neither is a set of
validators that each reject correctly while the end-to-end verdict never consults
them. This file proves both halves, in that order:

* **Whole-path.** The break is injected at the pipeline's *input*, the full path runs,
  and `PipelineResult.accepted()` must be False. These are the tests that matter: an
  earlier version of this harness aggregated four artifact checks and called the result
  an acceptance, so a run carrying an unhealthy required integration reported
  `accepted() == True` while the integration validator rejected the same inputs.
* **Per-validator.** The same four classes against the individual validators, each with
  a control asserting the unbroken case passes first, so a rejection cannot be an
  artifact of a broken fixture. Breaks are applied with `model_construct` where a model
  validator would otherwise refuse to build the artifact at all — the point is to check
  the *verifier*, not the producer's own gate.

Four failure classes, in both halves:

1. policy violation — compiled authority exceeds a declared bound
2. role-separation conflict — two roles hold the same write path, or a role reviews itself
3. missing required evidence — a required class has no typed, passing item
4. unhealthy required integration — a required integration is unobserved or degraded
"""

from __future__ import annotations

import pytest

from agent_foundry.compile import CompileAuthorityError
from agent_foundry.compile import api as compile_api
from agent_foundry.compile import authority as compile_authority
from agent_foundry.models import (
    EvidenceBundle,
    EvidenceClass,
    EvidenceItem,
    EvidenceResult,
    ExternalEffectClass,
    IntegrationHealthState,
    ReceiptContractError,
    ReviewDecision,
    ReviewOutcome,
    SliceValidation,
    ValidationOutcome,
    ValidatorNotRun,
)
from agent_foundry.verify import (
    VALIDATOR_IDS,
    validate_authority_ceiling,
    validate_integration_preflight,
    validate_required_evidence,
    validate_role_separation,
    validate_write_scope_containment,
)

from tests.e2e import support
from tests.e2e.pipeline import CANDIDATE_REVISION, PipelineResult, run_pipeline

BUILDER_ITEM = "wi-dcc714550913"


@pytest.fixture(scope="module")
def good() -> PipelineResult:
    return run_pipeline(
        support.SYNTHETIC,
        work_item_id=BUILDER_ITEM,
        integrations=[support.tracker_integration()],
        desired_integration_ids=[support.TRACKER_INTEGRATION_ID],
        observed_health=[support.tracker_health()],
    )


# ==========================================================================
# Whole-path: the break enters at the pipeline input and must reach the verdict
# ==========================================================================


def _run(**overrides) -> PipelineResult:
    """One full pipeline run over the synthetic fixture, with overrides applied."""
    kwargs = dict(
        work_item_id=BUILDER_ITEM,
        integrations=[support.tracker_integration()],
        desired_integration_ids=[support.TRACKER_INTEGRATION_ID],
        observed_health=[support.tracker_health()],
    )
    kwargs.update(overrides)
    return run_pipeline(support.SYNTHETIC, **kwargs)


def test_the_unbroken_run_is_accepted_and_every_validator_ran(good: PipelineResult) -> None:
    """The control for every whole-path test below.

    Coverage is asserted, not assumed: the verdict names every validator in the
    published catalog, and nothing was skipped. Without this, a rejection below could
    mean the fixture is broken, and an acceptance could mean the check never ran.
    """
    assert good.accepted(), good.rejecting()
    assert good.validation.not_run == []
    assert set(good.ran()) == set(VALIDATOR_IDS)


def test_whole_path_policy_violation_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Class 1. The producer refuses first; with its guard removed, the verdict still does.

    Two properties in one test, because either alone is misleading. The compiler
    intersects authority against every declared bound and raises rather than emitting a
    widened one, so a policy violation cannot normally reach an artifact at all. That
    makes it worth proving that when the producer's own guard is neutralized, the
    independent `authority-ceiling` check catches what the producer let through.
    """
    real_compute = compile_authority.compute_compiled_authority

    def widened(*args: object, **kwargs: object):
        return real_compute(*args, **kwargs).model_copy(
            update={"external_effect": ExternalEffectClass.PUBLICATION}
        )

    monkeypatch.setattr(compile_authority, "compute_compiled_authority", widened)
    monkeypatch.setattr(compile_api, "compute_compiled_authority", widened)

    with pytest.raises(CompileAuthorityError, match="exceeds manifest ceiling"):
        _run()

    # With the producer's structural guard removed the widened bundle is emitted, and
    # the slice verdict rejects it anyway.
    monkeypatch.setattr(
        compile_api, "validate_execution_bundle_authority", lambda *a, **k: None
    )
    result = _run()
    assert result.bundle.authority.external_effect is ExternalEffectClass.PUBLICATION
    assert not result.accepted()
    assert any(
        message.startswith("authority-ceiling/BLOCKED") for message in result.rejecting()
    ), result.rejecting()


def test_whole_path_role_separation_conflict_is_rejected() -> None:
    """Class 2. A project-supplied registry lets two roles write the same paths."""
    result = _run(
        registry=support.registry_granting_write_to("reviewer"),
        also_compile_roles=["reviewer"],
    )
    assert not result.accepted()
    rejecting = result.rejecting()
    assert any("overlapping write scope" in message for message in rejecting), rejecting
    assert any("review-only role" in message for message in rejecting), rejecting


def test_whole_path_missing_evidence_is_rejected() -> None:
    """Class 3. The run produced no evidence for the classes the Work Item requires."""
    result = _run(satisfied_evidence=frozenset())
    assert not result.accepted()
    rejecting = result.rejecting()
    for requirement in result.work_item.required_evidence:
        assert any(
            message.startswith("required-evidence/MISSING") and requirement in message
            for message in rejecting
        ), (requirement, rejecting)


def test_whole_path_partial_evidence_is_rejected() -> None:
    """Some evidence is not enough evidence, and the verdict says which class is short."""
    result = _run(satisfied_evidence=frozenset({EvidenceClass.DETERMINISTIC_TEST.value}))
    assert not result.accepted()
    assert any(
        message.startswith("required-evidence/") and "repository-revision" in message
        for message in result.rejecting()
    ), result.rejecting()


def test_whole_path_unhealthy_required_integration_is_rejected() -> None:
    """Class 4. The exact run an earlier version of this harness reported as accepted."""
    result = _run(observed_health=[support.tracker_health(IntegrationHealthState.UNAVAILABLE)])
    assert not result.accepted()
    assert any(
        message.startswith("integration-preflight/BLOCKED")
        for message in result.rejecting()
    ), result.rejecting()


def test_whole_path_unobserved_required_integration_is_rejected() -> None:
    """Unobserved is not healthy, all the way through to the verdict."""
    result = _run(observed_health=[])
    assert not result.accepted()
    assert any(
        "unobserved is not healthy" in message for message in result.rejecting()
    ), result.rejecting()


def test_a_silently_dropped_integration_does_not_read_as_not_required() -> None:
    """Resolution subtracts an unhealthy integration; the verdict must still object.

    The subtraction is correct — an integration below its required health does not
    belong in a Task Toolkit. What must not happen is the compiled bundle carrying no
    trace of the request, so preflight sees an empty required set and reports
    NOT_REQUIRED for an integration the caller asked for and could not have.
    """
    result = _run(observed_health=[support.tracker_health(IntegrationHealthState.UNAVAILABLE)])
    assert result.bundle.integration_ids == [], (
        "an unhealthy integration must not reach the compiled bundle"
    )
    assert not result.accepted()


def test_a_validator_that_cannot_run_is_not_an_acceptance(good: PipelineResult) -> None:
    """The property the whole verdict rests on, checked directly.

    `SliceValidation.accepted()` is False whenever an applicable validator had no input
    to run against. A partial verdict is not a verdict, however many of the checks that
    did run passed.
    """
    partial = SliceValidation(
        subject_id=good.validation.subject_id,
        reports=list(good.validation.reports),
        not_run=[
            ValidatorNotRun(
                validator_id="required-evidence", reason="no evidence bundle supplied"
            )
        ],
    )
    assert all(report.accepted() for report in partial.reports)
    assert not partial.accepted()


# ==========================================================================
# Per-validator: the same four classes, one validator at a time
# ==========================================================================


def _rejecting_messages(report) -> list[str]:
    return [finding.message for finding in report.rejecting()]


def _role(result: PipelineResult, role_id: str):
    return next(role for role in result.registry.roles if role.id == role_id)


def _permission_profile(result: PipelineResult):
    profile_id = result.task_toolkit.permission_profile_ids[0]
    from agent_foundry.toolkit.builtin_registry import build_default_registry_permission_profiles

    return next(
        profile
        for profile in build_default_registry_permission_profiles()
        if profile.id == profile_id
    )


# --- 1. policy violation -------------------------------------------------------


def test_baseline_authority_is_accepted(good: PipelineResult) -> None:
    """The control. Without it, a rejection below could mean the fixture is broken."""
    report = validate_authority_ceiling(
        good.bundle.authority,
        work_item=good.work_item,
        manifest=good.manifest,
        task_toolkit=good.task_toolkit,
        role=_role(good, good.bundle.role_id),
        permission_profile=_permission_profile(good),
        registry=good.registry,
    )
    assert report.accepted(), _rejecting_messages(report)


def test_authority_above_the_manifest_ceiling_is_rejected(good: PipelineResult) -> None:
    """Policy violation: the compiled bundle claims more effect than the project allows."""
    widened = good.bundle.authority.model_copy(
        update={"external_effect": ExternalEffectClass.PUBLICATION}
    )
    report = validate_authority_ceiling(
        widened,
        work_item=good.work_item,
        manifest=good.manifest,
        task_toolkit=good.task_toolkit,
        role=_role(good, good.bundle.role_id),
        permission_profile=_permission_profile(good),
        registry=good.registry,
    )
    assert not report.accepted()
    assert any("publication" in message for message in _rejecting_messages(report))


def test_write_scope_escaping_the_work_item_is_rejected(good: PipelineResult) -> None:
    """Policy violation on the path axis: a grant outside the item's declared scope."""
    escaped = good.bundle.authority.model_copy(
        update={"write_scope": ["../outside-the-repository"]}
    )
    report = validate_write_scope_containment(
        escaped,
        work_item=good.work_item,
        role=_role(good, good.bundle.role_id),
    )
    assert not report.accepted()
    assert any(
        "../outside-the-repository" in message for message in _rejecting_messages(report)
    )


# --- 2. role-separation conflict -----------------------------------------------


def test_concurrent_roles_sharing_a_write_path_are_rejected(good: PipelineResult) -> None:
    """Two roles authorized over the same path in one run is not single-writer."""
    other = good.bundle.model_copy(update={"role_id": "explorer"})
    report = validate_role_separation([good.bundle, other])
    assert not report.accepted()
    assert any("overlap" in message.lower() for message in _rejecting_messages(report))


def test_a_reviewer_may_not_review_its_own_implementation(good: PipelineResult) -> None:
    """The producer refuses to build it, and the verifier refuses to accept it built."""
    with pytest.raises(ReceiptContractError):
        ReviewDecision(
            work_item_id=good.work_item.id,
            run_id=good.bundle.run_id,
            reviewer_role="builder",
            implementing_role_id="builder",
            outcome=ReviewOutcome.APPROVED,
        )

    self_review = ReviewDecision.model_construct(
        work_item_id=good.work_item.id,
        run_id=good.bundle.run_id,
        reviewer_role="builder",
        implementing_role_id="builder",
        outcome=ReviewOutcome.APPROVED,
        findings=[],
        blocking=False,
        reviewed_revision=CANDIDATE_REVISION,
        evidence_refs=[],
        decided_at=None,
    )
    report = validate_role_separation([good.bundle], review_decisions=[self_review])
    assert not report.accepted()
    assert any("builder" in message for message in _rejecting_messages(report))


def test_a_review_only_role_holding_write_authority_is_rejected(
    good: PipelineResult,
) -> None:
    reviewer_with_write = good.bundle.model_copy(update={"role_id": "reviewer"})
    report = validate_role_separation([reviewer_with_write])
    assert not report.accepted()
    assert any("reviewer" in message for message in _rejecting_messages(report))


# --- 3. missing required evidence ----------------------------------------------


def test_baseline_evidence_satisfies_the_work_item(good: PipelineResult) -> None:
    report = validate_required_evidence(good.work_item, good.evidence_bundle)
    assert report.accepted(), _rejecting_messages(report)


def test_absent_evidence_is_missing_not_passing(good: PipelineResult) -> None:
    empty = good.evidence_bundle.model_copy(update={"items": []})
    report = validate_required_evidence(good.work_item, empty)
    assert not report.accepted()
    assert {finding.outcome for finding in report.rejecting()} == {ValidationOutcome.MISSING}
    for requirement in good.work_item.required_evidence:
        assert any(requirement in message for message in _rejecting_messages(report))


def test_untyped_evidence_proves_nothing(good: PipelineResult) -> None:
    """A free-form `kind` is not a claim a required class can be satisfied by."""
    untyped = good.evidence_bundle.model_copy(
        update={
            "items": [
                EvidenceItem(
                    kind="deterministic-test",
                    ref="artifacts/looks-official.log",
                    result=EvidenceResult.PASS,
                    proves_revision=CANDIDATE_REVISION,
                )
            ]
        }
    )
    report = validate_required_evidence(good.work_item, untyped)
    assert not report.accepted()


def test_failing_evidence_does_not_satisfy_a_requirement(good: PipelineResult) -> None:
    failing = good.evidence_bundle.model_copy(
        update={
            "items": [
                item.model_copy(update={"result": EvidenceResult.FAIL})
                for item in good.evidence_bundle.items
            ]
        }
    )
    report = validate_required_evidence(good.work_item, failing)
    assert not report.accepted()


def test_evidence_for_a_different_revision_does_not_carry_over(
    good: PipelineResult,
) -> None:
    stale = good.evidence_bundle.model_copy(
        update={
            "items": [
                item.model_copy(update={"proves_revision": None})
                for item in good.evidence_bundle.items
            ]
        }
    )
    report = validate_required_evidence(good.work_item, stale)
    assert not report.accepted()


def test_no_evidence_bundle_at_all_is_rejected(good: PipelineResult) -> None:
    report = validate_required_evidence(good.work_item, None)
    assert not report.accepted()


def test_a_class_cannot_be_both_attained_and_exempt(good: PipelineResult) -> None:
    conflicted = EvidenceBundle.model_construct(
        schema_version=good.evidence_bundle.schema_version,
        work_item_id=good.work_item.id,
        run_id=good.bundle.run_id,
        items=list(good.evidence_bundle.items),
        identity=good.evidence_bundle.identity,
        not_required_classes=[EvidenceClass.DETERMINISTIC_TEST],
        unresolved=[],
        provenance=list(good.evidence_bundle.provenance),
    )
    from agent_foundry.verify import validate_evidence_bundle_completeness

    report = validate_evidence_bundle_completeness(conflicted)
    assert not report.accepted()


# --- 4. unhealthy required integration -----------------------------------------


def test_baseline_integration_preflight_passes(good: PipelineResult) -> None:
    report = validate_integration_preflight(
        [support.tracker_integration()],
        required_ids=[support.TRACKER_INTEGRATION_ID],
        observed_health=[support.tracker_health()],
    )
    assert report.accepted(), _rejecting_messages(report)


def test_an_unobserved_required_integration_is_missing_not_healthy() -> None:
    report = validate_integration_preflight(
        [support.tracker_integration()],
        required_ids=[support.TRACKER_INTEGRATION_ID],
        observed_health=[],
    )
    assert not report.accepted()
    assert ValidationOutcome.MISSING in {finding.outcome for finding in report.rejecting()}


def test_a_degraded_required_integration_is_rejected() -> None:
    report = validate_integration_preflight(
        [support.tracker_integration()],
        required_ids=[support.TRACKER_INTEGRATION_ID],
        observed_health=[support.tracker_health(IntegrationHealthState.UNAVAILABLE)],
    )
    assert not report.accepted()
    assert any(
        "unavailable" in message.lower() for message in _rejecting_messages(report)
    )


def test_an_undeclared_required_integration_is_rejected() -> None:
    report = validate_integration_preflight(
        [],
        required_ids=[support.TRACKER_INTEGRATION_ID],
        observed_health=[support.tracker_health()],
    )
    assert not report.accepted()


def test_an_authenticating_integration_without_an_auth_block_is_rejected() -> None:
    spec = support.tracker_integration()
    without_auth = spec.model_copy(update={"auth": None})
    report = validate_integration_preflight(
        [without_auth],
        required_ids=[support.TRACKER_INTEGRATION_ID],
        observed_health=[support.tracker_health()],
    )
    assert not report.accepted()


def test_the_broken_integration_reaches_the_pipeline_as_a_rejection() -> None:
    """The whole slice, run with a degraded integration, is not accepted."""
    result = run_pipeline(
        support.SYNTHETIC,
        work_item_id=BUILDER_ITEM,
        integrations=[support.tracker_integration()],
        desired_integration_ids=[support.TRACKER_INTEGRATION_ID],
        observed_health=[support.tracker_health(IntegrationHealthState.UNAVAILABLE)],
    )
    health = {item.integration_id: item.state for item in result.integration_health}
    assert health[support.TRACKER_INTEGRATION_ID] is IntegrationHealthState.UNAVAILABLE
    report = validate_integration_preflight(
        [support.tracker_integration()],
        required_ids=sorted(result.project_lock.integration_ids),
        observed_health=result.integration_health,
    )
    assert not report.accepted()
