"""Build adoption change sets from intake evidence."""

from __future__ import annotations

from agent_foundry.adopt.authority import AuthorityAxis, authority_axis_for_target
from agent_foundry.models.base import FOUNDRY_SCHEMA_VERSION
from agent_foundry.models.common import (
    AdoptionAction,
    AdoptionChangeStatus,
    AuthorityRequirement,
    Autonomy,
    ExternalEffectClass,
    IntakeMode,
    Provenance,
    ProvenanceKind,
)
from agent_foundry.models.project import (
    AdoptionChangeItem,
    AdoptionChangeSet,
    AdoptionEvidence,
    ProjectIntake,
    ProjectManifest,
)


def _evidence(
    summary: str,
    *,
    kind: ProvenanceKind,
    source_ref: str | None = None,
    confidence: float | None = None,
    evidence_refs: list[str] | None = None,
    verbatim: str | None = None,
) -> AdoptionEvidence:
    return AdoptionEvidence(
        summary=summary,
        provenance=Provenance(kind=kind, confidence=confidence, source_ref=source_ref),
        evidence_refs=sorted(evidence_refs or []),
        verbatim=verbatim,
    )


def _change(
    *,
    target: str,
    action: AdoptionAction,
    summary: str,
    kind: ProvenanceKind,
    authority_requirement: AuthorityRequirement,
    status: AdoptionChangeStatus,
    source_ref: str | None = None,
    confidence: float | None = None,
    evidence_refs: list[str] | None = None,
    verbatim: str | None = None,
    rationale: str | None = None,
    priority: int | None = None,
) -> AdoptionChangeItem:
    return AdoptionChangeItem(
        target=target,
        action=action,
        evidence=_evidence(
            summary,
            kind=kind,
            source_ref=source_ref,
            confidence=confidence,
            evidence_refs=evidence_refs,
            verbatim=verbatim,
        ),
        authority_requirement=authority_requirement,
        status=status,
        rationale=rationale,
        priority=priority,
    )


def _observation_subjects(intake: ProjectIntake) -> set[str]:
    return {observation.subject for observation in intake.observations}


def _observation_refs(intake: ProjectIntake, subject: str) -> list[str]:
    """Source refs actually observed for a subject — never fabricated."""
    return sorted(
        {
            observation.provenance.source_ref
            for observation in intake.observations
            if observation.subject == subject and observation.provenance.source_ref
        }
    )


def _primary_ref(refs: list[str]) -> str | None:
    return refs[0] if refs else None


def _specific_ref(source_ref: str | None, refs: list[str]) -> str | None:
    """Prefer a located file over a bare project-root source_ref."""
    if source_ref and source_ref not in {".", "./"}:
        return source_ref
    return _primary_ref(refs)


def _agent_surface_refs(intake: ProjectIntake) -> list[str]:
    return _observation_refs(intake, "agent-instruction-surface")


def _bootstrap_changes(intake: ProjectIntake) -> list[AdoptionChangeItem]:
    subjects = _observation_subjects(intake)
    changes: list[AdoptionChangeItem] = []

    if "foundry-artifact" not in subjects:
        changes.append(
            _change(
                target="foundry-project-declaration",
                action=AdoptionAction.MIGRATE,
                summary="Bootstrap owner-declared project characteristics in .foundry/project.yaml",
                kind=ProvenanceKind.INFERRED,
                authority_requirement=AuthorityRequirement.BOUNDED_POLICY,
                status=AdoptionChangeStatus.PROPOSED,
                rationale="Greenfield projects need a durable machine-readable declaration",
                priority=1,
            )
        )

    if "agent-instruction-surface" not in subjects:
        changes.append(
            _change(
                target="agent-instruction-surface",
                action=AdoptionAction.MIGRATE,
                summary="Bootstrap a single agent instruction surface (for example AGENTS.md)",
                kind=ProvenanceKind.INFERRED,
                authority_requirement=AuthorityRequirement.BOUNDED_POLICY,
                status=AdoptionChangeStatus.PROPOSED,
                rationale="Agent execution needs a legible instruction entrypoint",
                priority=2,
            )
        )

    if "test-entrypoint" not in subjects:
        changes.append(
            _change(
                target="test-harness",
                action=AdoptionAction.HARDEN,
                summary="Add deterministic test entrypoints before increasing autonomy",
                kind=ProvenanceKind.INFERRED,
                authority_requirement=AuthorityRequirement.BOUNDED_POLICY,
                status=AdoptionChangeStatus.PROPOSED,
                rationale=(
                    "Testability is a prerequisite for safe agent execution, but adding "
                    "entrypoints writes new repository files and is not self-authorizing"
                ),
                priority=3,
            )
        )

    return changes


def _foundry_retention_changes(intake: ProjectIntake) -> list[AdoptionChangeItem]:
    changes: list[AdoptionChangeItem] = []
    declaration_observations = [
        observation
        for observation in intake.observations
        if observation.subject == "foundry-declaration"
    ]
    if declaration_observations:
        refs = sorted(
            {
                observation.provenance.source_ref
                for observation in declaration_observations
                if observation.provenance.source_ref
            }
        )
        if refs:
            changes.append(
                _change(
                    target="foundry-project-declaration",
                    action=AdoptionAction.KEEP,
                    summary="Retain authoritative owner-declared project characteristics",
                    kind=ProvenanceKind.DECLARED,
                    authority_requirement=AuthorityRequirement.NONE,
                    status=AdoptionChangeStatus.AUTO_APPLICABLE,
                    source_ref=_primary_ref(refs),
                    evidence_refs=refs,
                    rationale="Existing declaration is authoritative and compatible",
                    priority=1,
                )
            )
        return changes

    artifact_observations = [
        observation
        for observation in intake.observations
        if observation.subject == "foundry-artifact"
    ]
    if not artifact_observations:
        return changes

    refs = sorted(
        {
            observation.provenance.source_ref
            for observation in artifact_observations
            if observation.provenance.source_ref
        }
    )
    if not refs:
        return changes

    changes.append(
        _change(
            target="foundry-artifact-surfaces",
            action=AdoptionAction.KEEP,
            summary="Retain observed Foundry artifact surfaces",
            kind=ProvenanceKind.OBSERVED,
            authority_requirement=AuthorityRequirement.NONE,
            status=AdoptionChangeStatus.AUTO_APPLICABLE,
            source_ref=_primary_ref(refs),
            evidence_refs=refs,
            rationale="Observed artifacts are retained during retrofit",
            priority=1,
        )
    )
    return changes


def _brownfield_retrofit_changes(intake: ProjectIntake) -> list[AdoptionChangeItem]:
    subjects = _observation_subjects(intake)
    changes: list[AdoptionChangeItem] = []

    changes.extend(_foundry_retention_changes(intake))

    if "package-metadata" in subjects:
        refs = _observation_refs(intake, "package-metadata")
        changes.append(
            _change(
                target="package-metadata",
                action=AdoptionAction.KEEP,
                summary="Retain existing package and build metadata surfaces",
                kind=ProvenanceKind.OBSERVED,
                authority_requirement=AuthorityRequirement.NONE,
                status=AdoptionChangeStatus.AUTO_APPLICABLE,
                source_ref=_primary_ref(refs),
                evidence_refs=refs,
                priority=2,
            )
        )

    if "test-entrypoint" in subjects:
        test_refs = _observation_refs(intake, "test-entrypoint")
        changes.append(
            _change(
                target="test-harness",
                action=AdoptionAction.HARDEN,
                summary="Strengthen deterministic checks using existing test entrypoints",
                kind=ProvenanceKind.OBSERVED,
                authority_requirement=AuthorityRequirement.BOUNDED_POLICY,
                status=AdoptionChangeStatus.PROPOSED,
                source_ref=_primary_ref(test_refs),
                evidence_refs=test_refs,
                rationale=(
                    "Tightening controls does not expand authority, but editing the test "
                    "harness writes repository files and needs bounded write policy"
                ),
                priority=3,
            )
        )

    if "runtime-deploy-hint" in subjects:
        refs = _observation_refs(intake, "runtime-deploy-hint")
        changes.append(
            _change(
                target="runtime-deploy",
                action=AdoptionAction.KEEP,
                summary="Retain existing runtime and deployment surfaces",
                kind=ProvenanceKind.OBSERVED,
                authority_requirement=AuthorityRequirement.NONE,
                status=AdoptionChangeStatus.AUTO_APPLICABLE,
                source_ref=_primary_ref(refs),
                evidence_refs=refs,
                priority=4,
            )
        )

    fragmentation = [
        finding
        for finding in intake.classification_findings
        if finding.dimension == "agent-rule-fragmentation"
    ]
    for finding in fragmentation:
        changes.append(
            _change(
                target="agent-instruction-surfaces",
                action=AdoptionAction.CONSOLIDATE,
                summary="Multiple instruction surfaces mention overlapping subjects without reconciliation",
                kind=finding.provenance.kind,
                authority_requirement=AuthorityRequirement.EXPLICIT_AUTHORITY,
                status=AdoptionChangeStatus.PROPOSED,
                source_ref=_specific_ref(finding.provenance.source_ref, finding.evidence_refs),
                evidence_refs=finding.evidence_refs,
                confidence=finding.provenance.confidence,
                rationale="Consolidate deliberately; observed mentions are not normative",
                priority=5,
            )
        )

    unreconciled = [
        finding
        for finding in intake.readiness_findings
        if finding.dimension == "unreconciled-subject-mentions"
    ]
    for finding in unreconciled:
        changes.append(
            _change(
                target="instruction-surface-mentions",
                action=AdoptionAction.CONSOLIDATE,
                summary=finding.message,
                kind=finding.provenance.kind,
                authority_requirement=AuthorityRequirement.EXPLICIT_AUTHORITY,
                status=AdoptionChangeStatus.PROPOSED,
                source_ref=finding.provenance.source_ref,
                confidence=finding.provenance.confidence,
                rationale="Adjudicate unreconciled mentions with owner authority; do not auto-prescribe",
                priority=6,
            )
        )

    for finding in intake.readiness_findings:
        if not finding.blocker:
            continue
        changes.append(
            _change(
                target=f"readiness:{finding.dimension}",
                action=AdoptionAction.BLOCK,
                summary=finding.message,
                kind=finding.provenance.kind,
                authority_requirement=AuthorityRequirement.EXPLICIT_AUTHORITY,
                status=AdoptionChangeStatus.BLOCKED,
                source_ref=finding.provenance.source_ref,
                confidence=finding.provenance.confidence,
                rationale="Blocker prevents requested autonomy until resolved",
                priority=0,
            )
        )

    return changes


def _authority_proposal_changes(
    manifest: ProjectManifest,
    intake: ProjectIntake,
) -> list[AdoptionChangeItem]:
    """Propose autonomy increases only as explicit, non-auto-applicable changes."""
    changes: list[AdoptionChangeItem] = []
    current_autonomy = manifest.execution.autonomy
    if current_autonomy is None:
        return changes

    test_refs = _observation_refs(intake, "test-entrypoint")
    ci_refs = _observation_refs(intake, "ci-entrypoint")
    has_tests = any(observation.subject == "test-entrypoint" for observation in intake.observations)
    has_ci = any(observation.subject == "ci-entrypoint" for observation in intake.observations)
    if not (has_tests and has_ci):
        return changes

    if current_autonomy != Autonomy.SUGGEST:
        return changes

    changes.append(
        _change(
            target="execution.autonomy",
            action=AdoptionAction.DEFER,
            summary=(
                "Defer autonomy increase to bounded-external-write until explicit owner approval"
            ),
            kind=ProvenanceKind.INFERRED,
            authority_requirement=AuthorityRequirement.EXPLICIT_AUTHORITY,
            status=AdoptionChangeStatus.PROPOSED,
            evidence_refs=[*test_refs, *ci_refs],
            confidence=0.6,
            rationale="Inference must not silently expand autonomy scope",
            priority=8,
        )
    )
    return changes


def _unknown_intake_mode_change() -> AdoptionChangeItem:
    return _change(
        target="intake-mode",
        action=AdoptionAction.BLOCK,
        summary="intake_mode could not be determined from available evidence",
        kind=ProvenanceKind.INFERRED,
        authority_requirement=AuthorityRequirement.EXPLICIT_AUTHORITY,
        status=AdoptionChangeStatus.BLOCKED,
        confidence=0.0,
        rationale="Adoption planning requires an evidenced intake mode",
        priority=0,
    )


def build_change_set(intake: ProjectIntake, manifest: ProjectManifest) -> AdoptionChangeSet:
    intake_mode = manifest.project.intake_mode

    if intake_mode == IntakeMode.GREENFIELD:
        changes = _bootstrap_changes(intake)
    else:
        changes = _brownfield_retrofit_changes(intake)
        if intake_mode is None:
            changes.append(_unknown_intake_mode_change())

    changes.extend(_authority_proposal_changes(manifest, intake))

    changes.sort(
        key=lambda item: (
            item.priority if item.priority is not None else 99,
            item.target,
            item.action.value,
        )
    )

    return AdoptionChangeSet(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        project_name=manifest.project.name,
        intake_mode=intake_mode,
        changes=changes,
    )


def proposed_autonomy_for_change(change: AdoptionChangeItem) -> Autonomy | None:
    """Autonomy level an autonomy-bearing change would move the project to."""
    if authority_axis_for_target(change.target) is not AuthorityAxis.AUTONOMY:
        return None
    return Autonomy.BOUNDED_EXTERNAL_WRITE


def proposed_external_effect_for_change(change: AdoptionChangeItem) -> ExternalEffectClass | None:
    """External-effect class an effect-bearing change would move the project to."""
    if authority_axis_for_target(change.target) is not AuthorityAxis.EXTERNAL_EFFECT:
        return None
    return ExternalEffectClass.REPOSITORY_WRITE
