"""Decision explainability and inferred-fact tightening.

Every claim here is about structure the artifacts carry, not about a model
explaining itself: which facts caused a selection, what confidence stands behind an
inference, and whether inference was ever allowed to widen authority.
"""

from __future__ import annotations


from agent_foundry.models import (
    Autonomy,
    ClassificationFinding,
    ExternalEffectClass,
    Provenance,
    ProvenanceKind,
    ProjectObservation,
    ValidationOutcome,
)
from agent_foundry.verify import (
    assess_inferred_fact_tightening,
    build_decision_trace,
    validate_decision_explainability,
)
from agent_foundry.verify.explain import MATERIAL_COMPONENT_KINDS
from verify_support import compiled, complete_receipt, sample_manifest


def _messages(report) -> str:
    return " | ".join(finding.message for finding in report.findings)


def _declared(dimension: str, value: str) -> ClassificationFinding:
    return ClassificationFinding(
        dimension=dimension,
        value=value,
        provenance=Provenance(kind=ProvenanceKind.DECLARED, source_ref="intake.yaml"),
    )


def _inferred(dimension: str, value: str, confidence: float = 0.6) -> ClassificationFinding:
    return ClassificationFinding(
        dimension=dimension,
        value=value,
        provenance=Provenance(
            kind=ProvenanceKind.INFERRED, confidence=confidence, source_ref="pyproject.toml"
        ),
    )


# The `ClassificationFinding.dimension` keys the inspector actually emits. These read
# "External effect" and "Autonomy" until AF8: human labels, matching no finding, so the
# declared baseline was always empty and every manifest was reported as widened by
# inference. Nothing exposed it while classification could produce no value on either
# axis — an owner declaration can, so the names have to be the same name.
DECLARED_BASELINE = [
    _declared("impact.external_effect", ExternalEffectClass.REPOSITORY_WRITE.value),
    _declared("execution.autonomy", Autonomy.BOUNDED_EXTERNAL_WRITE.value),
]


# --- which facts and policies caused a selection --------------------------------


def test_the_trace_names_a_cause_for_every_material_decision():
    artifacts = compiled()
    trace = build_decision_trace(artifacts["bundle"], manifest=artifacts["manifest"])
    material = [
        entry for entry in trace.entries if entry.component_kind in MATERIAL_COMPONENT_KINDS
    ]
    assert material
    for entry in material:
        assert entry.causing_facts or entry.causing_policies, entry


def test_the_trace_records_exclusions_as_well_as_selections():
    artifacts = compiled()
    trace = build_decision_trace(artifacts["bundle"], manifest=artifacts["manifest"])
    assert any(entry.selected for entry in trace.entries)
    assert any(not entry.selected for entry in trace.entries)


def test_a_selection_without_a_cause_is_reported_missing():
    artifacts = compiled()
    stripped = [
        record.model_copy(update={"project_fact": None, "policy_id": None})
        for record in artifacts["bundle"].provenance
    ]
    forged = artifacts["bundle"].model_copy(update={"provenance": stripped})
    report = validate_decision_explainability(
        forged,
        manifest=artifacts["manifest"],
        classification_findings=DECLARED_BASELINE,
        receipt=complete_receipt()[0],
    )
    assert report.outcome() == ValidationOutcome.MISSING
    assert "neither a causing fact nor a causing policy" in _messages(report)


# --- inferred facts may tighten, never widen --------------------------------------


def test_inferred_facts_at_or_below_the_declared_baseline_do_not_widen():
    manifest = sample_manifest()
    results = assess_inferred_fact_tightening(
        manifest,
        [
            *DECLARED_BASELINE,
            _inferred("impact.external_effect", ExternalEffectClass.READ_ONLY.value),
        ],
    )
    assert all(not result.widened for result in results), results


def test_an_inference_above_the_declared_baseline_is_flagged_as_widening():
    manifest = sample_manifest(
        impact={
            "external_effect": "runtime-mutation",
            "reversibility": "rollback-required",
            "consequence": "high",
        }
    )
    results = assess_inferred_fact_tightening(manifest, DECLARED_BASELINE)
    effect = next(item for item in results if item.axis == "impact.external_effect")
    assert effect.widened
    assert effect.declared_only == ExternalEffectClass.REPOSITORY_WRITE.value
    assert effect.with_inferred == ExternalEffectClass.RUNTIME_MUTATION.value


def test_an_unknown_baseline_ranks_below_every_declared_level():
    """AF3's rule, restated here: silence is not a licence."""
    manifest = sample_manifest()
    results = assess_inferred_fact_tightening(manifest, [])
    assert all(result.widened for result in results), results
    assert "unknown baseline ranks below every declared level" in results[0].rationale


def test_widening_escalates_to_human_required_rather_than_passing():
    artifacts = compiled()
    manifest = sample_manifest(
        impact={
            "external_effect": "publication",
            "reversibility": "effectively-irreversible",
            "consequence": "critical",
        }
    )
    report = validate_decision_explainability(
        artifacts["bundle"],
        manifest=manifest,
        classification_findings=DECLARED_BASELINE,
        receipt=complete_receipt()[0],
    )
    assert report.outcome() == ValidationOutcome.HUMAN_REQUIRED
    assert "raised the authority envelope" in _messages(report)


# --- provenance and confidence for material inferred facts --------------------------


def test_an_inferred_observation_without_confidence_is_reported():
    artifacts = compiled()
    manifest = sample_manifest(
        observations=[
            ProjectObservation(
                subject="test-harness",
                content="pytest entrypoint inferred from packaging metadata",
                provenance=Provenance(
                    kind=ProvenanceKind.INFERRED, source_ref="pyproject.toml"
                ),
            )
        ]
    )
    report = validate_decision_explainability(
        artifacts["bundle"],
        manifest=manifest,
        classification_findings=DECLARED_BASELINE,
        receipt=complete_receipt()[0],
    )
    assert not report.accepted()
    assert "inferred observation carries no confidence" in _messages(report)


def test_an_inferred_classification_without_a_source_is_reported():
    artifacts = compiled()
    anonymous = ClassificationFinding(
        dimension="execution.autonomy",
        value=Autonomy.PREPARE.value,
        provenance=Provenance(kind=ProvenanceKind.INFERRED, confidence=0.4),
    )
    report = validate_decision_explainability(
        artifacts["bundle"],
        manifest=artifacts["manifest"],
        classification_findings=[*DECLARED_BASELINE, anonymous],
        receipt=complete_receipt()[0],
    )
    assert not report.accepted()
    assert "cites no source or evidence" in _messages(report)


# --- the full picture ---------------------------------------------------------------


def test_a_fully_explainable_compile_is_accepted():
    artifacts = compiled()
    receipt, _ = complete_receipt()
    report = validate_decision_explainability(
        artifacts["bundle"],
        manifest=artifacts["manifest"],
        classification_findings=DECLARED_BASELINE,
        receipt=receipt,
    )
    assert report.accepted(), _messages(report)


def test_missing_inputs_are_reported_rather_than_assumed_fine():
    artifacts = compiled()
    report = validate_decision_explainability(artifacts["bundle"])
    assert report.outcome() == ValidationOutcome.MISSING
    text = _messages(report)
    assert "no project manifest supplied" in text
    assert "no receipt supplied" in text
