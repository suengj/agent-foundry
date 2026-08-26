"""One pass of the V0.1 vertical slice, from a repository path to an ExecutionReceipt.

Every stage calls a published Core API. Nothing here re-implements a rule: the
harness's job is to hold the seams together and hand back what each stage produced,
so a test can assert on the artifacts rather than on a shell transcript.

Two things this harness supplies that the Core does not, and that the AF8 report
names as gaps rather than hides:

* **AdoptionChangeSet -> DecompositionInput.** No Core function turns a planned
  adoption change into a causal unit of work. `adoption_gaps` below is the mapping
  this harness uses; a different consumer would reasonably choose another, which is
  why it is stated here in the open instead of being smuggled into `agent_foundry`.
* **Run-time evidence.** `EvidenceBundle`, `ReviewDecision`, `TrackerProjection` and
  `RepositoryEvidence` describe what an execution runtime observed. V0.1 ships no
  runtime, so the harness stands in for one. These are inputs to verification, not
  outputs of it, and the receipt records the substitution as a limitation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from agent_foundry.adopt import plan_adoption
from agent_foundry.compile import compile_work_item
from agent_foundry.inspect import inspect_project
from agent_foundry.models import (
    AdoptionAction,
    AdoptionChangeItem,
    AdoptionChangeSet,
    AdoptionGap,
    AuthorityRequirement,
    CapabilityRegistry,
    ConsequenceClass,
    DecompositionInput,
    EvidenceBundle,
    EvidenceClass,
    EvidenceIdentity,
    EvidenceItem,
    EvidenceResult,
    EvidenceState,
    ExecutionBundle,
    ExecutionReceipt,
    ExecutionState,
    ExternalEffectClass,
    IntegrationHealth,
    IntegrationSpec,
    OutcomeCapability,
    ProjectIntake,
    ProjectManifest,
    Provenance,
    ProvenanceKind,
    ReceiptLimitation,
    ReconciliationReport,
    RepositoryEvidence,
    ReviewDecision,
    ReviewOutcome,
    Reversibility,
    TaskToolkit,
    ToolkitLock,
    ToolkitResolution,
    TrackerProjection,
    ValidationReport,
    WorkClass,
    WorkItemContract,
    WorkLifecycleState,
    WorkObjective,
    WorkPlan,
)
from agent_foundry.render import render_execution_bundle_markdown
from agent_foundry.toolkit import (
    check_integrations,
    default_registry as _builtin_registry,
    resolve_toolkit,
)
from agent_foundry.verify import build_execution_receipt, reconcile_work_item
from agent_foundry.verify.cli_api import validate_artifact

# Fixed clock. Every timestamp the harness produces is derived from these, so two
# runs a week apart serialize identically and a digest comparison means something.
STARTED_AT = datetime(2026, 5, 4, 9, 0, 0, tzinfo=timezone.utc)
FINISHED_AT = datetime(2026, 5, 4, 10, 30, 0, tzinfo=timezone.utc)

BASE_REVISION = "e2e-base-0000000000000000000000000000000000"
CANDIDATE_REVISION = "e2e-cand-0000000000000000000000000000000000"

# Adoption actions that describe work someone has to do. KEEP asserts the current
# state is already right, and DEFER records a decision not to act now; turning
# either into a Work Item would manufacture work out of a decision to do none.
ACTIONABLE_ACTIONS: frozenset[AdoptionAction] = frozenset(
    {
        AdoptionAction.CONSOLIDATE,
        AdoptionAction.WRAP,
        AdoptionAction.HARDEN,
        AdoptionAction.MIGRATE,
        AdoptionAction.BLOCK,
    }
)

_CONSEQUENCE_BY_AUTHORITY: dict[AuthorityRequirement, ConsequenceClass] = {
    AuthorityRequirement.EXPLICIT_AUTHORITY: ConsequenceClass.HIGH,
    AuthorityRequirement.BOUNDED_POLICY: ConsequenceClass.MEDIUM,
    AuthorityRequirement.NONE: ConsequenceClass.LOW,
}


def _gap_id(change: AdoptionChangeItem) -> str:
    slug = change.target.replace(":", "-").replace("_", "-").replace(".", "-").lower()
    return f"{change.action.value.lower()}-{slug}"


def adoption_gaps(change_set: AdoptionChangeSet) -> list[AdoptionGap]:
    """Map planned adoption changes onto causal adoption gaps, in a stable order."""
    gaps: list[AdoptionGap] = []
    for change in change_set.changes:
        if change.action not in ACTIONABLE_ACTIONS:
            continue
        gaps.append(
            AdoptionGap(
                id=_gap_id(change),
                target=change.target,
                action=change.action,
                rationale=change.rationale or change.evidence.summary,
                # The paths the change is evidenced by are the paths it touches, and
                # they are the only repository-relative bound the change set carries.
                # A change with no located evidence contributes no scope, and the
                # bundle compiled from it grants no write — which is the correct
                # outcome for a change whose target does not exist yet.
                scope=tuple(sorted(change.evidence.evidence_refs)),
                suggested_work_class=WorkClass.ADOPTION,
                authority_class=ExternalEffectClass.REPOSITORY_WRITE,
                consequence_class=_CONSEQUENCE_BY_AUTHORITY[change.authority_requirement],
                reversibility=Reversibility.VERSIONED,
                blocker=change.action is AdoptionAction.BLOCK,
            )
        )
    return sorted(gaps, key=lambda gap: gap.id)


def decomposition_input(change_set: AdoptionChangeSet, project_name: str) -> DecompositionInput:
    objective = WorkObjective(
        id="OBJ-ADOPT",
        title=f"Adopt {project_name} as an AI-native execution environment",
        description=(
            "Apply the planned adoption change set so agent execution in this "
            "repository is bounded, evidenced, and reviewable."
        ),
    )
    outcome = OutcomeCapability(
        id="OUT-ADOPT",
        objective_id=objective.id,
        title="Adoption changes applied",
        description="Every actionable adoption change is closed with evidence.",
    )
    return DecompositionInput(
        objective=objective,
        outcomes=(outcome,),
        adoption_gaps=tuple(adoption_gaps(change_set)),
    )


def _evidence_bundle(work_item: WorkItemContract, run_id: str) -> EvidenceBundle:
    """Stand in for what a runtime would report, typed to what the item requires.

    One typed, passing item per required class. Anything the item does not require
    is absent rather than fabricated, so a bundle never proves more than it was asked
    for.
    """
    class_by_requirement = {member.value: member for member in EvidenceClass}
    items: list[EvidenceItem] = []
    for requirement in sorted(work_item.required_evidence):
        evidence_class = class_by_requirement.get(requirement)
        if evidence_class is None:
            continue
        items.append(
            EvidenceItem(
                kind=requirement,
                ref=f"artifacts/{requirement}.log",
                evidence_class=evidence_class,
                result=EvidenceResult.PASS,
                proves_revision=CANDIDATE_REVISION,
                observed_at=FINISHED_AT,
                provenance=Provenance(
                    kind=ProvenanceKind.OBSERVED,
                    source_ref=f"artifacts/{requirement}.log",
                ),
            )
        )
    return EvidenceBundle.model_validate(
        {
            "schema_version": work_item.schema_version,
            "work_item_id": work_item.id,
            "run_id": run_id,
            "identity": EvidenceIdentity(
                base_revision=BASE_REVISION,
                candidate_revision=CANDIDATE_REVISION,
            ),
            "items": items,
            "provenance": [
                Provenance(kind=ProvenanceKind.OBSERVED, source_ref="artifacts/run.log")
            ],
        }
    )


def registry_with_builder_write_scope(write_scope: list[str]) -> CapabilityRegistry:
    """The builtin registry with the builder role's write scope replaced.

    The builtin `builder` role declares `write_scope=["src/", "tests/"]`, and compiled
    write authority is the intersection of that with the Work Item scope. Any project
    whose changes land elsewhere — `AGENTS.md`, `Makefile`, `.github/`, `.foundry/`,
    which is most of what adoption touches — intersects to nothing and compiles to a
    bundle that may write nowhere.

    `CapabilityRegistry` is a supported input to every resolve/compile entry point, so
    supplying a project-appropriate one is the product's own answer. What AF8 records
    is that nothing derives it: the default is a project-shape assumption baked into
    core, and a consumer has to notice and override it by hand.
    """
    builtin = _builtin_registry()
    roles = [
        role.model_copy(update={"write_scope": list(write_scope)})
        if role.id == "builder"
        else role
        for role in builtin.roles
    ]
    return builtin.model_copy(update={"roles": roles})


@dataclass(frozen=True)
class PipelineResult:
    """Everything one pass of the slice produced, stage by stage."""

    project_path: Path
    intake: ProjectIntake
    manifest: ProjectManifest
    change_set: AdoptionChangeSet
    work_plan: WorkPlan
    work_item: WorkItemContract
    resolution: ToolkitResolution
    project_lock: ToolkitLock
    integration_health: list[IntegrationHealth]
    task_toolkit: TaskToolkit
    bundle: ExecutionBundle
    markdown: str
    registry: CapabilityRegistry
    validation_reports: list[ValidationReport]
    evidence_bundle: EvidenceBundle
    receipt: ExecutionReceipt
    reconciliation: ReconciliationReport

    def accepted(self) -> bool:
        return all(report.accepted() for report in self.validation_reports)

    def rejecting(self) -> list[str]:
        return [
            f"{finding.validator_id}/{finding.outcome.value}: {finding.message}"
            for report in self.validation_reports
            for finding in report.rejecting()
        ]


def run_pipeline(
    project_path: str | Path,
    *,
    run_id: str = "RUN-E2E-001",
    role_id: str = "builder",
    reviewer_role_id: str = "reviewer",
    integrations: list[IntegrationSpec] | None = None,
    desired_integration_ids: list[str] | None = None,
    observed_health: list[IntegrationHealth] | None = None,
    work_item_id: str | None = None,
    registry: CapabilityRegistry | None = None,
) -> PipelineResult:
    """Run repository -> receipt once, returning every intermediate contract.

    `work_item_id` selects which decomposed item is compiled; without it the first
    item in the plan's own sorted order is used, which is stable across runs.
    """
    project = Path(project_path)
    integration_list = list(integrations or [])
    desired_ids = list(desired_integration_ids or [])
    health_list = list(observed_health or [])

    intake = inspect_project(project)
    plan = plan_adoption(intake)
    manifest = plan.manifest
    project_name = manifest.project.name or project.name

    from agent_foundry.work import decompose_work

    work_plan = decompose_work(decomposition_input(plan.change_set, project_name))
    if not work_plan.work_items:
        raise AssertionError(
            f"adoption of {project_name!r} produced no actionable work items; "
            "there is nothing to compile"
        )
    if work_item_id is None:
        work_item = work_plan.work_items[0]
    else:
        work_item = next(item for item in work_plan.work_items if item.id == work_item_id)

    reg = registry if registry is not None else _builtin_registry()

    resolution, project_lock = resolve_toolkit(
        manifest,
        registry=reg,
        integrations=integration_list,
        integration_health=health_list,
        desired_integration_ids=desired_ids,
    )

    integration_health = check_integrations(
        integration_list,
        required_ids=sorted(project_lock.integration_ids),
        observed_health=health_list,
    )

    compiled = compile_work_item(
        work_item,
        manifest,
        project_lock,
        role_id,
        run_id,
        registry=reg,
        integrations=integration_list,
        integration_health=health_list,
        observations=list(intake.observations),
        conventions=list(intake.conventions),
    )
    markdown = render_execution_bundle_markdown(compiled.bundle)

    reports = validate_artifact(
        "execution-bundle",
        compiled.bundle,
        project_lock=project_lock,
        registry=reg,
        work_item=work_item,
    )

    evidence_bundle = _evidence_bundle(work_item, run_id)
    reports.extend(validate_artifact("evidence-bundle", evidence_bundle))

    review = ReviewDecision(
        work_item_id=work_item.id,
        run_id=run_id,
        reviewer_role=reviewer_role_id,
        implementing_role_id=role_id,
        outcome=ReviewOutcome.APPROVED,
        reviewed_revision=CANDIDATE_REVISION,
        evidence_refs=[item.ref for item in evidence_bundle.items],
        decided_at=FINISHED_AT,
    )

    receipt = build_execution_receipt(
        bundle=compiled.bundle,
        started_at=STARTED_AT,
        finished_at=FINISHED_AT,
        work_lifecycle_state=WorkLifecycleState.IN_REVIEW,
        execution_state=ExecutionState.STOPPED,
        attained_evidence_states=[EvidenceState.IMPLEMENTED, EvidenceState.VALIDATED],
        not_required_evidence_states=[
            EvidenceState.RUNTIME_APPLIED,
            EvidenceState.RUNTIME_VERIFIED,
            EvidenceState.USER_ACCEPTED,
        ],
        project_lock=project_lock,
        registry=reg,
        base_revision=BASE_REVISION,
        candidate_revision=CANDIDATE_REVISION,
        evidence_bundle_id=f"EV-{run_id}",
        review_decision=review,
        permission_profile_version=project_lock.permission_profile_version,
        budget_profile_version=project_lock.budget_profile_version,
        limitations=[
            ReceiptLimitation(
                subject="execution runtime",
                reason=(
                    "V0.1 compiles and verifies contracts; no runtime executed this "
                    "bundle, so evidence was supplied by the end-to-end harness"
                ),
            )
        ],
    )
    reports.extend(validate_artifact("execution-receipt", receipt))

    reconciliation = reconcile_work_item(
        work_item=work_item,
        tracker=TrackerProjection(
            work_item_id=work_item.id,
            lifecycle_state=WorkLifecycleState.IN_REVIEW,
            declared_required_evidence_states=[
                EvidenceState.IMPLEMENTED,
                EvidenceState.VALIDATED,
            ],
            declared_not_required_evidence_states=[
                EvidenceState.RUNTIME_APPLIED,
                EvidenceState.RUNTIME_VERIFIED,
                EvidenceState.USER_ACCEPTED,
            ],
            observed_at=FINISHED_AT,
            source_ref="tracker://e2e",
        ),
        repository=RepositoryEvidence(
            work_item_id=work_item.id,
            base_revision=BASE_REVISION,
            candidate_revision=CANDIDATE_REVISION,
            evidence_bundle=evidence_bundle,
            review_decision=review,
            execution_state=ExecutionState.STOPPED,
        ),
    )

    return PipelineResult(
        project_path=project,
        intake=intake,
        manifest=manifest,
        change_set=plan.change_set,
        work_plan=work_plan,
        work_item=work_item,
        resolution=resolution,
        project_lock=project_lock,
        integration_health=integration_health,
        task_toolkit=compiled.task_toolkit,
        bundle=compiled.bundle,
        markdown=markdown,
        registry=reg,
        validation_reports=reports,
        evidence_bundle=evidence_bundle,
        receipt=receipt,
        reconciliation=reconciliation,
    )
