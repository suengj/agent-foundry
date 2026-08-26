"""Synthesize ProjectManifest from ProjectIntake classification evidence."""

from __future__ import annotations

from enum import Enum
from typing import TypeVar

from agent_foundry.models.base import FOUNDRY_SCHEMA_VERSION
from agent_foundry.models.common import (
    AccessSensitivity,
    Ambiguity,
    Autonomy,
    Concurrency,
    ConsequenceClass,
    ExternalEffectClass,
    IntakeMode,
    PrimaryArtifactState,
    PrimaryWorkMode,
    ProvenanceKind,
    Reversibility,
    Statefulness,
    TemporalMode,
)
from agent_foundry.models.project import (
    ClassificationFinding,
    ProjectAccess,
    ProjectAssurance,
    ProjectExecution,
    ProjectImpact,
    ProjectInfo,
    ProjectManifest,
    ProjectIntake,
    ProjectObservation,
    ProjectState,
    ReadinessFinding,
    WorkModes,
)

E = TypeVar("E", bound=Enum)

_PROVENANCE_PRECEDENCE: dict[ProvenanceKind, int] = {
    ProvenanceKind.NORMATIVE: 4,
    ProvenanceKind.DECLARED: 3,
    ProvenanceKind.OBSERVED: 2,
    ProvenanceKind.INFERRED: 1,
}

_MANIFEST_ELIGIBLE_KINDS: frozenset[ProvenanceKind] = frozenset(
    {ProvenanceKind.NORMATIVE, ProvenanceKind.DECLARED, ProvenanceKind.INFERRED}
)

_INTAKE_MODE_INFERENCE_MIN_CONFIDENCE = 0.5


def _best_finding(findings: list[ClassificationFinding]) -> ClassificationFinding | None:
    if not findings:
        return None
    return max(
        findings,
        key=lambda finding: (
            _PROVENANCE_PRECEDENCE.get(finding.provenance.kind, 0),
            finding.provenance.confidence or 0.0,
            finding.value or "",
        ),
    )


def _findings_by_dimension(intake: ProjectIntake) -> dict[str, list[ClassificationFinding]]:
    grouped: dict[str, list[ClassificationFinding]] = {}
    for finding in intake.classification_findings:
        grouped.setdefault(finding.dimension, []).append(finding)
    return grouped


def _eligible_for_manifest(finding: ClassificationFinding) -> bool:
    if finding.value is None:
        return False
    if finding.provenance.kind not in _MANIFEST_ELIGIBLE_KINDS:
        return False
    if finding.dimension == "intake_mode" and finding.provenance.kind == ProvenanceKind.INFERRED:
        confidence = finding.provenance.confidence or 0.0
        return confidence >= _INTAKE_MODE_INFERENCE_MIN_CONFIDENCE
    if finding.provenance.kind == ProvenanceKind.INFERRED:
        return finding.dimension == "intake_mode"
    return True


def _parse_enum(value: str, enum_type: type[E]) -> E | None:
    try:
        return enum_type(value)
    except ValueError:
        return None


def _manifest_value(
    grouped: dict[str, list[ClassificationFinding]],
    dimension: str,
    enum_type: type[E],
) -> E | None:
    finding = _best_finding(grouped.get(dimension, []))
    if finding is None or not _eligible_for_manifest(finding):
        return None
    assert finding.value is not None
    return _parse_enum(finding.value, enum_type)


def _synthesis_observations(intake: ProjectIntake) -> list[ProjectObservation]:
    observations: list[ProjectObservation] = []
    for finding in intake.classification_findings:
        if finding.value is None:
            continue
        if finding.provenance.kind == ProvenanceKind.OBSERVED:
            observations.append(
                ProjectObservation(
                    subject=f"classification-candidate:{finding.dimension}",
                    content=(
                        f"observed candidate {finding.value!r} for {finding.dimension} "
                        "(not promoted to manifest field)"
                    ),
                    provenance=finding.provenance,
                )
            )
        elif finding.provenance.kind == ProvenanceKind.INFERRED and finding.dimension != "intake_mode":
            observations.append(
                ProjectObservation(
                    subject=f"classification-candidate:{finding.dimension}",
                    content=(
                        f"inferred candidate {finding.value!r} for {finding.dimension} "
                        "held as evidence only"
                    ),
                    provenance=finding.provenance,
                )
            )
    for convention in intake.conventions:
        observations.append(
            ProjectObservation(
                subject=f"convention-mention:{convention.subject}",
                content=convention.evidence,
                provenance=convention.provenance,
            )
        )
    observations.sort(key=lambda item: (item.subject, item.content, item.provenance.source_ref or ""))
    return observations


def synthesize_manifest(intake: ProjectIntake) -> ProjectManifest:
    grouped = _findings_by_dimension(intake)

    intake_mode = _manifest_value(grouped, "intake_mode", IntakeMode)
    primary_work_mode = _manifest_value(grouped, "primary_work_mode", PrimaryWorkMode)
    primary_artifact = _manifest_value(grouped, "primary_artifact", PrimaryArtifactState)

    work_modes = WorkModes(primary=primary_work_mode) if primary_work_mode is not None else None

    state = ProjectState(
        persistence=_manifest_value(grouped, "state.persistence", Statefulness),
        temporal_mode=None,
    )
    impact = ProjectImpact(
        external_effect=_manifest_value(grouped, "impact.external_effect", ExternalEffectClass),
        reversibility=None,
        consequence=None,
    )
    execution = ProjectExecution(
        autonomy=_manifest_value(grouped, "execution.autonomy", Autonomy),
        ambiguity=None,
        concurrency=None,
    )
    access = ProjectAccess(
        sensitivity=_manifest_value(grouped, "access.sensitivity", AccessSensitivity),
    )

    readiness_findings = sorted(
        list(intake.readiness_findings),
        key=lambda finding: (finding.dimension, finding.message, finding.severity.value),
    )

    return ProjectManifest(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        project=ProjectInfo(
            name=None,
            intake_mode=intake_mode,
            work_modes=work_modes,
            primary_artifact=primary_artifact,
        ),
        state=state,
        impact=impact,
        execution=execution,
        assurance=ProjectAssurance(required=[]),
        access=access,
        observations=_synthesis_observations(intake),
        readiness_findings=readiness_findings,
    )
