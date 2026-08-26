"""Decision explainability — structured audit evidence, not narration.

The questions this module has to answer from artifacts alone:

* which facts and policies caused a role, skill, or integration to be selected or
  excluded;
* what provenance and confidence stand behind each material inferred fact;
* whether inferred facts only *tightened* controls, or whether inference was allowed
  to grant authority a declared fact never granted;
* which of the three lifecycles a given state belongs to.

None of these is a request for the model to explain itself. Each is a structural
property of the compiled artifacts.
"""

from __future__ import annotations

from agent_foundry.models.common import (
    Autonomy,
    ExternalEffectClass,
    Provenance,
    ProvenanceKind,
    ValidationOutcome,
)
from agent_foundry.models.execution import ExecutionBundle
from agent_foundry.models.interaction import ExecutionReceipt
from agent_foundry.models.project import ClassificationFinding, ProjectManifest
from agent_foundry.models.verification import (
    AuthorityTightening,
    DecisionTrace,
    DecisionTraceEntry,
    LifecycleSeparation,
    ValidationFinding,
    ValidationReport,
)
from agent_foundry.verify import claims
from agent_foundry.verify.independent import EXTERNAL_EFFECT_ASCENDING, vocabulary_violations

_AUTONOMY_ASCENDING: tuple[Autonomy, ...] = (
    Autonomy.SUGGEST,
    Autonomy.PREPARE,
    Autonomy.ISOLATED_EXECUTE,
    Autonomy.BOUNDED_EXTERNAL_WRITE,
    Autonomy.APPROVED_APPLY,
    Autonomy.CONTINUOUS_OPERATION,
)

UNKNOWN_BASELINE_RANK = -1
"""Rank of an undeclared baseline.

A manifest field left unknown is the ordinary case, not an exceptional one. Ranking
unknown below every declared level means an inferred value can never look
non-widening merely because nothing was declared to compare it against.
"""

# Manifest axes that define the authority envelope, and the classification dimension
# that feeds each. Dimension labels match the intake documentation's table.
AUTHORITY_AXES: tuple[tuple[str, str], ...] = (
    ("impact.external_effect", "External effect"),
    ("execution.autonomy", "Autonomy"),
)

_AXIS_ORDERS: dict[str, tuple[str, ...]] = {
    "impact.external_effect": tuple(item.value for item in EXTERNAL_EFFECT_ASCENDING),
    "execution.autonomy": tuple(item.value for item in _AUTONOMY_ASCENDING),
}

# Provenance kinds that count as a declared or observed baseline. INFERRED is
# deliberately excluded: it is the thing being tested, not part of the baseline.
_BASELINE_KINDS: frozenset[ProvenanceKind] = frozenset(
    {ProvenanceKind.DECLARED, ProvenanceKind.OBSERVED, ProvenanceKind.NORMATIVE}
)


def _axis_rank(axis: str, value: str | None) -> int:
    if value is None:
        return UNKNOWN_BASELINE_RANK
    order = _AXIS_ORDERS[axis]
    return order.index(value) if value in order else UNKNOWN_BASELINE_RANK


def _manifest_axis_value(manifest: ProjectManifest, axis: str) -> str | None:
    """The manifest's value on an authority axis, as a plain string.

    Read through `getattr(..., "value", ...)` rather than `.value` directly: a
    manifest built past its validators carries a raw string where the field type
    promises an enum, and dereferencing it raises. Callers run the vocabulary scan
    first, which rejects such a manifest outright; this keeps the accessor total so a
    caller that forgets crashes nothing.
    """
    if axis == "impact.external_effect":
        effect: ExternalEffectClass | str | None = manifest.impact.external_effect
        return None if effect is None else str(getattr(effect, "value", effect))
    autonomy: Autonomy | str | None = manifest.execution.autonomy
    return None if autonomy is None else str(getattr(autonomy, "value", autonomy))


def assess_inferred_fact_tightening(
    manifest: ProjectManifest,
    classification_findings: list[ClassificationFinding],
) -> list[AuthorityTightening]:
    """Compare the authority a manifest claims with what declared facts alone support.

    For each authority axis, the baseline is the highest level any declared, observed,
    or normative classification finding supports. The manifest value is what the
    synthesized profile actually carries. If the manifest sits above the baseline, an
    inference widened the envelope — which inference is never allowed to do.
    """
    results: list[AuthorityTightening] = []
    for axis, dimension in AUTHORITY_AXES:
        order = _AXIS_ORDERS[axis]
        baseline_values = [
            finding.value
            for finding in classification_findings
            if finding.dimension == dimension
            and finding.provenance.kind in _BASELINE_KINDS
            and finding.value in order
        ]
        baseline = (
            max(baseline_values, key=lambda value: order.index(value))
            if baseline_values
            else None
        )
        actual = _manifest_axis_value(manifest, axis)
        widened = _axis_rank(axis, actual) > _axis_rank(axis, baseline)
        if baseline is None and actual is not None:
            rationale = (
                f"no declared or observed finding supports a level on {axis}; an "
                f"unknown baseline ranks below every declared level, so {actual} is "
                "treated as widening"
            )
        elif widened:
            rationale = (
                f"{axis} carries {actual}, above the {baseline} that declared and "
                "observed facts support"
            )
        else:
            rationale = (
                f"{axis} carries {actual}, at or below the {baseline} that declared "
                "and observed facts support"
            )
        results.append(
            AuthorityTightening(
                axis=axis,
                declared_only=baseline,
                with_inferred=actual,
                widened=widened,
                rationale=rationale,
            )
        )
    return results


def build_decision_trace(
    bundle: ExecutionBundle,
    *,
    manifest: ProjectManifest | None = None,
    classification_findings: list[ClassificationFinding] | None = None,
    receipt: ExecutionReceipt | None = None,
) -> DecisionTrace:
    """Project a compiled bundle into a traceable audit record."""
    entries = [
        DecisionTraceEntry(
            component_kind=record.component_kind,
            component_id=record.component_id,
            selected=record.selected,
            causing_facts=[record.project_fact] if record.project_fact else [],
            causing_policies=[record.policy_id] if record.policy_id else [],
        )
        for record in sorted(
            bundle.provenance,
            key=lambda item: (item.component_kind, item.component_id, item.selected),
        )
    ]

    tightening: list[AuthorityTightening] = []
    if manifest is not None:
        tightening = assess_inferred_fact_tightening(manifest, classification_findings or [])

    separation = LifecycleSeparation()
    if receipt is not None:
        separation = LifecycleSeparation(
            work_lifecycle_state=receipt.work_lifecycle_state,
            execution_state=receipt.execution_state,
            attained_evidence_states=list(receipt.attained_evidence_states),
            not_required_evidence_states=list(receipt.not_required_evidence_states),
        )

    provenance: list[Provenance] = []
    if manifest is not None:
        provenance = [observation.provenance for observation in manifest.observations]
    for finding in classification_findings or []:
        provenance.append(finding.provenance)

    return DecisionTrace(
        work_item_id=bundle.work_item_id,
        run_id=bundle.run_id,
        role_id=bundle.role_id,
        entries=entries,
        authority_tightening=tightening,
        lifecycle_separation=separation,
        classification_provenance=provenance,
    )


# Component kinds whose selection changes who may act or what may be touched. These
# are the decisions that must name a cause; a context reference or a stop condition
# is carried, not chosen.
MATERIAL_COMPONENT_KINDS: frozenset[str] = frozenset(
    {"role", "skill", "integration", "capability", "workflow", "permission-profile"}
)


def validate_decision_explainability(
    bundle: ExecutionBundle,
    *,
    manifest: ProjectManifest | None = None,
    classification_findings: list[ClassificationFinding] | None = None,
    receipt: ExecutionReceipt | None = None,
) -> ValidationReport:
    """Check that the compiled decisions are attributable and did not widen authority."""
    validator_id = claims.DECISION_EXPLAINABILITY
    subject_id = f"{bundle.work_item_id}/{bundle.run_id}"

    # Vocabulary first, as everywhere else in verify/: a manifest or bundle carrying a
    # value from no known vocabulary cannot support any statement about why a
    # decision was made, and ranking or dereferencing it below would raise.
    malformed: list[ValidationFinding] = []
    for label, model in (
        ("bundle", bundle),
        ("manifest", manifest),
        ("receipt", receipt),
        *(
            (f"classification[{index}]", item)
            for index, item in enumerate(classification_findings or [])
        ),
    ):
        if model is None:
            continue
        malformed.extend(
            ValidationFinding(
                validator_id=validator_id,
                outcome=ValidationOutcome.BLOCKED,
                subject=subject_id,
                message=f"{label}.{violation}",
            )
            for violation in vocabulary_violations(model)
        )
    if malformed:
        return ValidationReport(
            subject_kind="execution-bundle", subject_id=subject_id, findings=malformed
        )

    findings: list[ValidationFinding] = []
    trace = build_decision_trace(
        bundle,
        manifest=manifest,
        classification_findings=classification_findings,
        receipt=receipt,
    )
    subject = f"{bundle.work_item_id}/{bundle.run_id}"

    material = [
        entry for entry in trace.entries if entry.component_kind in MATERIAL_COMPONENT_KINDS
    ]
    if not material:
        findings.append(
            ValidationFinding(
                validator_id=validator_id,
                outcome=ValidationOutcome.MISSING,
                subject=subject,
                message=(
                    "no role, skill, integration, capability, workflow or permission "
                    "profile decision is recorded; why this bundle has the shape it "
                    "has is untraceable"
                ),
            )
        )
    for entry in material:
        if not entry.causing_facts and not entry.causing_policies:
            findings.append(
                ValidationFinding(
                    validator_id=validator_id,
                    outcome=ValidationOutcome.MISSING,
                    subject=f"{entry.component_kind}:{entry.component_id}",
                    message=(
                        f"{'selection' if entry.selected else 'exclusion'} names "
                        "neither a causing fact nor a causing policy"
                    ),
                )
            )

    if manifest is None:
        findings.append(
            ValidationFinding(
                validator_id=validator_id,
                outcome=ValidationOutcome.MISSING,
                subject=subject,
                message=(
                    "no project manifest supplied; whether inferred facts tightened or "
                    "widened authority cannot be established"
                ),
            )
        )
    else:
        for tightening in trace.authority_tightening:
            if tightening.widened:
                findings.append(
                    ValidationFinding(
                        validator_id=validator_id,
                        outcome=ValidationOutcome.HUMAN_REQUIRED,
                        subject=tightening.axis,
                        message=(
                            "inferred facts raised the authority envelope: "
                            f"{tightening.rationale}"
                        ),
                    )
                )
        for observation in manifest.observations:
            if (
                observation.provenance.kind == ProvenanceKind.INFERRED
                and observation.provenance.confidence is None
            ):
                findings.append(
                    ValidationFinding(
                        validator_id=validator_id,
                        outcome=ValidationOutcome.MISSING,
                        subject=f"observation:{observation.subject}",
                        message="inferred observation carries no confidence",
                    )
                )

    for finding in classification_findings or []:
        if finding.provenance.kind != ProvenanceKind.INFERRED:
            continue
        if finding.provenance.confidence is None:
            findings.append(
                ValidationFinding(
                    validator_id=validator_id,
                    outcome=ValidationOutcome.MISSING,
                    subject=f"classification:{finding.dimension}",
                    message="inferred classification finding carries no confidence",
                )
            )
        if not finding.provenance.source_ref and not finding.evidence_refs:
            findings.append(
                ValidationFinding(
                    validator_id=validator_id,
                    outcome=ValidationOutcome.MISSING,
                    subject=f"classification:{finding.dimension}",
                    message="inferred classification finding cites no source or evidence",
                )
            )

    separation = trace.lifecycle_separation
    if receipt is None:
        findings.append(
            ValidationFinding(
                validator_id=validator_id,
                outcome=ValidationOutcome.MISSING,
                subject=subject,
                message=(
                    "no receipt supplied; work lifecycle, execution state and evidence "
                    "state are not traceable from this bundle alone"
                ),
            )
        )
    elif separation.work_lifecycle_state is None or separation.execution_state is None:
        findings.append(
            ValidationFinding(
                validator_id=validator_id,
                outcome=ValidationOutcome.MISSING,
                subject=subject,
                message="lifecycle separation is not fully recorded in the trace",
            )
        )

    if not findings:
        findings.append(
            ValidationFinding(
                validator_id=validator_id,
                outcome=ValidationOutcome.PASS,
                subject=subject,
                message=(
                    f"{len(material)} material decision(s) name a cause, inferred facts "
                    "did not widen authority, and the three lifecycles are traceable"
                ),
            )
        )

    return ValidationReport(
        subject_kind="execution-bundle",
        subject_id=subject,
        findings=findings,
    )
