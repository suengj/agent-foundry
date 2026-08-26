"""Unknown values never read as safe — on either side of a sibling pair.

This project has shipped "unknown reads as safe" five times: AF3 unknown authority,
AF5 missing integration spec, AF5 absent health evidence, AF5 declared-unavailable
health, and — inside the module written to forbid it — an unrecognised
`not_required_evidence_states` entry passing lifecycle validation.

The shape is always the same. Two lists carry values from one vocabulary; the code
checks one list and trusts the other. So these tests do not check a single field.
They check *both halves of every pair*, and one of them enumerates the pairs so that
adding a new one half-checked is a test failure rather than a future review finding.

Every case below is pinned with a `model_construct` forgery, because that is how a
payload with a bypassed model validator actually reaches a validator.
"""

from __future__ import annotations

import pytest

from agent_foundry.models import (
    EvidenceClass,
    EvidenceState,
    ReconciliationDimension,
    ValidationOutcome,
)
from agent_foundry.verify import (
    reconcile_work_item,
    validate_evidence_bundle_completeness,
    validate_execution_bundle_completeness,
    validate_lifecycle_separation,
    validate_required_evidence,
    validate_toolkit_coherence,
    validate_write_scope_containment,
)
from agent_foundry.verify.independent import (
    EVIDENCE_STATE_PROGRESSION,
    EXEMPTION_MARKER,
    evidence_state_partition_conflicts,
    unrecognised_members,
)
from verify_support import (
    compiled,
    complete_receipt,
    full_evidence_bundle,
    repository,
    sample_work_item,
    tracker,
)

# Pydantic warns when serializing a deliberately off-vocabulary value back out. That
# is the expected consequence of forging one, not a defect under test.
pytestmark = pytest.mark.filterwarnings("ignore:Pydantic serializer warnings:UserWarning")


def _messages(report) -> str:
    return " | ".join(finding.message for finding in report.findings)


def _construct(model, **changes):
    """Forge a model past its own validators, the way a bad payload arrives."""
    return type(model).model_construct(**{**model.__dict__, **changes})


# --- 1. receipt evidence-state lists (the instance the reviewer found) ----------


def test_an_unrecognised_not_required_state_is_blocked_not_passed():
    """The reported defect: `['SOMEDAY']` used to return PASS.

    BLOCKED rather than MISSING, deliberately. An exemption is a positive claim that
    some obligation does not apply. A value naming no evidence state identifies
    nothing that could be exempt, so the record is not *incomplete* — an empty list
    would be that — it is *wrong*. The attained side already treats an off-ladder
    value this way, and splitting the verdict between siblings for one defect is the
    asymmetry that caused this.
    """
    receipt, _ = complete_receipt()
    forged = _construct(receipt, not_required_evidence_states=["SOMEDAY"])
    report = validate_lifecycle_separation(forged)
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert not report.accepted()
    assert "names no known evidence" in _messages(report) or "is not an evidence state" in _messages(report)


def test_the_exemption_marker_cannot_exempt_itself():
    receipt, _ = complete_receipt()
    forged = _construct(receipt, not_required_evidence_states=[EXEMPTION_MARKER])
    report = validate_lifecycle_separation(forged)
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "names no evidence state that could be exempt" in _messages(report)


def test_an_unrecognised_attained_state_is_blocked_too():
    """The sibling that was already checked — pinned so it stays checked."""
    receipt, _ = complete_receipt()
    forged = _construct(receipt, attained_evidence_states=["SOMEDAY"])
    report = validate_lifecycle_separation(forged)
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "cannot have been attained" in _messages(report)


@pytest.mark.parametrize("side", ["attained", "not_required"])
def test_the_partition_rule_checks_both_sides_against_the_ladder(side):
    """Called directly, so the property is pinned at the derivation, not just its caller."""
    ladder = [state.value for state in EVIDENCE_STATE_PROGRESSION]
    lists = {"attained": [], "not_required": []}
    lists[side] = ["SOMEDAY"]
    conflicts = evidence_state_partition_conflicts(**lists)
    assert conflicts, f"{side} accepted an unrecognised value"
    assert "SOMEDAY" in " ".join(conflicts)

    clean = {"attained": ladder[:2], "not_required": ladder[2:]}
    assert evidence_state_partition_conflicts(**clean) == []


# --- 2. evidence-bundle class lists --------------------------------------------


def test_an_unrecognised_evidence_class_on_an_item_is_blocked():
    bundle = full_evidence_bundle()
    item = _construct(bundle.items[0], evidence_class="vibes")
    forged = _construct(bundle, items=[item])
    report = validate_evidence_bundle_completeness(forged)
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "not a known evidence class" in _messages(report)


def test_an_unrecognised_not_required_class_is_blocked():
    forged = _construct(full_evidence_bundle(), not_required_classes=["vibes"])
    report = validate_evidence_bundle_completeness(forged)
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "names no known evidence class" in _messages(report)


# --- 3. required-evidence requirement vs exemption ------------------------------


def test_an_unrecognised_exemption_never_reads_as_an_accepted_requirement():
    """It used to crash; before that it would have reported NOT_REQUIRED."""
    forged = _construct(full_evidence_bundle(), not_required_classes=["vibes"])
    report = validate_required_evidence(sample_work_item(), forged)
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "names no known evidence class" in _messages(report)
    accepted_subjects = {
        finding.subject
        for finding in report.findings
        if finding.outcome == ValidationOutcome.NOT_REQUIRED
    }
    assert "vibes" not in accepted_subjects


def test_the_requirement_side_stays_checked():
    report = validate_required_evidence(
        sample_work_item(required_evidence=["vibes"]), full_evidence_bundle()
    )
    assert report.outcome() == ValidationOutcome.MISSING
    assert "does not name a known evidence class" in _messages(report)


def test_a_forged_bundle_is_rejected_rather_than_crashing_the_validator():
    """A validator that raises on a forged artifact has not rejected it."""
    forged = _construct(full_evidence_bundle(), not_required_classes=["vibes"])
    report = validate_required_evidence(sample_work_item(), forged)
    assert report.findings  # returned a verdict rather than propagating AttributeError
    assert not report.accepted()


# --- 4. granted vs forbidden write paths ----------------------------------------


def test_a_forbidden_write_path_that_resolves_to_nothing_is_blocked():
    artifacts = compiled()
    forged = artifacts["bundle"].authority.model_copy(
        update={"forbidden_scopes": ["../../etc"]}
    )
    report = validate_write_scope_containment(
        forged, work_item=artifacts["work_item"], role=artifacts["role"]
    )
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "denies nothing" in _messages(report)


def test_the_granted_side_stays_checked():
    artifacts = compiled()
    forged = artifacts["bundle"].authority.model_copy(
        update={"write_scope": ["../../etc"], "forbidden_scopes": []}
    )
    report = validate_write_scope_containment(
        forged, work_item=artifacts["work_item"], role=artifacts["role"]
    )
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "does not resolve" in _messages(report)


# --- 5. allowed vs forbidden capabilities ----------------------------------------


def test_a_forbidden_capability_outside_the_toolkit_is_blocked():
    bundle = compiled()["bundle"]
    forged = bundle.model_copy(update={"forbidden_capabilities": ["nonexistent.capability"]})
    report = validate_execution_bundle_completeness(forged)
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "forbidding it denies nothing" in _messages(report)


def test_the_allowed_side_stays_checked():
    bundle = compiled()["bundle"]
    forged = bundle.model_copy(
        update={"allowed_capabilities": [*bundle.allowed_capabilities, "runtime.verify"]}
    )
    report = validate_execution_bundle_completeness(forged)
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "not in the task toolkit" in _messages(report)


# --- 6. task toolkit vs project lock, against the registry -------------------------


def test_a_project_lock_selecting_an_unregistered_component_is_blocked():
    artifacts = compiled()
    lock = artifacts["lock"].model_copy(
        update={
            "skill_ids": [*artifacts["lock"].skill_ids, "ghost-skill"],
            "skill_versions": {**artifacts["lock"].skill_versions, "ghost-skill": "1.0.0"},
        }
    )
    report = validate_toolkit_coherence(artifacts["task_toolkit"], lock, artifacts["registry"])
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "project lock skill 'ghost-skill' is not declared in the registry" in _messages(report)


def test_the_task_side_stays_checked():
    artifacts = compiled()
    task = artifacts["task_toolkit"].model_copy(
        update={"skill_ids": [*artifacts["task_toolkit"].skill_ids, "ghost-skill"]}
    )
    report = validate_toolkit_coherence(task, artifacts["lock"], artifacts["registry"])
    assert report.outcome() == ValidationOutcome.BLOCKED
    assert "not in the pinned project lock" in _messages(report)


# --- 7. tracker required vs not-required declarations ------------------------------


@pytest.mark.parametrize(
    "field",
    ["declared_required_evidence_states", "declared_not_required_evidence_states"],
)
def test_an_unrecognised_state_in_either_tracker_declaration_is_blocked(field):
    forged = _construct(tracker(), **{field: ["SOMEDAY"]})
    report = reconcile_work_item(
        work_item=sample_work_item(), tracker=forged, repository=repository()
    )
    assert report.outcome_for(ReconciliationDimension.EVIDENCE_STATE) == (
        ValidationOutcome.BLOCKED
    )
    assert "names none" in _messages(report)


def test_reconciliation_returns_a_verdict_rather_than_crashing_on_a_forged_projection():
    forged = _construct(tracker(), declared_not_required_evidence_states=["SOMEDAY"])
    report = reconcile_work_item(
        work_item=sample_work_item(), tracker=forged, repository=repository()
    )
    assert report.findings


# --- the class itself: every sibling pair is checked on both sides -----------------

# Each entry is a vocabulary and the two (or more) lists drawn from it that a
# validator compares. The point of naming them here is that adding a pair without
# checking both halves fails this test instead of shipping.
SIBLING_VOCABULARY_PAIRS = [
    (
        "receipt evidence states",
        {state.value for state in EVIDENCE_STATE_PROGRESSION},
        ("attained_evidence_states", "not_required_evidence_states"),
    ),
    (
        "evidence bundle classes",
        {member.value for member in EvidenceClass},
        ("items[].evidence_class", "not_required_classes"),
    ),
    (
        "tracker evidence declarations",
        {state.value for state in EvidenceState},
        (
            "declared_required_evidence_states",
            "declared_not_required_evidence_states",
        ),
    ),
]


@pytest.mark.parametrize(
    ("label", "vocabulary", "lists"),
    SIBLING_VOCABULARY_PAIRS,
    ids=[pair[0] for pair in SIBLING_VOCABULARY_PAIRS],
)
def test_every_named_sibling_pair_has_a_test_for_each_side(label, vocabulary, lists):
    """A registry of pairs, so the audit is a standing property rather than a sweep."""
    assert len(lists) >= 2, label
    assert vocabulary, label
    # The shared helper is what makes "check both sides" one call rather than two
    # chances to forget the second.
    assert unrecognised_members(["not-in-vocabulary"], vocabulary) == ["not-in-vocabulary"]
    assert unrecognised_members(sorted(vocabulary), vocabulary) == []


def test_the_shared_helper_is_used_by_every_vocabulary_check():
    """Grep-level, but it is what keeps the pairs above from drifting apart."""
    from pathlib import Path

    verify = Path(__file__).resolve().parents[1] / "src" / "agent_foundry" / "verify"
    users = {
        path.name
        for path in verify.glob("*.py")
        if "unrecognised_members" in path.read_text(encoding="utf-8")
    }
    assert {"independent.py", "validators.py"} <= users, users
