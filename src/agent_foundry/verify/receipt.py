"""Execution receipt assembly and artifact identity.

The receipt records what happened. It is not a second live work tracker, so nothing
here reads or writes external state: everything it reports is supplied by the caller
as already-observed facts.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from agent_foundry.models.base import FOUNDRY_SCHEMA_VERSION, FoundryModel
from agent_foundry.models.common import EvidenceState, ExecutionState, WorkLifecycleState
from agent_foundry.models.execution import ExecutionBundle
from agent_foundry.models.interaction import (
    ArtifactIdentity,
    BudgetConsumption,
    ExecutionReceipt,
    ReceiptLimitation,
    ReviewDecision,
    RunFinding,
)
from agent_foundry.models.io import dump_json
from agent_foundry.models.registry import CapabilityRegistry
from agent_foundry.models.toolkit import TaskToolkit, ToolkitLock

ARTIFACT_EXECUTION_BUNDLE = "execution-bundle"
ARTIFACT_TASK_TOOLKIT = "task-toolkit"
ARTIFACT_PROJECT_LOCK = "toolkit-lock"
ARTIFACT_REGISTRY = "capability-registry"


def artifact_digest(model: FoundryModel) -> str:
    """Content digest of a contract, over its deterministic serialization.

    `dump_json` is byte-stable and sorted, so equal contracts digest equally
    regardless of construction order. This binds a receipt to one artifact body; it
    is not an independent derivation of that body's correctness.
    """
    return hashlib.sha256(dump_json(model)).hexdigest()


def _identity(kind: str, ref: str, model: FoundryModel, version: str | None = None) -> ArtifactIdentity:
    return ArtifactIdentity(kind=kind, ref=ref, digest=artifact_digest(model), version=version)


def build_execution_receipt(
    *,
    bundle: ExecutionBundle,
    started_at: datetime,
    work_lifecycle_state: WorkLifecycleState,
    execution_state: ExecutionState,
    attained_evidence_states: list[EvidenceState],
    not_required_evidence_states: list[EvidenceState],
    finished_at: datetime | None = None,
    project_lock: ToolkitLock | None = None,
    registry: CapabilityRegistry | None = None,
    base_revision: str | None = None,
    candidate_revision: str | None = None,
    integrated_revision: str | None = None,
    evidence_bundle_id: str | None = None,
    review_decision: ReviewDecision | None = None,
    runtime_verification_ref: str | None = None,
    findings: list[RunFinding] | None = None,
    limitations: list[ReceiptLimitation] | None = None,
    budget: BudgetConsumption | None = None,
    permission_profile_version: str | None = None,
    budget_profile_version: str | None = None,
    adapter_versions: dict[str, str] | None = None,
    cleanup_state: str | None = None,
    next_action: str | None = None,
) -> ExecutionReceipt:
    """Assemble a receipt from a compiled bundle and observed run facts.

    `evidence_state` is filled from the attained list as the highest rung reached, or
    `NOT_REQUIRED` when nothing was required. It is a projection for existing
    consumers; the two lists are the record.
    """
    from agent_foundry.verify.independent import EVIDENCE_STATE_PROGRESSION

    identities: list[ArtifactIdentity] = [
        _identity(ARTIFACT_EXECUTION_BUNDLE, f"{bundle.work_item_id}/{bundle.run_id}", bundle)
    ]
    if bundle.task_toolkit is not None:
        identities.append(
            _identity(
                ARTIFACT_TASK_TOOLKIT,
                bundle.task_toolkit.work_item_id,
                bundle.task_toolkit,
            )
        )
    if project_lock is not None:
        identities.append(
            _identity(
                ARTIFACT_PROJECT_LOCK,
                project_lock.project_name,
                project_lock,
                version=project_lock.foundry_compat,
            )
        )
    if registry is not None:
        identities.append(
            _identity(ARTIFACT_REGISTRY, "builtin", registry, version=registry.foundry_compat)
        )

    attained = list(attained_evidence_states)
    ranked = [state for state in EVIDENCE_STATE_PROGRESSION if state in attained]
    projection = ranked[-1] if ranked else EvidenceState.NOT_REQUIRED

    permission_profile_id: str | None = None
    if bundle.task_toolkit is not None and bundle.task_toolkit.permission_profile_ids:
        permission_profile_id = bundle.task_toolkit.permission_profile_ids[0]

    return ExecutionReceipt(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        work_item_id=bundle.work_item_id,
        run_id=bundle.run_id,
        role_id=bundle.role_id,
        work_lifecycle_state=work_lifecycle_state,
        execution_state=execution_state,
        evidence_state=projection,
        started_at=started_at,
        finished_at=finished_at,
        evidence_bundle_id=evidence_bundle_id,
        attained_evidence_states=attained,
        not_required_evidence_states=list(not_required_evidence_states),
        workflow_id=bundle.task_toolkit.workflow_id if bundle.task_toolkit else None,
        base_revision=base_revision,
        candidate_revision=candidate_revision,
        integrated_revision=integrated_revision,
        artifact_identities=identities,
        adapter_versions=dict(adapter_versions or {}),
        permission_profile_id=permission_profile_id,
        permission_profile_version=permission_profile_version,
        budget_profile_id=bundle.budget_profile_id,
        budget_profile_version=budget_profile_version,
        review_decision=review_decision,
        runtime_verification_ref=runtime_verification_ref,
        findings=list(findings or []),
        limitations=list(limitations or []),
        budget=budget,
        cleanup_state=cleanup_state,
        next_action=next_action,
    )


def receipt_artifacts(
    bundle: ExecutionBundle,
    *,
    task_toolkit: TaskToolkit | None = None,
    project_lock: ToolkitLock | None = None,
    registry: CapabilityRegistry | None = None,
) -> dict[str, FoundryModel]:
    """Artifacts a receipt's declared identities are checked against."""
    artifacts: dict[str, FoundryModel] = {ARTIFACT_EXECUTION_BUNDLE: bundle}
    toolkit = task_toolkit if task_toolkit is not None else bundle.task_toolkit
    if toolkit is not None:
        artifacts[ARTIFACT_TASK_TOOLKIT] = toolkit
    if project_lock is not None:
        artifacts[ARTIFACT_PROJECT_LOCK] = project_lock
    if registry is not None:
        artifacts[ARTIFACT_REGISTRY] = registry
    return artifacts
