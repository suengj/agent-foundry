"""An owner declaration the vocabulary rejects is reported, not silently dropped.

Two M1 invariants meet here:

* *An explicit owner declaration is never silently overridden.* A declaration
  dropped by validation with no trace is the same failure as one overridden by a
  heuristic — the owner's statement disappears either way.
* *UNKNOWN / unobserved / conflicted / resolved are distinguishable.* A profile
  dimension published as RESOLVED at a value ``ProjectManifest`` can never carry
  is not honestly resolved.

Before this contract correction, ``impact: {reversibility: reversible}`` was
republished by ``synthesize_project_profile`` as RESOLVED at ``declared``
provenance, refused (correctly) by ``synthesize_manifest``, and reported by no
readiness finding an inspection could see. Both halves are pinned below, along
with the negative direction: a *valid* declaration must still resolve cleanly and
must raise no finding at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_foundry.adopt import plan_adoption
from agent_foundry.inspect import inspect_project
from agent_foundry.inspect.classification import (
    CLASSIFICATION_DIMENSIONS,
    DECLARED_VOCABULARIES,
    usable_declared_value,
)
from agent_foundry.models import Concurrency, ProfileResolution, ProvenanceKind, Reversibility
from agent_foundry.profile import synthesize_project_profile

INVALID_DECLARATION = """\
project:
  name: p
  intake_mode: brownfield
impact:
  reversibility: reversible
execution:
  concurrency: single
"""

VALID_DECLARATION = """\
project:
  name: p
  intake_mode: brownfield
impact:
  reversibility: versioned
execution:
  concurrency: single-writer
"""


def _project(root: Path, declaration: str) -> Path:
    (root / ".foundry").mkdir(parents=True)
    (root / ".foundry" / "project.yaml").write_text(declaration, encoding="utf-8")
    (root / "README.md").write_text("# p\n", encoding="utf-8")
    return root


def _dimension(profile, name: str):
    return next(dim for dim in profile.dimensions if dim.dimension == name)


def _invalid_findings(findings):
    return [f for f in findings if f.dimension == "declared-value-invalid"]


def test_invalid_declaration_is_reported_on_the_inspection_path(tmp_path: Path) -> None:
    """The owner is told, from `inspect` alone — not only from `plan_adoption`."""
    intake = inspect_project(_project(tmp_path / "proj", INVALID_DECLARATION))
    reported = _invalid_findings(intake.readiness_findings)
    messages = " | ".join(f.message for f in reported)

    assert len(reported) == 2, f"expected one finding per rejected value, got {messages}"
    for dimension, value in (
        ("impact.reversibility", "reversible"),
        ("execution.concurrency", "single"),
    ):
        matching = [f for f in reported if dimension in f.message]
        assert matching, f"no finding names {dimension}: {messages}"
        # The dimension, the rejected token, and the file the owner must edit.
        assert repr(value) in matching[0].message
        assert ".foundry/project.yaml" in matching[0].message
        assert matching[0].provenance.kind is ProvenanceKind.DECLARED
        assert matching[0].provenance.source_ref == ".foundry/project.yaml"


def test_invalid_declaration_is_not_published_as_resolved(tmp_path: Path) -> None:
    """UNKNOWN, not RESOLVED: the profile may not attribute a value the schema rejects."""
    intake = inspect_project(_project(tmp_path / "proj", INVALID_DECLARATION))
    profile = synthesize_project_profile(intake)

    for name in ("impact.reversibility", "execution.concurrency"):
        dimension = _dimension(profile, name)
        assert dimension.resolution is ProfileResolution.UNKNOWN, (
            f"{name} published as {dimension.resolution.value} at "
            f"{[a.value for a in dimension.attributions]}"
        )
        # UNKNOWN carries no attributions by contract; the fact that something
        # *was* declared lives in the readiness finding, not in a fabricated
        # attribution.
        assert dimension.attributions == []


def test_invalid_declaration_is_still_refused_by_the_manifest(tmp_path: Path) -> None:
    """The manifest must not start accepting the value the profile stopped publishing."""
    intake = inspect_project(_project(tmp_path / "proj", INVALID_DECLARATION))
    manifest = plan_adoption(intake).manifest

    assert manifest.impact.reversibility is None
    assert manifest.execution.concurrency is None
    # One typo, one finding: `inspect.readiness` and `adopt.manifest` raise this
    # from the same builder, and the merge drops the exact duplicate.
    reported = _invalid_findings(manifest.readiness_findings)
    assert len(reported) == 2, [f.message for f in reported]


def test_valid_declaration_still_resolves_cleanly(tmp_path: Path) -> None:
    """The negative direction: reporting every declaration as suspect is worse."""
    intake = inspect_project(_project(tmp_path / "proj", VALID_DECLARATION))
    profile = synthesize_project_profile(intake)
    manifest = plan_adoption(intake).manifest

    assert _invalid_findings(intake.readiness_findings) == []
    assert _invalid_findings(manifest.readiness_findings) == []
    assert manifest.impact.reversibility is Reversibility.VERSIONED
    assert manifest.execution.concurrency is Concurrency.SINGLE_WRITER
    for name, value in (
        ("impact.reversibility", "versioned"),
        ("execution.concurrency", "single-writer"),
    ):
        dimension = _dimension(profile, name)
        assert dimension.resolution is ProfileResolution.RESOLVED
        assert [a.value for a in dimension.attributions] == [value]


def test_empty_declared_list_is_not_an_invalid_member() -> None:
    """`secondary_work_modes: []` declares no members; it does not declare a bad one."""
    assert usable_declared_value("secondary_work_modes", "") == ""


def test_free_form_dimensions_have_no_vocabulary_to_reject() -> None:
    """A name and a write scope are not vocabularies; nothing there may be refused."""
    for dimension in ("project.name", "authority.write_scope"):
        assert dimension not in DECLARED_VOCABULARIES
        assert usable_declared_value(dimension, "anything at all") == "anything at all"


@pytest.mark.parametrize("dimension", CLASSIFICATION_DIMENSIONS)
def test_every_declarable_dimension_states_whether_it_has_a_vocabulary(dimension: str) -> None:
    """A new dimension must decide: closed vocabulary, or deliberately free-form.

    Without this, a dimension added to `CLASSIFICATION_DIMENSIONS` and to the
    manifest but not to `DECLARED_VOCABULARIES` would quietly reacquire the
    original defect — validated by `adopt.manifest`, unvalidated by the profile.
    """
    free_form = {"project.name", "authority.write_scope"}
    assert (dimension in DECLARED_VOCABULARIES) is (dimension not in free_form)


def test_the_vocabulary_drift_guard_actually_fires() -> None:
    """`_assert_vocabulary_matches` must fail when the two definitions disagree.

    The guard exists because `adopt.manifest` names each enum at its call site (it
    needs the static return type) while `profile.synth` and `inspect.readiness` read
    the same correspondence out of `DECLARED_VOCABULARIES`. Two copies of one fact
    drift, and the drift's shape is exactly the defect this was added alongside: a
    manifest refusing a value the profile happily published.

    An independent review found the guard was called for every vocabulary dimension
    and did fire on real drift — but that deleting it broke no test. A guard nothing
    proves is a guard nobody can rely on, so this proves it directly rather than
    inferring it from the fact that the suite is green.
    """
    from agent_foundry.adopt.manifest import _assert_vocabulary_matches
    from agent_foundry.inspect.classification import DECLARED_VOCABULARIES
    from agent_foundry.models.common import Autonomy, Reversibility

    dimension = "impact.reversibility"
    assert DECLARED_VOCABULARIES[dimension] is Reversibility

    # Agreement is silent.
    _assert_vocabulary_matches(dimension, Reversibility)

    # Disagreement is loud, and names both sides so the reader can tell which moved.
    with pytest.raises(AssertionError) as caught:
        _assert_vocabulary_matches(dimension, Autonomy)
    message = str(caught.value)
    assert dimension in message
    assert "Reversibility" in message and "Autonomy" in message


def test_every_vocabulary_dimension_is_actually_guarded(monkeypatch) -> None:
    """The guard covering 13 of 14 dimensions would be worth nothing on the 14th.

    `DECLARED_VOCABULARIES` is the shared definition and `adopt.manifest` holds the
    copy; every entry must be checked, or the unchecked one drifts silently, which is
    the whole failure mode.

    This spies the guard during a real `synthesize_manifest` over a fully-declared
    project rather than scanning source, because the call sites pass `dimension` as a
    variable from two helpers — there is no literal to grep for, and a source scan
    would silently pass while proving nothing.
    """
    from agent_foundry.adopt import manifest as manifest_module
    from agent_foundry.inspect import inspect_project
    from agent_foundry.inspect.classification import DECLARED_VOCABULARIES

    seen: set[str] = set()
    original = manifest_module._assert_vocabulary_matches

    def spy(dimension: str, enum_type: type) -> None:
        seen.add(dimension)
        original(dimension, enum_type)

    monkeypatch.setattr(manifest_module, "_assert_vocabulary_matches", spy)

    fixture = Path(__file__).resolve().parent / "fixtures" / "projects" / "e2e-synthetic"
    manifest_module.synthesize_manifest(inspect_project(fixture))

    unguarded = sorted(set(DECLARED_VOCABULARIES) - seen)
    assert unguarded == [], (
        f"these dimensions have a shared vocabulary that `adopt.manifest` never checks "
        f"its own enum against, so the two can drift silently: {unguarded}"
    )
