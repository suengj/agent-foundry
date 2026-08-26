"""Artifact-kind dispatch for the `agent-foundry validate` subcommand.

This module holds no validation logic. It decides *which* published validator a
loaded artifact is subject to and returns their reports unchanged, so the CLI and a
Python caller reach the same functions by the same route. If a check ever needs to
exist here, it belongs in `verify.validators` instead — a second implementation
behind a second surface is the failure mode this file is shaped to prevent.
"""

from __future__ import annotations

from typing import Any, Callable

from agent_foundry.models.base import FoundryModel
from agent_foundry.models.execution import ExecutionBundle
from agent_foundry.models.interaction import EvidenceBundle, ExecutionReceipt
from agent_foundry.models.project import ProjectManifest
from agent_foundry.models.registry import CapabilityRegistry, RoleContract
from agent_foundry.models.toolkit import TaskToolkit, ToolkitLock
from agent_foundry.models.verification import (
    SliceValidation,
    ValidationReport,
    ValidatorNotRun,
)
from agent_foundry.models.work import WorkItemContract
from agent_foundry.verify import claims
from agent_foundry.verify.validators import (
    validate_contract_schema_compatibility,
    validate_evidence_bundle_completeness,
    validate_execution_bundle_completeness,
    validate_lifecycle_separation,
    validate_provenance_completeness,
    validate_receipt_completeness,
    validate_toolkit_coherence,
    validate_work_dependency_graph,
    validate_write_scope_containment,
)

# Artifact kinds this subcommand can validate, in the order a caller meets them
# walking the pipeline. The key is what `--kind` accepts.
ARTIFACT_KINDS: tuple[str, ...] = (
    "work-item",
    "task-toolkit",
    "execution-bundle",
    "evidence-bundle",
    "execution-receipt",
)

_MODEL_BY_KIND: dict[str, type[FoundryModel]] = {
    "work-item": WorkItemContract,
    "task-toolkit": TaskToolkit,
    "execution-bundle": ExecutionBundle,
    "evidence-bundle": EvidenceBundle,
    "execution-receipt": ExecutionReceipt,
}


class ValidateInputError(ValueError):
    """Raised when the caller has not supplied what a kind's validators require."""


def model_for_kind(kind: str) -> type[FoundryModel]:
    try:
        return _MODEL_BY_KIND[kind]
    except KeyError:
        raise ValidateInputError(
            f"unknown artifact kind {kind!r}; expected one of {', '.join(ARTIFACT_KINDS)}"
        ) from None


def _role_from_registry(role_id: str, registry: CapabilityRegistry | None) -> RoleContract | None:
    if registry is None:
        return None
    for role in registry.roles:
        if role.id == role_id:
            return role
    return None


def _bundle_reports(
    bundle: ExecutionBundle,
    project_lock: ToolkitLock | None,
    registry: CapabilityRegistry | None,
    work_item: WorkItemContract | None,
    manifest: ProjectManifest | None,
) -> list[ValidationReport]:
    reports = [
        validate_execution_bundle_completeness(bundle),
        validate_provenance_completeness(bundle),
    ]
    # Write-scope containment is a claim about the bundle *against the work item that
    # bounds it*. Without that item there is no outer bound to check against, so the
    # check is skipped rather than run against a stand-in that would grant anything.
    if bundle.authority is not None and work_item is not None:
        reports.append(
            validate_write_scope_containment(
                bundle.authority,
                work_item=work_item,
                role=_role_from_registry(bundle.role_id, registry),
                manifest=manifest,
            )
        )
    if bundle.task_toolkit is not None and project_lock is not None and registry is not None:
        reports.append(
            validate_toolkit_coherence(bundle.task_toolkit, project_lock, registry)
        )
    return reports


# Validators that apply to each artifact kind, beyond schema compatibility, which
# applies to all of them. A validator listed here and not run for lack of an input is
# reported as `not_run`; one that is not listed does not apply to the kind at all.
_APPLICABLE_BY_KIND: dict[str, tuple[str, ...]] = {
    "work-item": (claims.WORK_DEPENDENCY_GRAPH,),
    "task-toolkit": (claims.TOOLKIT_COHERENCE,),
    "execution-bundle": (
        claims.EXECUTION_BUNDLE_COMPLETENESS,
        claims.PROVENANCE_COMPLETENESS,
        claims.WRITE_SCOPE_CONTAINMENT,
        claims.TOOLKIT_COHERENCE,
    ),
    "evidence-bundle": (claims.EVIDENCE_BUNDLE_COMPLETENESS,),
    "execution-receipt": (claims.RECEIPT_COMPLETENESS, claims.LIFECYCLE_SEPARATION),
}


def validate_artifact(
    kind: str,
    artifact: FoundryModel,
    *,
    project_lock: ToolkitLock | None = None,
    registry: CapabilityRegistry | None = None,
    work_item: WorkItemContract | None = None,
    manifest: ProjectManifest | None = None,
) -> SliceValidation:
    """Run every published validator that applies to *artifact*, and say what did not.

    A validator whose additional inputs were not supplied is *not* run against a
    stand-in — `validate_toolkit_coherence` without the pinned project lock would
    compare a task toolkit to nothing and pass — and it is not silently omitted either.
    It is recorded in `not_run`, so a caller can tell a passing subset from a verdict.

    This checks one artifact. The verdict over a whole compiled slice is
    `agent_foundry.verify.validate_compiled_slice`, which covers every validator in the
    catalog rather than the handful one artifact kind can support.
    """
    reports: list[ValidationReport] = [
        validate_contract_schema_compatibility([(kind, artifact)])
    ]

    handlers: dict[str, Callable[[Any], list[ValidationReport]]] = {
        "work-item": lambda item: [validate_work_dependency_graph([item])],
        "task-toolkit": lambda toolkit: (
            [validate_toolkit_coherence(toolkit, project_lock, registry)]
            if project_lock is not None and registry is not None
            else []
        ),
        "execution-bundle": lambda bundle: _bundle_reports(
            bundle, project_lock, registry, work_item, manifest
        ),
        "evidence-bundle": lambda bundle: [validate_evidence_bundle_completeness(bundle)],
        "execution-receipt": lambda receipt: [
            validate_receipt_completeness(receipt),
            validate_lifecycle_separation(receipt),
        ],
    }

    handler = handlers.get(kind)
    if handler is None:
        raise ValidateInputError(
            f"unknown artifact kind {kind!r}; expected one of {', '.join(ARTIFACT_KINDS)}"
        )
    reports.extend(handler(artifact))

    ran = {finding.validator_id for report in reports for finding in report.findings}
    not_run = [
        ValidatorNotRun(
            validator_id=validator_id,
            reason=_MISSING_INPUT_REASON.get(
                validator_id, "a required input was not supplied"
            ),
        )
        for validator_id in _APPLICABLE_BY_KIND.get(kind, ())
        if validator_id not in ran
    ]
    return SliceValidation(
        subject_id=f"{kind}:{_subject_id(artifact)}",
        reports=reports,
        not_run=sorted(not_run, key=lambda item: item.validator_id),
    )


_MISSING_INPUT_REASON: dict[str, str] = {
    claims.TOOLKIT_COHERENCE: "--toolkit-lock was not supplied, so the task toolkit "
    "has no pinned lock to be checked against",
    claims.WRITE_SCOPE_CONTAINMENT: "--work-item was not supplied, so a granted write "
    "path has no work item scope to be contained by",
}


def _subject_id(artifact: FoundryModel) -> str:
    for attribute in ("work_item_id", "id", "project_name"):
        value = getattr(artifact, attribute, None)
        if value:
            return str(value)
    return "unknown"


__all__ = [
    "ARTIFACT_KINDS",
    "ValidateInputError",
    "model_for_kind",
    "validate_artifact",
]
