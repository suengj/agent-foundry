"""Structural guards on the independence of the validation layer.

Three things have to stay true for the AF7 validators to be worth anything:

1. The re-derived primitives must not quietly start importing the implementations
   they exist to be independent of. That is checked by reading the import graph, so
   it survives a refactor that nobody re-reads this file for.
2. No module anywhere in `verify/` may call a *producer-owned validation rule* — a
   helper that a pydantic `model_validator` or `field_validator` in `models/` uses to
   decide whether an artifact may exist. Those helpers are producers. A validator
   that calls one agrees with it however wrong it is.

   This second guard exists because the first one was not enough. It read only
   `verify/independent.py`, so it could not see an import made from
   `verify/validators.py` — and two validators went out coupled to the producer
   rules they were supposed to check independently. The guard below discovers the
   producer rules by walking `models/` for functions called inside a validator
   decorator, rather than from a hand-maintained list, so a new producer rule is
   protected the day it is written.
3. Every validator must publish what it proves and what it cannot, and those claims
   must stay in one-to-one correspondence with the code.

The scan here is syntactic, and syntactic scanning can never be complete: a call
assembled at runtime through `getattr` or `__import__` is invisible to it. That is
not a gap to be closed by enumerating dynamic spellings — it is a losing arms race.
`tests/test_verify_producer_tripwire.py` answers it behaviorally instead, by wrapping
the producer rules and observing whether a validator actually calls one. This file
stays because it is fast and catches the ordinary static regression; the two guards
together are the same two-derivations principle the rest of AF7 rests on.
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
VERIFY_MODULES = sorted((SRC / "verify").glob("*.py"))
MODELS_MODULES = sorted((SRC / "models").glob("*.py"))

VALIDATOR_DECORATORS = frozenset({"model_validator", "field_validator"})

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
    """Every module named by an import in this file, including deferred ones."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


def _decorator_name(node: ast.expr) -> str | None:
    while isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def producer_validation_rules() -> dict[str, str]:
    """Helpers that a model validator in `models/` calls to gate construction.

    Discovered rather than listed: any module-level function called from inside a
    `@model_validator` or `@field_validator` body is, by definition, part of the rule
    that decides whether the producer will emit the artifact at all.
    """
    rules: dict[str, str] = {}
    for path in MODELS_MODULES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module_level = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not any(
                _decorator_name(decorator) in VALIDATOR_DECORATORS
                for decorator in node.decorator_list
            ):
                continue
            for called in ast.walk(node):
                if isinstance(called, ast.Call) and isinstance(called.func, ast.Name):
                    if called.func.id in module_level:
                        rules[called.func.id] = f"agent_foundry.models.{path.stem}"
    return rules


def _referenced_names(path: Path) -> set[str]:
    """Names this file imports or reaches for as an attribute.

    Covers `from x import rule`, `import x` then `x.rule(...)`, and imports made
    inside a function body, so there is no spelling of "call the producer's rule"
    that slips past.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names)
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


@pytest.mark.parametrize("path", VERIFY_MODULES, ids=lambda p: p.name)
def test_no_verify_module_imports_a_producing_package(path):
    """Widened from `independent.py` alone: the narrow guard let a coupling through."""
    imported = _imported_modules(path)
    offenders = sorted(
        module
        for module in imported
        for root in FORBIDDEN_IMPORT_ROOTS
        if module == root or module.startswith(f"{root}.")
    )
    assert offenders == [], (
        f"verify/{path.name} imports {offenders}; a validator built on the code that "
        "produces the artifact agrees with it by construction"
    )


def test_producer_validation_rules_are_discovered_not_assumed():
    """The discovery has to actually find the rules, or the next guard is vacuous."""
    rules = producer_validation_rules()
    for expected in (
        "disposition_obligation_violations",
        "evidence_state_partition_violations",
        "validate_schema_compatibility",
        "lint_no_raw_secrets",
    ):
        assert expected in rules, f"{expected} was not discovered as a producer rule"


@pytest.mark.parametrize("path", VERIFY_MODULES, ids=lambda p: p.name)
def test_no_verify_module_calls_a_producer_owned_validation_rule(path):
    """A model validator's helper decides whether the artifact may exist.

    Reusing it here would mean a wrong rule and its purported validator agree —
    the AF6 failure mode, one layer down. The obligations those helpers encode are
    restated in `verify/independent.py` from the contract text instead.
    """
    rules = producer_validation_rules()
    referenced = _referenced_names(path)
    offenders = sorted(name for name in referenced if name in rules)
    assert offenders == [], (
        f"verify/{path.name} references producer validation rule(s) {offenders} "
        f"(defined in {sorted({rules[name] for name in offenders})}); re-derive the "
        "rule in verify/independent.py instead of calling the producer's copy"
    )


def test_the_producer_rule_guard_would_catch_a_reintroduced_coupling(tmp_path):
    """Guard the guard: a file that does import the producer rule must be flagged."""
    offending = tmp_path / "recoupled.py"
    offending.write_text(
        "from agent_foundry.models.interaction import "
        "evidence_state_partition_violations\n",
        encoding="utf-8",
    )
    rules = producer_validation_rules()
    referenced = _referenced_names(offending)
    assert sorted(name for name in referenced if name in rules) == [
        "evidence_state_partition_violations"
    ]

    attribute_style = tmp_path / "recoupled_attr.py"
    attribute_style.write_text(
        "from agent_foundry.models import interaction\n"
        "def check(x):\n"
        "    return interaction.disposition_obligation_violations(**x)\n",
        encoding="utf-8",
    )
    referenced_attr = _referenced_names(attribute_style)
    assert "disposition_obligation_violations" in referenced_attr


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


def test_independence_claims_rest_on_the_dependency_guard_not_on_assertion():
    """`independently_derived=True` has to be backed by something mechanical.

    Every validator lives in a module the guard above covers, and that guard fails on
    any reference to a producer-owned validation rule. So a True in the catalog is
    only sayable while no validator module calls a producer's rule — which is what
    went wrong the first time this shipped, and what is now checked rather than
    claimed.
    """
    hosting = {"validators.py", "explain.py", "independent.py"}
    covered = {path.name for path in VERIFY_MODULES}
    assert hosting <= covered, sorted(hosting - covered)

    rules = producer_validation_rules()
    assert rules, "producer-rule discovery found nothing; the guard would be vacuous"
    for path in VERIFY_MODULES:
        offenders = sorted(name for name in _referenced_names(path) if name in rules)
        assert offenders == [], (path.name, offenders)


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
