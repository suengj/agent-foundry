"""Shared builders for the AF7 validation, reconciliation, and receipt tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agent_foundry.compile import compile_work_item
from agent_foundry.models import (
    BudgetConsumption,
    EvidenceBundle,
    EvidenceClass,
    EvidenceIdentity,
    EvidenceItem,
    EvidenceResult,
    EvidenceState,
    ExecutionState,
    FindingDisposition,
    IntegrationHealth,
    IntegrationHealthState,
    IntegrationSpec,
    ProjectManifest,
    Provenance,
    ProvenanceKind,
    ReceiptLimitation,
    RepositoryEvidence,
    ReviewDecision,
    ReviewOutcome,
    RunFinding,
    RuntimeReadback,
    TrackerProjection,
    WorkItemContract,
    WorkLifecycleState,
)
from agent_foundry.models.base import FOUNDRY_SCHEMA_VERSION
from agent_foundry.toolkit import default_registry, resolve_toolkit
from agent_foundry.toolkit.builtin_registry import (
    build_default_registry_budget_profiles,
    build_default_registry_permission_profiles,
)
from agent_foundry.verify.receipt import build_execution_receipt

BASE_REVISION = "rev-base-0001"
CANDIDATE_REVISION = "rev-cand-0002"
INTEGRATED_REVISION = "rev-int-0003"
STARTED_AT = datetime(2026, 3, 1, 9, 0, 0, tzinfo=timezone.utc)
FINISHED_AT = datetime(2026, 3, 1, 11, 0, 0, tzinfo=timezone.utc)


def sample_manifest(**overrides: object) -> ProjectManifest:
    base = {
        "schema_version": FOUNDRY_SCHEMA_VERSION,
        "project": {
            "name": "sample-service",
            "intake_mode": "brownfield",
            "work_modes": {"primary": "build"},
            "primary_artifact": "code",
        },
        "state": {"persistence": "persistent-shared-external", "temporal_mode": "long-running"},
        "impact": {
            "external_effect": "repository-write",
            "reversibility": "versioned",
            "consequence": "medium",
        },
        "execution": {
            "autonomy": "bounded-external-write",
            "ambiguity": "bounded-judgment",
            "concurrency": "single-writer",
        },
        "assurance": {"required": ["deterministic-tests"]},
        "access": {"sensitivity": "internal"},
        # Compiled write authority is the intersection of this declared envelope
        # with the Work Item scope. Undeclared grants nothing.
        "authority": {"write_scope": ["src/", "tests/"]},
    }
    base.update(overrides)
    return ProjectManifest.model_validate(base)


def sample_work_item(**overrides: object) -> WorkItemContract:
    base = {
        "schema_version": FOUNDRY_SCHEMA_VERSION,
        "id": "WI-VERIFY-001",
        "title": "Add bounded validation layer",
        "work_class": "CAPABILITY",
        "objective": "Deliver bounded validation changes in src/",
        "current_facts": ["compiler exists"],
        "scope": ["src/", "tests/"],
        "out_of_scope": ["execution runtime"],
        "acceptance_criteria": ["pytest green"],
        "dependencies": [],
        "authority_class": "repository-write",
        "consequence_class": "medium",
        "required_evidence": ["deterministic-test", "repository-revision"],
        "stop_conditions": ["cannot express semantics"],
    }
    base.update(overrides)
    return WorkItemContract.model_validate(base)


def compiled(role_id: str = "builder", run_id: str = "RUN-VERIFY-001", **work_overrides: object):
    """Compile a real bundle plus every artifact a validator needs to check it."""
    manifest = sample_manifest()
    work_item = sample_work_item(**work_overrides)
    _, lock = resolve_toolkit(manifest)
    result = compile_work_item(work_item, manifest, lock, role_id, run_id)
    registry = default_registry()
    role = next(item for item in registry.roles if item.id == role_id)
    profiles = build_default_registry_permission_profiles()
    profile = next(
        item for item in profiles if item.id == result.task_toolkit.permission_profile_ids[0]
    )
    return {
        "manifest": manifest,
        "work_item": work_item,
        "lock": lock,
        "task_toolkit": result.task_toolkit,
        "bundle": result.bundle,
        "registry": registry,
        "role": role,
        "permission_profile": profile,
        "budget_profiles": build_default_registry_budget_profiles(),
    }


def full_evidence_bundle(**overrides: object) -> EvidenceBundle:
    base = {
        "schema_version": FOUNDRY_SCHEMA_VERSION,
        "work_item_id": "WI-VERIFY-001",
        "run_id": "RUN-VERIFY-001",
        "identity": EvidenceIdentity(
            base_revision=BASE_REVISION,
            candidate_revision=CANDIDATE_REVISION,
        ),
        "items": [
            EvidenceItem(
                kind="test-report",
                ref="artifacts/pytest.log",
                evidence_class=EvidenceClass.DETERMINISTIC_TEST,
                result=EvidenceResult.PASS,
                proves_revision=CANDIDATE_REVISION,
                provenance=Provenance(kind=ProvenanceKind.OBSERVED, source_ref="artifacts/pytest.log"),
            ),
            EvidenceItem(
                kind="diff",
                ref="artifacts/change.diff",
                evidence_class=EvidenceClass.REPOSITORY_REVISION,
                result=EvidenceResult.PASS,
                proves_revision=CANDIDATE_REVISION,
                provenance=Provenance(kind=ProvenanceKind.OBSERVED, source_ref="artifacts/change.diff"),
            ),
        ],
        "provenance": [Provenance(kind=ProvenanceKind.OBSERVED, source_ref="run-log")],
    }
    base.update(overrides)
    return EvidenceBundle.model_validate(base)


def approving_review(**overrides: object) -> ReviewDecision:
    base = {
        "work_item_id": "WI-VERIFY-001",
        "run_id": "RUN-VERIFY-001",
        "reviewer_role": "reviewer",
        "implementing_role_id": "builder",
        "outcome": ReviewOutcome.APPROVED,
        "reviewed_revision": CANDIDATE_REVISION,
        "evidence_refs": ["artifacts/pytest.log"],
        "decided_at": FINISHED_AT,
    }
    base.update(overrides)
    return ReviewDecision.model_validate(base)


def integration_spec(
    integration_id: str = "work-tracker",
    required: IntegrationHealthState = IntegrationHealthState.AUTHORIZED,
    *,
    with_auth: bool = True,
) -> IntegrationSpec:
    payload: dict[str, object] = {
        "schema_version": FOUNDRY_SCHEMA_VERSION,
        "id": integration_id,
        "kind": "integration",
        "transport": "api",
        "version": "1.0.0",
        "capabilities": ["work.read"],
        "permissions": {"write_requires": "explicit-authority"},
        "health": {"required": required.value},
    }
    if with_auth:
        payload["auth"] = {"method": "token", "credential_ref": "env:TRACKER_TOKEN"}
    return IntegrationSpec.model_validate(payload)


def health(
    integration_id: str,
    state: IntegrationHealthState,
    *,
    checked_at: datetime | None = FINISHED_AT,
) -> IntegrationHealth:
    return IntegrationHealth(
        integration_id=integration_id,
        state=state,
        checked_at=checked_at,
    )


def complete_receipt(*, lifecycle: WorkLifecycleState = WorkLifecycleState.IN_REVIEW, **overrides):
    """Build a receipt from a real compile, with every identity and limit recorded."""
    artifacts = compiled()
    receipt = build_execution_receipt(
        bundle=artifacts["bundle"],
        started_at=STARTED_AT,
        finished_at=FINISHED_AT,
        work_lifecycle_state=lifecycle,
        execution_state=ExecutionState.STOPPED,
        attained_evidence_states=[EvidenceState.IMPLEMENTED, EvidenceState.VALIDATED],
        not_required_evidence_states=[
            EvidenceState.RUNTIME_APPLIED,
            EvidenceState.RUNTIME_VERIFIED,
            EvidenceState.USER_ACCEPTED,
        ],
        project_lock=artifacts["lock"],
        registry=artifacts["registry"],
        base_revision=BASE_REVISION,
        candidate_revision=CANDIDATE_REVISION,
        evidence_bundle_id="EV-VERIFY-001",
        review_decision=approving_review(),
        permission_profile_version="1.0.0",
        budget_profile_version="1.0.0",
        limitations=[
            ReceiptLimitation(
                subject="runtime state",
                reason="this work item applies no runtime configuration",
                evidence_class=EvidenceClass.RUNTIME_READBACK,
            )
        ],
        findings=[
            RunFinding(
                id="F-1",
                disposition=FindingDisposition.RESIDUAL,
                summary="error paths are covered by unit tests only",
                follow_up_work_ref="WI-VERIFY-002",
            )
        ],
        budget=BudgetConsumption(retries_used=0, max_retry_budget=2),
        cleanup_state="workspace released",
        next_action="request independent review",
        **overrides,
    )
    return receipt, artifacts


def tracker(**overrides: object) -> TrackerProjection:
    base = {
        "work_item_id": "WI-VERIFY-001",
        "lifecycle_state": WorkLifecycleState.IN_REVIEW,
        "external_ref": "tracker://queue/17",
        "declared_required_evidence_states": [
            EvidenceState.IMPLEMENTED,
            EvidenceState.VALIDATED,
            EvidenceState.REVIEWED,
            EvidenceState.MERGED_INTEGRATED,
        ],
        "declared_not_required_evidence_states": [
            EvidenceState.RUNTIME_APPLIED,
            EvidenceState.RUNTIME_VERIFIED,
            EvidenceState.USER_ACCEPTED,
            EvidenceState.SYSTEM_VERIFIED,
        ],
        "observed_at": FINISHED_AT,
        "source_ref": "tracker-projection.yaml",
    }
    base.update(overrides)
    return TrackerProjection.model_validate(base)


def repository(**overrides: object) -> RepositoryEvidence:
    base = {
        "work_item_id": "WI-VERIFY-001",
        "base_revision": BASE_REVISION,
        "candidate_revision": CANDIDATE_REVISION,
        "integrated_revision": INTEGRATED_REVISION,
        "evidence_bundle": full_evidence_bundle(),
        "review_decision": approving_review(),
    }
    base.update(overrides)
    return RepositoryEvidence.model_validate(base)


def runtime(**overrides: object) -> RuntimeReadback:
    base = {
        "work_item_id": "WI-VERIFY-001",
        "observed": True,
        "applied_revision": INTEGRATED_REVISION,
        "expected_revision": INTEGRATED_REVISION,
        "integration_health": [health("work-tracker", IntegrationHealthState.HEALTHY)],
        "source_ref": "runtime-readback.json",
        "observed_at": FINISHED_AT,
    }
    base.update(overrides)
    return RuntimeReadback.model_validate(base)


STALE_OBSERVATION_AGE = timedelta(minutes=30)
