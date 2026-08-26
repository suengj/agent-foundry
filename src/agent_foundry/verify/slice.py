"""Validate one compiled slice with every validator that applies to it.

The gap this closes: a caller holding a handful of passing reports has no way to tell
whether the rest of the validators passed, were exempt, or were never invoked. AF8's
own end-to-end harness fell into exactly that — it aggregated four artifact checks and
called the result an acceptance, so a run carrying an unhealthy required integration
reported `accepted() == True` while `validate_integration_preflight` rejected the same
inputs on its own.

So this function runs *every* published validator, and where an input it needs was not
supplied it records a `ValidatorNotRun` rather than omitting it. `SliceValidation.accepted()`
is False whenever anything did not run. A partial verdict is not a verdict.

No rule lives here. Every check is imported from `verify.validators` and
`verify.explain`, so the CLI, a Python caller, and any later facade reach one
implementation by one route.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from agent_foundry.models.execution import ExecutionBundle
from agent_foundry.models.integrations import IntegrationHealth, IntegrationSpec
from agent_foundry.models.interaction import (
    EvidenceBundle,
    ExecutionReceipt,
    ReviewDecision,
)
from agent_foundry.models.policy import PermissionProfile
from agent_foundry.models.project import ClassificationFinding, ProjectManifest
from agent_foundry.models.registry import CapabilityRegistry, RoleContract
from agent_foundry.models.toolkit import ToolkitLock
from agent_foundry.models.verification import (
    SliceValidation,
    ValidationReport,
    ValidatorNotRun,
)
from agent_foundry.models.work import WorkItemContract
from agent_foundry.verify import claims
from agent_foundry.verify.independent import malformed_vocabulary_report
from agent_foundry.verify.explain import validate_decision_explainability
from agent_foundry.verify.receipt import receipt_artifacts
from agent_foundry.verify.validators import (
    validate_authority_ceiling,
    validate_contract_schema_compatibility,
    validate_evidence_bundle_completeness,
    validate_execution_bundle_completeness,
    validate_integration_preflight,
    validate_lifecycle_separation,
    validate_provenance_completeness,
    validate_receipt_completeness,
    validate_required_evidence,
    validate_role_separation,
    validate_toolkit_coherence,
    validate_work_dependency_graph,
    validate_write_scope_containment,
)


@dataclass(frozen=True)
class CompiledSlice:
    """Everything one compiled Work Item produced, plus what a run reported about it.

    The compile-time fields are required because the compiler has all of them: a caller
    that reached an `ExecutionBundle` necessarily holds the manifest, lock, registry and
    Work Item that produced it. The run-time fields are optional because V0.1 ships no
    runtime — and each one left unset makes the validators that need it *not run*, which
    is reported rather than quietly skipped.
    """

    work_item: WorkItemContract
    manifest: ProjectManifest
    project_lock: ToolkitLock
    registry: CapabilityRegistry
    bundle: ExecutionBundle

    # Every bundle authorized concurrently against this run, this one included. Role
    # separation is a property of the set, so a single-bundle list is a real answer
    # (one writer cannot collide with itself), not a missing input.
    concurrent_bundles: list[ExecutionBundle] = field(default_factory=list)
    work_items: list[WorkItemContract] = field(default_factory=list)
    permission_profiles: list[PermissionProfile] = field(default_factory=list)
    integrations: list[IntegrationSpec] = field(default_factory=list)
    integration_health: list[IntegrationHealth] = field(default_factory=list)
    required_integration_ids: list[str] | None = None
    """Integrations this work was required to have, or None to read the bundle's.

    These are not always the same set, and the difference matters. Resolution
    subtracts an integration whose observed health is below what its spec requires —
    correct, and fail-closed — but the compiled bundle then carries no trace of the
    request, so preflighting only what the bundle kept would report NOT_REQUIRED for an
    integration the caller asked for and could not have. Stating the requirement
    separately is what keeps a silently-dropped integration from reading as a pass.
    """
    classification_findings: list[ClassificationFinding] = field(default_factory=list)

    evidence_bundle: EvidenceBundle | None = None
    receipt: ExecutionReceipt | None = None
    review_decisions: list[ReviewDecision] = field(default_factory=list)

    now: datetime | None = None
    max_observation_age: timedelta | None = None


def _role(slice_: CompiledSlice) -> RoleContract | None:
    for role in slice_.registry.roles:
        if role.id == slice_.bundle.role_id:
            return role
    return None


def _permission_profile(slice_: CompiledSlice) -> PermissionProfile | None:
    task_toolkit = slice_.bundle.task_toolkit
    if task_toolkit is None or not task_toolkit.permission_profile_ids:
        return None
    wanted = task_toolkit.permission_profile_ids[0]
    for profile in slice_.permission_profiles:
        if profile.id == wanted:
            return profile
    return None


def validate_compiled_slice(slice_: CompiledSlice) -> SliceValidation:
    """Run every applicable validator over one compiled slice.

    Returns what ran and what could not, never a subset presented as a whole.
    """
    reports: list[ValidationReport] = []
    not_run: list[ValidatorNotRun] = []

    def skip(validator_id: str, reason: str) -> None:
        not_run.append(ValidatorNotRun(validator_id=validator_id, reason=reason))

    bundle = slice_.bundle
    work_item = slice_.work_item
    task_toolkit = bundle.task_toolkit
    subject_id = f"{bundle.work_item_id}/{bundle.run_id}"

    # Vocabulary first, through the same gate every individual validator uses. This
    # function dereferences the contracts it is handed — reading the role off the
    # bundle, the profile off the task toolkit, the required integrations off both —
    # before any validator sees them, so a value naming nothing in its vocabulary has
    # to be rejected here rather than reached past.
    malformed = malformed_vocabulary_report(
        claims.EXECUTION_BUNDLE_COMPLETENESS,
        "compiled-slice",
        subject_id,
        {
            "bundle": bundle,
            "work_item": work_item,
            "manifest": slice_.manifest,
            "project_lock": slice_.project_lock,
            "registry": slice_.registry,
            "evidence_bundle": slice_.evidence_bundle,
            "receipt": slice_.receipt,
        },
    )
    if malformed is not None:
        return SliceValidation(
            subject_id=subject_id,
            reports=[malformed],
            not_run=[
                ValidatorNotRun(
                    validator_id=validator_id,
                    reason=(
                        "a supplied contract carries a value from no known vocabulary, "
                        "so nothing downstream could be examined"
                    ),
                )
                for validator_id in sorted(
                    set(claims.VALIDATOR_IDS) - {claims.EXECUTION_BUNDLE_COMPLETENESS}
                )
            ],
        )

    # --- contracts ------------------------------------------------------------
    contracts: list[tuple[str, object]] = [
        ("work-item", work_item),
        ("project-manifest", slice_.manifest),
        ("toolkit-lock", slice_.project_lock),
        ("capability-registry", slice_.registry),
        ("execution-bundle", bundle),
    ]
    if task_toolkit is not None:
        contracts.append(("task-toolkit", task_toolkit))
    if slice_.evidence_bundle is not None:
        contracts.append(("evidence-bundle", slice_.evidence_bundle))
    if slice_.receipt is not None:
        contracts.append(("execution-receipt", slice_.receipt))
    reports.append(validate_contract_schema_compatibility(contracts))

    # --- work ------------------------------------------------------------------
    plan_items = slice_.work_items or [work_item]
    reports.append(validate_work_dependency_graph(plan_items))

    # --- toolkit ---------------------------------------------------------------
    if task_toolkit is None:
        skip(claims.TOOLKIT_COHERENCE, "the execution bundle carries no task toolkit")
    else:
        reports.append(
            validate_toolkit_coherence(task_toolkit, slice_.project_lock, slice_.registry)
        )

    # --- authority --------------------------------------------------------------
    role = _role(slice_)
    permission_profile = _permission_profile(slice_)
    if bundle.authority is None:
        skip(claims.AUTHORITY_CEILING, "the execution bundle carries no compiled authority")
        skip(claims.WRITE_SCOPE_CONTAINMENT, "the execution bundle carries no compiled authority")
    elif task_toolkit is None:
        skip(claims.AUTHORITY_CEILING, "the execution bundle carries no task toolkit")
        reports.append(
            validate_write_scope_containment(
                bundle.authority,
                work_item=work_item,
                role=role,
                manifest=slice_.manifest,
            )
        )
    else:
        reports.append(
            validate_authority_ceiling(
                bundle.authority,
                work_item=work_item,
                manifest=slice_.manifest,
                task_toolkit=task_toolkit,
                role=role,
                permission_profile=permission_profile,
                registry=slice_.registry,
            )
        )
        reports.append(
            validate_write_scope_containment(
                bundle.authority,
                work_item=work_item,
                role=role,
                manifest=slice_.manifest,
            )
        )

    # --- roles -------------------------------------------------------------------
    concurrent = slice_.concurrent_bundles or [bundle]
    reports.append(
        validate_role_separation(concurrent, review_decisions=slice_.review_decisions)
    )

    # --- integrations --------------------------------------------------------------
    required_integration_ids = sorted(
        set(bundle.integration_ids)
        | set(slice_.required_integration_ids or [])
    )
    reports.append(
        validate_integration_preflight(
            slice_.integrations,
            required_ids=required_integration_ids,
            observed_health=slice_.integration_health,
            now=slice_.now,
            max_observation_age=slice_.max_observation_age,
        )
    )

    # --- bundle structure -----------------------------------------------------------
    reports.append(validate_execution_bundle_completeness(bundle))
    reports.append(validate_provenance_completeness(bundle))
    reports.append(
        validate_decision_explainability(
            bundle,
            manifest=slice_.manifest,
            classification_findings=slice_.classification_findings,
            receipt=slice_.receipt,
        )
    )

    # --- evidence ---------------------------------------------------------------------
    if slice_.evidence_bundle is None:
        skip(claims.REQUIRED_EVIDENCE, "no evidence bundle was supplied for this run")
        skip(claims.EVIDENCE_BUNDLE_COMPLETENESS, "no evidence bundle was supplied for this run")
    else:
        reports.append(validate_required_evidence(work_item, slice_.evidence_bundle))
        reports.append(validate_evidence_bundle_completeness(slice_.evidence_bundle))

    # --- receipt -----------------------------------------------------------------------
    if slice_.receipt is None:
        skip(claims.RECEIPT_COMPLETENESS, "no execution receipt was supplied for this run")
        skip(claims.LIFECYCLE_SEPARATION, "no execution receipt was supplied for this run")
    else:
        reports.append(
            validate_receipt_completeness(
                slice_.receipt,
                artifacts=receipt_artifacts(
                    bundle,
                    task_toolkit=task_toolkit,
                    project_lock=slice_.project_lock,
                    registry=slice_.registry,
                ),
            )
        )
        reports.append(
            validate_lifecycle_separation(
                slice_.receipt,
                required_evidence_states=slice_.receipt.attained_evidence_states,
            )
        )

    validation = SliceValidation(
        subject_id=subject_id,
        reports=reports,
        not_run=sorted(not_run, key=lambda item: item.validator_id),
    )
    _assert_every_validator_accounted_for(validation)
    return validation


def _assert_every_validator_accounted_for(validation: SliceValidation) -> None:
    """Post-condition: no published validator silently disappears from a slice verdict.

    This is the specific failure this module exists to prevent, so it is checked here
    rather than left to a test: a validator added to the catalog and not wired in would
    otherwise reduce the verdict's coverage without changing its answer.
    """
    accounted = set(validation.ran()) | {item.validator_id for item in validation.not_run}
    missing = sorted(set(claims.VALIDATOR_IDS) - accounted)
    if missing:
        raise AssertionError(
            "slice validation neither ran nor recorded a skip for: "
            + ", ".join(missing)
            + "; every entry in verify.claims.VALIDATOR_IDS must be accounted for"
        )


__all__ = ["CompiledSlice", "validate_compiled_slice"]
