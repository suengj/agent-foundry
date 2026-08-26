"""Structural guards on the independence of the validation layer.

Two things have to stay true for the AF7 validators to be worth anything:

1. The re-derived primitives must not quietly start importing the implementations
   they exist to be independent of. That is checked by reading the import graph, so
   it survives a refactor that nobody re-reads this file for.
2. Every validator must publish what it proves and what it cannot, and those claims
   must stay in one-to-one correspondence with the code.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from agent_foundry.verify import VALIDATOR_CLAIMS, VALIDATOR_IDS
from agent_foundry.verify import claims as claims_module
from agent_foundry.verify import validators as validators_module
from agent_foundry.verify import explain as explain_module
from agent_foundry.verify.independent import (
    EVIDENCE_STATE_PROGRESSION,
    EXTERNAL_EFFECT_ASCENDING,
    contained_in_any,
    effect_rank,
    exceeds,
    health_satisfies,
    normalize_repository_path,
    parse_major_minor,
    path_within,
    tightest,
)

SRC = Path(__file__).resolve().parents[1] / "src" / "agent_foundry"
INDEPENDENT = SRC / "verify" / "independent.py"

# Packages whose implementations the independent layer must never consult. Importing
# any of them would make a "second derivation" a call back into the first.
FORBIDDEN_IMPORT_ROOTS = (
    "agent_foundry.compile",
    "agent_foundry.toolkit",
    "agent_foundry.work",
    "agent_foundry.adopt",
    "agent_foundry.inspect",
)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


def test_the_independent_layer_imports_none_of_the_producing_packages():
    imported = _imported_modules(INDEPENDENT)
    offenders = sorted(
        module
        for module in imported
        for root in FORBIDDEN_IMPORT_ROOTS
        if module == root or module.startswith(f"{root}.")
    )
    assert offenders == [], (
        f"{INDEPENDENT.name} imports {offenders}; a validator built on the code that "
        "produces the artifact agrees with it by construction"
    )


def test_the_independent_layer_only_depends_on_contracts():
    imported = _imported_modules(INDEPENDENT)
    foundry = {module for module in imported if module.startswith("agent_foundry")}
    assert all(module.startswith("agent_foundry.models") for module in foundry), foundry


def test_the_independent_effect_order_agrees_with_the_ceiling_table_it_does_not_import():
    """A second derivation that agrees is evidence — so check that it does agree.

    If this ever fails, one of the two orderings is wrong and the disagreement is the
    finding. Importing the other table to build this one would make the check vacuous.
    """
    from agent_foundry.toolkit.ceiling import EFFECT_RANK

    for effect in EXTERNAL_EFFECT_ASCENDING:
        assert effect_rank(effect) == EFFECT_RANK[effect], effect


def test_the_independent_path_resolution_agrees_with_the_compiler_on_shared_cases():
    from agent_foundry.compile.authority import _normalize_scope_path

    cases = [
        "src/",
        "./src",
        "src//nested",
        "src/../lib",
        "src/../../etc",
        "/etc/passwd",
        "..",
        ".",
        "",
        "C:/repo/src",
        "\\\\host\\share",
    ]
    for case in cases:
        assert normalize_repository_path(case) == _normalize_scope_path(case), case


def test_the_independent_layer_rejects_url_shaped_bounds_the_compiler_also_rejects():
    from agent_foundry.compile.authority import _normalize_scope_path

    assert normalize_repository_path("http://example.invalid/x") is None
    assert _normalize_scope_path("http://example.invalid/x") is None


def test_containment_helpers_behave_as_bounds_rather_than_string_prefixes():
    assert path_within("src", "src/module.py")
    assert path_within("src", "src")
    assert not path_within("src", "srcx/module.py")
    assert not path_within("src", "../src/module.py")
    assert contained_in_any("tests/unit", ["src", "tests"])
    assert not contained_in_any("docs", ["src", "tests"])


def test_an_unknown_requirement_outranks_every_declared_level():
    assert exceeds(None, EXTERNAL_EFFECT_ASCENDING[-1])
    assert tightest(None, None) == EXTERNAL_EFFECT_ASCENDING[0]


def test_silence_grants_read_only_not_everything():
    from agent_foundry.models import ExternalEffectClass

    assert exceeds(ExternalEffectClass.REPOSITORY_WRITE, None)
    assert not exceeds(ExternalEffectClass.READ_ONLY, None)


def test_health_ordering_never_lets_an_unobserved_state_satisfy_a_requirement():
    from agent_foundry.models import IntegrationHealthState

    assert health_satisfies(None, IntegrationHealthState.DESIRED) is False
    assert health_satisfies(IntegrationHealthState.UNAVAILABLE, IntegrationHealthState.DESIRED) is False
    assert health_satisfies(IntegrationHealthState.HEALTHY, IntegrationHealthState.AUTHORIZED)
    assert health_satisfies(IntegrationHealthState.DEGRADED, IntegrationHealthState.HEALTHY)
    assert not health_satisfies(IntegrationHealthState.CONFIGURED, IntegrationHealthState.AUTHENTICATED)


def test_not_required_has_no_position_on_the_evidence_ladder():
    from agent_foundry.models import EvidenceState

    assert EvidenceState.NOT_REQUIRED not in EVIDENCE_STATE_PROGRESSION
    assert len(EVIDENCE_STATE_PROGRESSION) == len(EvidenceState) - 1


@pytest.mark.parametrize(
    ("text", "expected"),
    [("0.1", (0, 1)), ("1.10", (1, 10)), ("0", None), ("0.1.2", None), ("x.y", None)],
)
def test_schema_version_parsing_is_strict(text, expected):
    assert parse_major_minor(text) == expected


# --- the claims catalog stays in step with the code ---------------------------------


def _public_validator_names() -> set[str]:
    names = {
        name
        for name in dir(validators_module)
        if name.startswith("validate_") and callable(getattr(validators_module, name))
    }
    names.add("validate_decision_explainability")
    return names


def test_every_validator_publishes_a_claim():
    functions = _public_validator_names()
    # Each function's claim id is its name minus the `validate_` prefix, in kebab case.
    expected = {name.removeprefix("validate_").replace("_", "-") for name in functions}
    # Two functions share the schema-compatibility id with the model-level helper name.
    missing = sorted(expected - set(VALIDATOR_IDS))
    assert missing == [], f"validators without a published claim: {missing}"


def test_every_claim_belongs_to_a_validator_that_exists():
    functions = _public_validator_names()
    ids_from_code = {name.removeprefix("validate_").replace("_", "-") for name in functions}
    orphans = sorted(set(VALIDATOR_IDS) - ids_from_code)
    assert orphans == [], f"claims with no validator: {orphans}"


def test_claims_are_unique_and_say_what_they_cannot_prove():
    assert len(VALIDATOR_IDS) == len(set(VALIDATOR_IDS))
    for claim in VALIDATOR_CLAIMS:
        assert claim.proves.strip(), claim.validator_id
        assert claim.cannot_prove.strip(), claim.validator_id
        assert len(claim.cannot_prove) > 30, claim.validator_id


def test_a_claim_that_is_not_independently_derived_explains_what_it_is_worth():
    dependent = [claim for claim in VALIDATOR_CLAIMS if not claim.independently_derived]
    assert dependent, "at least one honest dependency is expected to be declared"
    for claim in dependent:
        assert "worth" in claim.cannot_prove or "and nothing more" in claim.cannot_prove


def test_most_validators_are_independently_derived():
    independent = [claim for claim in VALIDATOR_CLAIMS if claim.independently_derived]
    assert len(independent) >= len(VALIDATOR_CLAIMS) - 1


def test_every_finding_a_validator_emits_carries_its_own_id():
    """A report whose findings name a different validator would misattribute a defect."""
    from verify_support import compiled

    artifacts = compiled()
    report = validators_module.validate_execution_bundle_completeness(artifacts["bundle"])
    assert {finding.validator_id for finding in report.findings} == {
        claims_module.EXECUTION_BUNDLE_COMPLETENESS
    }
    explain_report = explain_module.validate_decision_explainability(artifacts["bundle"])
    assert {finding.validator_id for finding in explain_report.findings} == {
        claims_module.DECISION_EXPLAINABILITY
    }


def test_no_report_is_ever_silently_empty():
    """An empty report aggregates to MISSING, so silence can never read as a pass."""
    from agent_foundry.models import ValidationOutcome, ValidationReport

    empty = ValidationReport(subject_kind="x", subject_id="y")
    assert empty.outcome() == ValidationOutcome.MISSING
    assert empty.accepted() is False
