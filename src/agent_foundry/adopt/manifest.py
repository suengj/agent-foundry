"""Synthesize ProjectManifest from ProjectIntake classification evidence."""

from __future__ import annotations

from enum import Enum
from typing import TypeVar

from agent_foundry.inspect.classification import (
    DECLARED_LIST_SEPARATOR,
    reason_is_absence_enumeration,
    traversal_supports_absence_enumeration,
)
from agent_foundry.models.base import FOUNDRY_SCHEMA_VERSION
from agent_foundry.models.common import (
    AccessSensitivity,
    Ambiguity,
    AssuranceMode,
    Autonomy,
    Concurrency,
    ConsequenceClass,
    ExternalEffectClass,
    IntakeMode,
    PrimaryArtifactState,
    PrimaryWorkMode,
    Provenance,
    ProvenanceKind,
    Reversibility,
    Statefulness,
    TemporalMode,
)
from agent_foundry.models.project import (
    ClassificationFinding,
    ProjectAccess,
    ProjectAssurance,
    ProjectAuthority,
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
    with_values = [finding for finding in findings if finding.value is not None]
    pool = with_values if with_values else findings
    return max(
        pool,
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


def _drop_absence_findings_over_an_incomplete_walk(
    grouped: dict[str, list[ClassificationFinding]],
    intake: ProjectIntake,
    synthesis_readiness: list[ReadinessFinding],
) -> dict[str, list[ClassificationFinding]]:
    """Withhold every finding chosen from silence when the walk left a hole.

    A finding whose reason enumerates signals that were checked and not found
    (``reason_is_absence_enumeration``) states something about the ground the
    walk covered, and nothing about the ground it did not. Over a walk that
    stopped at a depth or entry limit, could not observe a path, refused a
    containment escape, or left a file's bytes unread, the enumerated signals
    may sit precisely in the region never examined -- so
    ``intake_mode = greenfield`` there is not evidence of a greenfield project,
    it is evidence of a short walk. A running service with CI, a container
    manifest and thirty source files must not be adopted as greenfield because
    the traversal stopped at its third entry.

    ``profile.synth`` already gates these for the descriptive profile. This
    module is the other consumer, and the more consequential one: a manifest
    field is what downstream compilation trusts, so an ungated absence here does
    not merely misdescribe the project, it prescribes for one that does not
    exist. Both consumers now ask
    ``traversal_supports_absence_enumeration`` -- one definition, owned beside
    the prefixes, rather than two that can drift.

    The dropped field is left genuinely unset. It is not replaced with the other
    member of its vocabulary, nor with a lower-confidence guess: substituting a
    different value chosen by the same silence would be the same defect wearing
    a different value. Unset is also the *tighter* outcome for the one dimension
    this currently reaches -- ``build_change_set`` routes ``intake_mode=None``
    to the brownfield-retrofit path plus an explicit ``BLOCK`` change
    (``_unknown_intake_mode_change``), never to greenfield bootstrapping -- so
    withholding evidence here can only narrow what adoption proposes, never
    widen it. A ``traversal-incomplete`` readiness finding records the drop, so
    the manifest does not merely look undeclared.

    Findings that are not absence-derived are untouched: a truncated walk does
    not un-see what it did see.
    """
    unread_file_count = sum(
        1 for obs in intake.observations if obs.subject == "file-read-skipped"
    )
    if traversal_supports_absence_enumeration(
        intake.traversal_stats, unread_file_count=unread_file_count
    ):
        return grouped

    filtered: dict[str, list[ClassificationFinding]] = {}
    for dimension, findings in grouped.items():
        kept = [f for f in findings if not reason_is_absence_enumeration(f.reason)]
        dropped = [f for f in findings if reason_is_absence_enumeration(f.reason)]
        for finding in dropped:
            if finding.value is None:
                continue
            _record_withheld_absence(finding, dimension, synthesis_readiness)
        filtered[dimension] = kept
    return filtered


def _record_withheld_absence(
    finding: ClassificationFinding,
    dimension: str,
    synthesis_readiness: list[ReadinessFinding],
) -> None:
    """Report a value withheld because the walk that produced it left a hole.

    The withholding has to be visible. A field that is merely absent reads as
    "nothing was declared and nothing inferred"; this one is absent because
    something *was* inferred and was not trustworthy over the ground the walk
    actually covered, which is a different fact and the one an operator needs in
    order to widen the traversal and look again.
    """
    source_ref = finding.provenance.source_ref or (
        finding.evidence_refs[0] if finding.evidence_refs else "."
    )
    synthesis_readiness.append(
        ReadinessFinding(
            dimension="traversal-incomplete",
            severity=ConsequenceClass.HIGH,
            message=(
                f"Inferred {dimension} value {finding.value!r} was withheld: it was "
                "chosen because a list of signals was checked and none found, and the "
                "traversal did not cover the whole tree, so those signals may lie in "
                "the region the walk never examined"
            ),
            blocker=False,
            provenance=Provenance(
                kind=ProvenanceKind.INFERRED,
                confidence=finding.provenance.confidence,
                source_ref=source_ref,
            ),
        )
    )


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
    synthesis_readiness: list[ReadinessFinding],
) -> E | None:
    finding = _best_finding(grouped.get(dimension, []))
    if finding is None or finding.value is None:
        return None
    if not _eligible_for_manifest(finding):
        return None
    parsed = _parse_enum(finding.value, enum_type)
    if parsed is None and finding.provenance.kind == ProvenanceKind.DECLARED:
        _record_invalid_declaration(finding, dimension, finding.value, synthesis_readiness)
    return parsed


def _record_invalid_declaration(
    finding: ClassificationFinding,
    dimension: str,
    value: str,
    synthesis_readiness: list[ReadinessFinding],
) -> None:
    """Report a declared value that is not a member of its vocabulary.

    The field stays unset rather than guessing: an owner who wrote a value Foundry
    does not recognise has said something, and dropping it silently would leave the
    manifest looking merely undeclared.
    """
    source_ref = finding.provenance.source_ref or (
        finding.evidence_refs[0] if finding.evidence_refs else "."
    )
    synthesis_readiness.append(
        ReadinessFinding(
            dimension="declared-value-invalid",
            severity=ConsequenceClass.HIGH,
            message=(
                f"Declared {dimension} value {value!r} is not valid "
                f"(source: {source_ref})"
            ),
            blocker=False,
            provenance=Provenance(
                kind=ProvenanceKind.DECLARED,
                confidence=finding.provenance.confidence,
                source_ref=source_ref,
            ),
        )
    )


def _manifest_list(
    grouped: dict[str, list[ClassificationFinding]],
    dimension: str,
    enum_type: type[E],
    synthesis_readiness: list[ReadinessFinding],
) -> list[E]:
    """Promote a declared list dimension, reporting any member that is not valid.

    An unrecognised member is not silently dropped and does not poison the members
    beside it: the valid ones are kept and the invalid one raises a
    `declared-value-invalid` readiness finding, the same treatment a scalar gets.
    """
    finding = _best_finding(grouped.get(dimension, []))
    if finding is None or finding.value is None:
        return []
    if not _eligible_for_manifest(finding):
        return []
    if finding.value == "":
        return []
    values: list[E] = []
    for raw in finding.value.split(DECLARED_LIST_SEPARATOR):
        parsed = _parse_enum(raw, enum_type)
        if parsed is None:
            if finding.provenance.kind == ProvenanceKind.DECLARED:
                _record_invalid_declaration(finding, dimension, raw, synthesis_readiness)
            continue
        values.append(parsed)
    return values


def _manifest_string_list(
    grouped: dict[str, list[ClassificationFinding]],
    dimension: str,
) -> list[str]:
    """Promote a declared list of free-form strings.

    Repository paths are not a vocabulary, so there is no member to reject — only a
    declaration to honour or an absence to report. Containment and traversal are
    checked where the paths are used to grant authority, not here: this layer records
    what the owner wrote.
    """
    finding = _best_finding(grouped.get(dimension, []))
    if finding is None or finding.value is None:
        return []
    if not _eligible_for_manifest(finding):
        return []
    if finding.value == "":
        return []
    return [item for item in finding.value.split(DECLARED_LIST_SEPARATOR) if item]


def _manifest_name(grouped: dict[str, list[ClassificationFinding]]) -> str | None:
    """Promote the declared project name.

    The name is a free-form identifier, not a vocabulary member, so there is no
    value to reject — only a declaration to honour or an absence to report.
    """
    finding = _best_finding(grouped.get("project.name", []))
    if finding is None or finding.value is None:
        return None
    if not _eligible_for_manifest(finding):
        return None
    return finding.value


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
    synthesis_readiness: list[ReadinessFinding] = []
    grouped = _drop_absence_findings_over_an_incomplete_walk(
        _findings_by_dimension(intake), intake, synthesis_readiness
    )

    intake_mode = _manifest_value(grouped, "intake_mode", IntakeMode, synthesis_readiness)
    primary_work_mode = _manifest_value(
        grouped, "primary_work_mode", PrimaryWorkMode, synthesis_readiness
    )
    primary_artifact = _manifest_value(
        grouped, "primary_artifact", PrimaryArtifactState, synthesis_readiness
    )

    secondary_work_modes = _manifest_list(
        grouped, "secondary_work_modes", PrimaryWorkMode, synthesis_readiness
    )
    work_modes = (
        WorkModes(primary=primary_work_mode, secondary=secondary_work_modes)
        if primary_work_mode is not None or secondary_work_modes
        else None
    )

    state = ProjectState(
        persistence=_manifest_value(grouped, "state.persistence", Statefulness, synthesis_readiness),
        temporal_mode=_manifest_value(
            grouped, "state.temporal_mode", TemporalMode, synthesis_readiness
        ),
    )
    impact = ProjectImpact(
        external_effect=_manifest_value(
            grouped, "impact.external_effect", ExternalEffectClass, synthesis_readiness
        ),
        reversibility=_manifest_value(
            grouped, "impact.reversibility", Reversibility, synthesis_readiness
        ),
        consequence=_manifest_value(
            grouped, "impact.consequence", ConsequenceClass, synthesis_readiness
        ),
    )
    execution = ProjectExecution(
        autonomy=_manifest_value(grouped, "execution.autonomy", Autonomy, synthesis_readiness),
        ambiguity=_manifest_value(grouped, "execution.ambiguity", Ambiguity, synthesis_readiness),
        concurrency=_manifest_value(
            grouped, "execution.concurrency", Concurrency, synthesis_readiness
        ),
    )
    access = ProjectAccess(
        sensitivity=_manifest_value(
            grouped, "access.sensitivity", AccessSensitivity, synthesis_readiness
        ),
    )
    assurance = ProjectAssurance(
        required=_manifest_list(
            grouped, "assurance.required", AssuranceMode, synthesis_readiness
        )
    )
    authority = ProjectAuthority(
        write_scope=_manifest_string_list(grouped, "authority.write_scope")
    )

    readiness_findings = sorted(
        [*intake.readiness_findings, *synthesis_readiness],
        key=lambda finding: (finding.dimension, finding.message, finding.severity.value),
    )

    return ProjectManifest(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        project=ProjectInfo(
            name=_manifest_name(grouped),
            intake_mode=intake_mode,
            work_modes=work_modes,
            primary_artifact=primary_artifact,
        ),
        state=state,
        impact=impact,
        execution=execution,
        assurance=assurance,
        authority=authority,
        access=access,
        observations=_synthesis_observations(intake),
        readiness_findings=readiness_findings,
    )
