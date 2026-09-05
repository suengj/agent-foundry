"""Schema 0.2 contract rebase: wire-token migration and fail-closed compatibility.

Two properties are under test, and they are the two halves of "versioned rather than
silently accepted":

* a v0.1 artifact still loads, and comes out declaring the current schema version;
* an artifact that declares 0.2 while carrying a 0.1 token is refused with an
  explicit compatibility error naming the field, the legacy token and its
  replacement — not a generic enum error that reads as a typo.
"""

from __future__ import annotations

import collections.abc
import copy
import json
import tomllib
import typing
from pathlib import Path

import pytest

import agent_foundry.models as models
from agent_foundry import __version__
from agent_foundry.models.base import FoundryModel
from agent_foundry.models import (
    FOUNDRY_SCHEMA_VERSION,
    CapabilityRegistry,
    IntegrationSpec,
    ContractMigrationError,
    SchemaCompatibilityError,
    SkillSpec,
    SkillTriggers,
    ToolkitLock,
    UnmigratableContractError,
    WorkClass,
    WorkItemContract,
    WorkPlan,
    dump_yaml,
    load_yaml,
    migrate_contract_payload,
)
from agent_foundry.models.compat import TOKEN_MIGRATIONS

REPO_ROOT = Path(__file__).resolve().parents[1]
LEGACY_V0_1 = Path(__file__).resolve().parent / "fixtures" / "legacy" / "v0_1"
CANONICAL = Path(__file__).resolve().parent / "fixtures" / "valid"
DELTA_DOC = REPO_ROOT / "docs" / "contracts" / "v0.2-contract-delta.md"


def _canonical_work_item(schema_version: str = FOUNDRY_SCHEMA_VERSION) -> dict:
    return {
        "schema_version": schema_version,
        "id": "WI-COMPAT",
        "title": "Compat",
        "work_class": WorkClass.CAPABILITY.value,
        "objective": "Objective",
        "current_facts": ["fact"],
        "scope": ["src/"],
        "out_of_scope": ["out"],
        "acceptance_criteria": ["criteria"],
        "authority_class": "repository-write",
        "consequence_class": "medium",
        "required_evidence": ["deterministic-test"],
        "stop_conditions": ["stop"],
    }


def _all_models() -> list[type]:
    """Every Foundry model class, so a reflection guard cannot miss a module."""
    import importlib
    import pkgutil

    from pydantic import BaseModel

    import agent_foundry.models as models_pkg

    found: dict[str, type] = {}
    for module_info in pkgutil.iter_modules(models_pkg.__path__):
        module = importlib.import_module(f"agent_foundry.models.{module_info.name}")
        for attribute_name in dir(module):
            candidate = getattr(module, attribute_name)
            if (
                isinstance(candidate, type)
                and issubclass(candidate, BaseModel)
                and getattr(candidate, "__name__", "") == attribute_name
                and candidate.__module__.startswith("agent_foundry")
            ):
                found[f"{candidate.__module__}.{candidate.__name__}"] = candidate
    assert len(found) > 50, f"reflection found only {len(found)} models; it is broken"
    return [found[key] for key in sorted(found)]


def _work_plan(*, outer: str, inner: str, token: str) -> dict:
    """A work plan and a nested work item, each declaring its own schema version."""
    nested = _canonical_work_item(schema_version=inner)
    nested["work_class"] = token
    return {
        "schema_version": outer,
        "objective": {"id": "OBJ", "title": "t", "description": "d"},
        "work_items": [nested],
    }


# --- the version rebase itself ---------------------------------------------------


def test_schema_version_is_the_v0_2_line() -> None:
    assert FOUNDRY_SCHEMA_VERSION == "0.2"


def test_package_version_is_the_v0_2_development_line() -> None:
    """Every place the version is *stated* must agree with the one that is *used*.

    `__version__` is what `doctor` reports and what `foundry_compat` is evaluated
    against. `pyproject.toml` is what a build installs. The README is what a reader
    believes. An unguarded restatement is how the README came to claim `0.1.0` while
    `doctor` printed `0.2.0.dev0`, so all three are pinned together here.
    """
    assert __version__ == "0.2.0.dev0"
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == __version__

    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    heading = readme.index("## Release status")
    stated = readme[heading : readme.index("```", readme.index("```text", heading) + 7)]
    stated_version = stated.split("```text", 1)[1].strip()
    assert stated_version == __version__, (
        "README 'Release status' states a package version that is not the one the "
        f"package reports: README says {stated_version!r}, __version__ is {__version__!r}"
    )


# --- migrating a real preserved v0.1 artifact ------------------------------------


def test_legacy_v0_1_work_item_loads_and_is_upgraded() -> None:
    obj = load_yaml(WorkItemContract, (LEGACY_V0_1 / "work_item_contract.yaml").read_bytes())
    assert obj.work_class is WorkClass.CAPABILITY
    assert obj.schema_version == FOUNDRY_SCHEMA_VERSION


def test_legacy_fixture_on_disk_still_declares_the_old_contract() -> None:
    """The fixture proves migration only while it stays legacy.

    A well-meaning "fix" that rewrote these files would leave the migration path
    untested while every assertion above still passed, so the file's own bytes are
    asserted rather than only what they load into.
    """
    raw = (LEGACY_V0_1 / "work_item_contract.yaml").read_text(encoding="utf-8")
    assert 'schema_version: "0.1"' in raw
    assert "work_class: CAPABILITY" in raw
    raw_skill = (LEGACY_V0_1 / "skill_spec.yaml").read_text(encoding="utf-8")
    assert 'schema_version: "0.1"' in raw_skill
    assert "- CAPABILITY" in raw_skill


def test_migrated_object_round_trips_deterministically() -> None:
    source = (LEGACY_V0_1 / "work_item_contract.yaml").read_bytes()
    first = load_yaml(WorkItemContract, source)
    dumped = dump_yaml(first)
    second = load_yaml(WorkItemContract, dumped)
    assert second == first
    # Byte-stable: a migrated artifact re-dumps to itself, so re-saving a migrated
    # file is not an endless source of diff noise.
    assert dump_yaml(second) == dumped
    # And the dumped bytes carry the canonical token and the current version, so the
    # emitted artifact is not self-contradictory.
    assert b"work_class: capability" in dumped
    assert f"schema_version: '{FOUNDRY_SCHEMA_VERSION}'".encode() in dumped


# --- the fail-closed half --------------------------------------------------------


def test_current_version_payload_with_legacy_token_fails_closed() -> None:
    payload = _canonical_work_item()
    payload["work_class"] = "CAPABILITY"
    with pytest.raises(ContractMigrationError) as exc_info:
        WorkItemContract.model_validate(payload)
    message = str(exc_info.value)
    assert "WorkItemContract" in message
    assert "work_class" in message
    assert "CAPABILITY" in message
    assert "capability" in message
    assert FOUNDRY_SCHEMA_VERSION in message


def test_contract_migration_error_is_a_schema_compatibility_error() -> None:
    """Callers that already treat schema incompatibility as fatal must not start
    letting a legacy token through because it arrived under a new class name."""
    assert issubclass(ContractMigrationError, SchemaCompatibilityError)


def test_fail_closed_error_carries_structured_fields() -> None:
    payload = _canonical_work_item()
    payload["work_class"] = "RESIDUAL_HARDENING"
    with pytest.raises(ContractMigrationError) as exc_info:
        WorkItemContract.model_validate(payload)
    error = exc_info.value
    assert error.json_path == "work_class"
    assert error.legacy_token == "RESIDUAL_HARDENING"
    assert error.canonical_token == "residual-hardening"
    assert error.changed_in == "0.2"


# --- the nested / list-valued field ----------------------------------------------


def test_legacy_nested_list_field_migrates() -> None:
    obj = load_yaml(SkillSpec, (LEGACY_V0_1 / "skill_spec.yaml").read_bytes())
    assert obj.triggers.work_classes == [WorkClass.CAPABILITY, WorkClass.ADOPTION]
    assert obj.schema_version == FOUNDRY_SCHEMA_VERSION


def test_current_version_nested_list_field_fails_closed() -> None:
    payload = {
        "schema_version": FOUNDRY_SCHEMA_VERSION,
        "id": "skill-x",
        "version": "1.0.0",
        "description": "d",
        "triggers": {"work_classes": ["capability", "ADOPTION"]},
    }
    with pytest.raises(ContractMigrationError) as exc_info:
        SkillSpec.model_validate(payload)
    error = exc_info.value
    assert error.json_path == "triggers.work_classes[1]"
    assert error.legacy_token == "ADOPTION"
    assert error.canonical_token == "adoption"


# --- the nested-contract version boundary ----------------------------------------
#
# A nested mapping that declares its own `schema_version` is a separately versioned
# contract: the outer walk skips it, and it migrates against *its own* declared
# version when pydantic descends into it. Removing that rule leaves the whole suite
# green unless both directions below are pinned, and it breaks both of them at once —
# one by rejecting an artifact that is fine, the other by accepting one that is not.


def test_newer_outer_contract_does_not_reject_an_older_nested_one() -> None:
    """Direction one: a 0.2 plan carrying 0.1 work items is a normal artifact.

    Without the boundary rule the outer walk runs in fail-closed mode over the whole
    tree and rejects the nested legacy token, even though the nested contract declares
    the version that entitles it to be migrated.
    """
    plan = WorkPlan.model_validate(_work_plan(outer="0.2", inner="0.1", token="CAPABILITY"))
    assert plan.schema_version == FOUNDRY_SCHEMA_VERSION
    assert plan.work_items[0].schema_version == FOUNDRY_SCHEMA_VERSION
    assert plan.work_items[0].work_class is WorkClass.CAPABILITY


def test_older_outer_contract_does_not_silently_migrate_a_newer_nested_one() -> None:
    """Direction two, and the one that matters: fail-closed must hold at every depth.

    Without the boundary rule the outer 0.1 artifact puts the walk in rewrite mode for
    the entire tree, so the nested contract's own 0.2 declaration is ignored and its
    legacy token is silently corrected. The guarantee that a 0.2 artifact cannot carry
    a 0.1 token would then hold only at the top level.
    """
    with pytest.raises(ContractMigrationError) as exc_info:
        WorkPlan.model_validate(_work_plan(outer="0.1", inner="0.2", token="CAPABILITY"))
    error = exc_info.value
    assert error.contract_name == "WorkItemContract"
    assert error.json_path == "work_class"
    assert error.legacy_token == "CAPABILITY"


def test_legacy_v0_1_work_plan_migrates_outer_and_nested() -> None:
    plan = load_yaml(WorkPlan, (LEGACY_V0_1 / "work_plan.yaml").read_bytes())
    assert plan.schema_version == FOUNDRY_SCHEMA_VERSION
    assert plan.work_items[0].schema_version == FOUNDRY_SCHEMA_VERSION
    assert plan.work_items[0].work_class is WorkClass.CAPABILITY


def test_legacy_v0_1_registry_migrates_its_nested_skill_spec() -> None:
    registry = load_yaml(
        CapabilityRegistry, (LEGACY_V0_1 / "capability_registry.yaml").read_bytes()
    )
    assert registry.schema_version == FOUNDRY_SCHEMA_VERSION
    skill = registry.skills[0]
    assert skill.schema_version == FOUNDRY_SCHEMA_VERSION
    assert skill.triggers.work_classes == [
        WorkClass.CAPABILITY,
        WorkClass.RESIDUAL_HARDENING,
    ]


def test_registry_nested_skill_declaring_current_version_fails_closed() -> None:
    """The same fail-closed guarantee, one level deeper than `SkillSpec` itself."""
    payload = {
        "schema_version": "0.1",
        "foundry_compat": ">=0.1,<0.3",
        "skills": [
            {
                "schema_version": FOUNDRY_SCHEMA_VERSION,
                "id": "skill-x",
                "version": "1.0.0",
                "description": "d",
                "triggers": {"work_classes": ["ADOPTION"]},
            }
        ],
    }
    with pytest.raises(ContractMigrationError) as exc_info:
        CapabilityRegistry.model_validate(payload)
    assert exc_info.value.contract_name == "SkillSpec"
    assert exc_info.value.json_path == "triggers.work_classes[0]"


# --- free-form data is not this module's business ---------------------------------
#
# The traversal is type-directed: it follows the contract's declared field types, not
# key names in the payload. `IntegrationSpec.adapter_options` is a `FreeFormMapping` —
# an adapter-owned namespace where a key called `work_class` is entirely plausible —
# and Core rewriting a provider's option value would be both an unversioned
# compatibility break and the exact opposite of provider-neutral.


def _integration_spec(schema_version: str, adapter_options: dict) -> dict:
    return {
        "schema_version": schema_version,
        "id": "work-tracker",
        "kind": "integration",
        "transport": "mcp",
        "version": "1",
        "permissions": {"write_requires": "explicit-authority"},
        "health": {"required": "authenticated"},
        "adapter_options": adapter_options,
    }


_COLLIDING_ADAPTER_OPTIONS = {
    "work_class": "CAPABILITY",
    "work_classes": ["ADOPTION", "CAPABILITY"],
    "suggested_work_class": "DISCOVERY",
    "nested": {"work_class": "INCIDENT"},
}


def test_free_form_adapter_options_are_not_rewritten_when_migrating() -> None:
    """Direction one: a v0.1 artifact keeps its adapter values verbatim."""
    spec = IntegrationSpec.model_validate(
        _integration_spec("0.1", dict(_COLLIDING_ADAPTER_OPTIONS))
    )
    assert spec.schema_version == FOUNDRY_SCHEMA_VERSION
    assert spec.adapter_options == _COLLIDING_ADAPTER_OPTIONS


def test_free_form_adapter_options_do_not_trigger_fail_closed() -> None:
    """Direction two: a valid 0.2 artifact is not rejected over free-form data.

    This is the worse half. Rejecting a legitimate provider configuration with a
    contract-migration error tells the owner to change a value that was never
    Foundry's to name.
    """
    spec = IntegrationSpec.model_validate(
        _integration_spec(FOUNDRY_SCHEMA_VERSION, dict(_COLLIDING_ADAPTER_OPTIONS))
    )
    assert spec.adapter_options == _COLLIDING_ADAPTER_OPTIONS


def test_free_form_collision_survives_a_round_trip() -> None:
    """And the value is still there after the artifact is written back out."""
    spec = IntegrationSpec.model_validate(
        _integration_spec("0.1", dict(_COLLIDING_ADAPTER_OPTIONS))
    )
    reloaded = load_yaml(IntegrationSpec, dump_yaml(spec))
    assert reloaded.adapter_options == _COLLIDING_ADAPTER_OPTIONS
    assert reloaded == spec


def test_undeclared_keys_are_passed_through_for_pydantic_to_reject() -> None:
    """Migration must not pre-empt `extra="forbid"` by editing a key nobody declared."""
    payload = _canonical_work_item(schema_version="0.1")
    payload["not_a_field"] = {"work_class": "CAPABILITY"}
    migrated = migrate_contract_payload(payload, WorkItemContract)
    assert migrated["not_a_field"] == {"work_class": "CAPABILITY"}
    with pytest.raises(Exception) as exc_info:
        WorkItemContract.model_validate(payload)
    assert not isinstance(exc_info.value, ContractMigrationError)


def test_the_walker_and_the_registry_guard_share_one_definition() -> None:
    """The implementation scopes by declared type; so does the exhaustiveness guard.

    They disagreed once — the guard scoped to `WorkClass`-typed fields while the
    walker matched key names at any depth — and a green suite over a broken behaviour
    was the result. This pins that the walker's per-model plan is derived from the
    same annotations the guard reflects over.
    """
    from agent_foundry.models.compat import _plan_for

    assert set(_plan_for(WorkItemContract).tokens) == {"work_class"}
    assert set(_plan_for(SkillTriggers).tokens) == {"work_classes"}
    # A free-form mapping is neither a token field nor a descendable child.
    integration_plan = _plan_for(IntegrationSpec)
    assert "adapter_options" not in integration_plan.tokens
    assert "adapter_options" not in integration_plan.children
    # A nested versioned contract is not descended into either: it migrates itself.
    assert "work_items" not in _plan_for(WorkPlan).children
    assert "skills" not in _plan_for(CapabilityRegistry).children


# --- traversal cannot guess, and cannot silently do nothing -----------------------
#
# Two ways a type-directed walker fails quietly. It can descend a payload against a
# model the annotation does not pin down, rewriting data that model does not own; or
# it can register a field as descendable and then never reach it, so a legacy token
# there is neither migrated nor failed closed. Both are unreachable in the models
# shipped today, and both are the mechanism's own invariant rather than a property of
# the current model set — which is why they are pinned rather than left to chance.


def test_an_ambiguous_union_of_models_is_refused_not_guessed() -> None:
    """`A | B` gives migration no declared type, so it must refuse to plan the field.

    Arbitrarily descending against whichever arm comes first reintroduces the round-2
    defect behind a union: a field on the *non*-selected arm gets rewritten, and a
    valid current-version payload of the other shape is rejected.
    """
    from agent_foundry.models.base import FoundryModel
    from agent_foundry.models.compat import MigrationPlanError, _plan_for

    class _ArmA(FoundryModel):
        work_class: WorkClass

    class _ArmB(FoundryModel):
        work_class: str

    class _Ambiguous(FoundryModel):
        either: _ArmA | _ArmB

    with pytest.raises(MigrationPlanError) as exc_info:
        _plan_for(_Ambiguous)
    message = str(exc_info.value)
    assert "_Ambiguous.either" in message
    assert "_ArmA" in message and "_ArmB" in message


def test_no_shipped_model_declares_an_ambiguous_nested_union() -> None:
    """The guard above only helps if nothing already trips it.

    This cannot be caught by the `WorkClass`-typed reflection guard: the field that
    gets corrupted under an ambiguous union is typically not `WorkClass`-typed at all.
    Introducing such a field must fail here rather than at some later data loss.
    """
    from agent_foundry.models.compat import MigrationPlanError, _plan_for

    offenders: list[str] = []
    for model in _all_models():
        try:
            _plan_for(model)
        except MigrationPlanError as exc:
            offenders.append(f"{model.__name__}: {exc}")
    assert offenders == [], "\n".join(offenders)


def _holder(annotation: object) -> type:
    """A throwaway versioned contract with one field of the given annotation."""
    from agent_foundry.models.base import VersionedContract

    return type(
        "_Holder",
        (VersionedContract,),
        {"__annotations__": {"either": annotation}, "either": None},
    )


class _Held(FoundryModel):
    """Nested model carrying the one migrated vocabulary."""

    work_classes: list[WorkClass] = []


def test_every_planned_child_is_walked_for_real() -> None:
    """Plan and descent must agree, asserted by walking rather than by re-deriving.

    The earlier version of this test asked a second function whether each planned
    child was reachable. That function re-implemented the descent's branch structure,
    so the two agreed with each other and disagreed with the code that actually walks —
    which is how a union-shaped field came to be registered and then never descended.
    This drives the real traversal instead: every field the plan registers as a child
    must, given a payload of the right shape, come back as a *new* object. A field the
    descent silently declines to walk returns the identical input and fails here.
    """
    from agent_foundry.models.compat import _descend, _descent_route, _plan_for

    def probe(annotation: object) -> object | None:
        """A payload shaped like the route this annotation offers."""
        route = _descent_route(annotation)
        if route is None:
            return None
        if route.kind == "model":
            return {}
        if route.kind == "mapping":
            return {"k": {}}
        origin = typing.get_origin(route.annotation)
        args = typing.get_args(route.annotation)
        positional = origin is tuple and len(args) > 1 and args[1] is not Ellipsis
        return [{} for _ in args] if positional else [{}]

    unwalked: list[str] = []
    for model in _all_models():
        for field_name, annotation in _plan_for(model).children.items():
            payload = probe(annotation)
            walked = _descend(
                payload,
                annotation,
                contract_name=model.__name__,
                json_path="probe",
                declared=(0, 1),
                declared_version="0.1",
            )
            if walked is payload:
                unwalked.append(f"{model.__name__}.{field_name}: {annotation!r}")
    assert unwalked == [], (
        "field(s) registered as descendable that the traversal does not walk:\n"
        + "\n".join(unwalked)
    )


# --- unions that name more than one descendable shape ------------------------------
#
# `_descend` used to resolve a union itself, and did it twice over: it short-circuited
# on a directly-named model before the union branch could run, and when it did run it
# took whichever arm first produced a new object. `list[Model] | Model` — the ordinary
# one-or-many idiom — was therefore registered as descendable and then walked in
# neither declaration order, and `list[str] | list[Model]` behaved differently from
# `list[Model] | list[str]`. Unions now collapse in one place, before descent.


@pytest.mark.parametrize(
    ("label", "annotation_factory"),
    [
        ("list[Held] | Held", lambda held: list[held] | held),
        ("Held | list[Held]", lambda held: held | list[held]),
    ],
)
def test_a_union_of_two_descendable_shapes_is_refused(label, annotation_factory) -> None:
    """Both declaration orders, because this is not an ordering edge case.

    Refusing rather than handling is the same call made for a union of two distinct
    models: there is no declared type to descend against, and either choice
    under-migrates some payloads. A model declaring this gets a loud, deterministic
    failure here instead of a silent gap downstream.
    """
    from agent_foundry.models.compat import MigrationPlanError, _plan_for

    with pytest.raises(MigrationPlanError) as exc_info:
        _plan_for(_holder(annotation_factory(_Held)))
    assert "more than one arm that reaches a nested model" in str(exc_info.value)


@pytest.mark.parametrize(
    ("label", "annotation_factory"),
    [
        ("list[str] | list[Held]", lambda held: list[str] | list[held]),
        ("list[Held] | list[str]", lambda held: list[held] | list[str]),
    ],
)
def test_one_reaching_arm_migrates_the_same_in_either_order(
    label, annotation_factory
) -> None:
    """Only one arm reaches a model, so there is a declared type — and order is moot.

    These two spellings previously behaved differently from each other: one migrated
    and failed closed, the other did neither. Same set of arms, different outcome,
    decided by which was written first.
    """
    from agent_foundry.models.compat import migrate_contract_payload

    contract = _holder(annotation_factory(_Held))
    migrated = migrate_contract_payload(
        {"schema_version": "0.1", "either": [{"work_classes": ["CAPABILITY"]}]},
        contract,
    )
    assert migrated["either"] == [{"work_classes": ["capability"]}]

    with pytest.raises(ContractMigrationError) as exc_info:
        migrate_contract_payload(
            {
                "schema_version": FOUNDRY_SCHEMA_VERSION,
                "either": [{"work_classes": ["CAPABILITY"]}],
            },
            contract,
        )
    assert exc_info.value.json_path == "either[0].work_classes[0]"


def test_optional_model_still_descends() -> None:
    """`Model | None` is the shape every shipped union-typed child actually has.

    The refusal above must not catch it: `None` reaches no model, so there is exactly
    one reaching arm and one declared type.
    """
    from agent_foundry.models.compat import migrate_contract_payload

    migrated = migrate_contract_payload(
        {"schema_version": "0.1", "either": {"work_classes": ["ADOPTION"]}},
        _holder(_Held | None),
    )
    assert migrated["either"] == {"work_classes": ["adoption"]}


def test_no_shipped_model_declares_a_multi_arm_descendable_union() -> None:
    """Every union-typed child in the repository today is `Model | None`."""
    from agent_foundry.models.compat import _plan_for

    for model in _all_models():
        _plan_for(model)  # raises MigrationPlanError if any field is multi-arm


def test_the_one_classifier_answers_every_shape_precisely() -> None:
    """There is one definition of "descendable", and it is not "mentions a model".

    The `not_reaching` list is the point. A naive "does this annotation mention a
    `BaseModel` anywhere?" answers `True` for `dict[_Held, str]` (model as a *key*,
    never descended) and for `dict[str, Any]` after unwrapping — and a second helper
    written that way is what previously agreed with the plan while disagreeing with
    the walk. Those shapes are listed here so the imprecise answer cannot pass.
    """
    from agent_foundry.models.compat import _descent_route

    reaching = [
        _Held,
        list[_Held],
        _Held | None,
        dict[str, _Held],
        tuple[_Held, ...],
        tuple[str, _Held],
        typing.Sequence[_Held],
        collections.abc.Mapping[str, _Held],
    ]
    not_reaching = [
        str,
        list[str],
        dict[str, typing.Any],
        dict[_Held, str],
        collections.abc.Mapping[_Held, str],
        list[SkillSpec],
        WorkClass,
        None,
    ]
    for annotation in reaching:
        assert _descent_route(annotation) is not None, annotation
    for annotation in not_reaching:
        assert _descent_route(annotation) is None, annotation


@pytest.mark.parametrize("model_slot", [0, 1])
def test_a_heterogeneous_tuple_descends_positionally(model_slot: int) -> None:
    """`tuple[X, Y]` is positional; descending every slot against `X` is wrong.

    One slot is declared `_Held`, the other a free-form mapping whose key collides
    with the migrated vocabulary. Under a non-positional walk the two slots swap
    declared types, and the failure differs by which slot holds the model: with the
    model first, the free-form value is *rewritten*; with it second, the real token is
    *not migrated*. Both orders are covered because both are wrong in different ways.
    """
    from agent_foundry.models.base import VersionedContract
    from agent_foundry.models.compat import migrate_contract_payload

    free_form = {"work_classes": ["CAPABILITY"]}
    held = {"work_classes": ["CAPABILITY"]}
    if model_slot == 0:
        annotation = tuple[_Held, dict[str, typing.Any]]
        payload = [held, free_form]
        expected = [{"work_classes": ["capability"]}, free_form]
    else:
        annotation = tuple[dict[str, typing.Any], _Held]
        payload = [free_form, held]
        expected = [free_form, {"work_classes": ["capability"]}]

    contract = type(
        "_Pair",
        (VersionedContract,),
        {"__annotations__": {"pair": annotation}, "pair": ()},
    )
    migrated = migrate_contract_payload(
        {"schema_version": "0.1", "pair": payload}, contract
    )
    assert migrated["pair"] == expected


def test_a_homogeneous_tuple_still_descends_every_slot() -> None:
    """`tuple[X, ...]` must not be mistaken for a positional pair."""
    from agent_foundry.models.base import VersionedContract
    from agent_foundry.models.compat import migrate_contract_payload

    class _Many(VersionedContract):
        items: tuple[_Held, ...] = ()

    migrated = migrate_contract_payload(
        {
            "schema_version": "0.1",
            "items": [{"work_classes": ["CAPABILITY"]}, {"work_classes": ["ADOPTION"]}],
        },
        _Many,
    )
    assert migrated["items"] == [
        {"work_classes": ["capability"]},
        {"work_classes": ["adoption"]},
    ]


@pytest.mark.parametrize(
    "annotation_factory",
    [
        pytest.param(lambda m: list[m], id="list"),
        pytest.param(lambda m: tuple[m, ...], id="tuple"),
        pytest.param(lambda m: typing.Sequence[m], id="typing.Sequence"),
        pytest.param(lambda m: collections.abc.Sequence[m], id="abc.Sequence"),
        pytest.param(lambda m: dict[str, m], id="dict"),
        pytest.param(lambda m: typing.Mapping[str, m], id="typing.Mapping"),
        pytest.param(lambda m: collections.abc.Mapping[str, m], id="abc.Mapping"),
        pytest.param(lambda m: m | None, id="optional"),
    ],
)
def test_every_container_spelling_reaches_the_model_inside_it(annotation_factory) -> None:
    """Both spellings of every container, so they cannot diverge again."""
    from agent_foundry.models.compat import _descent_route

    assert _descent_route(annotation_factory(SkillTriggers)) is not None


def test_container_spellings_actually_migrate_the_token_underneath() -> None:
    """Behavioural, not only structural: the token inside each container moves."""
    from agent_foundry.models.base import FoundryModel, VersionedContract
    from agent_foundry.models.compat import migrate_contract_payload

    class _Held(FoundryModel):
        work_classes: list[WorkClass] = []

    class _SeqHolder(VersionedContract):
        items: typing.Sequence[_Held] = ()

    class _MapHolder(VersionedContract):
        items: typing.Mapping[str, _Held] = {}

    migrated = migrate_contract_payload(
        {"schema_version": "0.1", "items": [{"work_classes": ["CAPABILITY"]}]},
        _SeqHolder,
    )
    assert migrated["items"][0]["work_classes"] == ["capability"]

    migrated = migrate_contract_payload(
        {"schema_version": "0.1", "items": {"k": {"work_classes": ["ADOPTION"]}}},
        _MapHolder,
    )
    assert migrated["items"]["k"]["work_classes"] == ["adoption"]

    with pytest.raises(ContractMigrationError) as exc_info:
        migrate_contract_payload(
            {
                "schema_version": FOUNDRY_SCHEMA_VERSION,
                "items": [{"work_classes": ["CAPABILITY"]}],
            },
            _SeqHolder,
        )
    assert exc_info.value.json_path == "items[0].work_classes[0]"


def test_planning_refuses_a_model_whose_annotations_are_unresolved() -> None:
    """A plan is cached, so one built from a `ForwardRef` would persist.

    `AdoptionPlanResult` ships incomplete, which is why this is asserted rather than
    assumed: planning resolves first, and refuses if resolution does not complete.
    """
    from agent_foundry.models.base import FoundryModel
    from agent_foundry.models.compat import MigrationPlanError, _plan_for

    class _Unresolvable(FoundryModel):
        later: "NeverDefinedAnywhere" = None  # noqa: F821

    with pytest.raises(MigrationPlanError) as exc_info:
        _plan_for(_Unresolvable)
    assert "unresolved" in str(exc_info.value)


def test_an_incomplete_model_is_resolved_rather_than_planned_blind() -> None:
    """The resolvable case must still work — refusing everything is not the fix."""
    from agent_foundry.models import AdoptionPlanResult
    from agent_foundry.models.compat import _plan_for

    _plan_for(AdoptionPlanResult)
    assert AdoptionPlanResult.__pydantic_complete__


# --- owner-declared fields migration refuses to rewrite ---------------------------


def test_legacy_toolkit_lock_with_a_stale_compat_range_fails_closed() -> None:
    """`foundry_compat` is normative, so migration refuses rather than broadening it.

    A stock v0.1 lock pins `">=0.1,<0.2"`. Bumping its `schema_version` to 0.2 while
    leaving that range would emit an object declaring 0.2 and pinning a range that
    excludes 0.2 — and it would fail far away, at resolve time, complaining about the
    range rather than about the file being an unmigrated v0.1 artifact.
    """
    with pytest.raises(UnmigratableContractError) as exc_info:
        load_yaml(ToolkitLock, (LEGACY_V0_1 / "toolkit_lock.yaml").read_bytes())
    error = exc_info.value
    assert error.contract_name == "ToolkitLock"
    assert error.field_name == "foundry_compat"
    assert error.declared_value == ">=0.1,<0.2"
    assert error.running_version == __version__
    assert error.from_version == "0.1"
    assert error.to_version == FOUNDRY_SCHEMA_VERSION
    message = str(error)
    assert "no migration is provided for foundry_compat" in message.lower()


def test_unmigratable_contract_error_is_a_schema_compatibility_error() -> None:
    assert issubclass(UnmigratableContractError, SchemaCompatibilityError)


def test_a_legacy_lock_whose_range_admits_the_running_version_still_migrates() -> None:
    """The refusal is about a false assertion, not about being old."""
    lock = ToolkitLock.model_validate(
        {
            "schema_version": "0.1",
            "project_name": "p",
            "foundry_compat": ">=0.1,<0.3",
        }
    )
    assert lock.schema_version == FOUNDRY_SCHEMA_VERSION
    assert lock.foundry_compat == ">=0.1,<0.3"


def test_a_current_version_lock_with_a_stale_range_is_not_this_rule_s_business() -> None:
    """No migration happens, so nothing is made self-contradictory here.

    A 0.2 artifact pinning a range that excludes 0.2 was written that way by its owner.
    That is a declaration to argue with at resolve time, not a migration failure, and
    this rule must not quietly take over an unrelated diagnosis.
    """
    lock = ToolkitLock.model_validate(
        {
            "schema_version": FOUNDRY_SCHEMA_VERSION,
            "project_name": "p",
            "foundry_compat": ">=0.1,<0.2",
        }
    )
    assert lock.foundry_compat == ">=0.1,<0.2"


def test_a_malformed_compat_range_is_left_to_its_own_validator() -> None:
    """Migration must not invent a diagnosis it is not the owner of.

    A malformed range is not evaluated at construction time in this repository — it is
    rejected at resolve time by `assert_registry_compat`. Migration must therefore
    neither reject it here (it is not this rule's failure) nor rewrite it, and must
    leave the malformed text intact so the validator that does own it still sees it.
    """
    lock = ToolkitLock.model_validate(
        {
            "schema_version": "0.1",
            "project_name": "p",
            "foundry_compat": ">=0.1garbage",
        }
    )
    assert lock.foundry_compat == ">=0.1garbage"
    assert lock.schema_version == FOUNDRY_SCHEMA_VERSION

    from agent_foundry.toolkit.compat import assert_registry_compat

    with pytest.raises(SchemaCompatibilityError) as exc_info:
        assert_registry_compat(lock.foundry_compat)
    assert not isinstance(exc_info.value, UnmigratableContractError)


def test_the_shipped_registry_range_admits_the_running_version() -> None:
    """The envelope must not claim a runtime that cannot read what it publishes."""
    from agent_foundry.toolkit.builtin_registry import build_default_registry
    from agent_foundry.toolkit.compat import foundry_version_matches_compat

    registry = build_default_registry()
    assert registry.foundry_compat == ">=0.2,<0.3"
    assert foundry_version_matches_compat(registry.foundry_compat)
    assert ToolkitLock.model_fields["foundry_compat"].default == ">=0.2,<0.3"


# --- purity and no-op properties -------------------------------------------------


def test_migration_does_not_mutate_the_caller_input() -> None:
    payload = _canonical_work_item(schema_version="0.1")
    payload["work_class"] = "CAPABILITY"
    payload["dependencies"] = [{"relation": "requires", "target_id": "WI-OTHER"}]
    before = copy.deepcopy(payload)

    migrated = migrate_contract_payload(payload, WorkItemContract)

    assert payload == before
    assert payload["work_class"] == "CAPABILITY"
    assert migrated["work_class"] == "capability"
    assert migrated["schema_version"] == FOUNDRY_SCHEMA_VERSION
    # And the same input twice gives the same output.
    assert migrate_contract_payload(payload, WorkItemContract) == migrated


def test_canonical_payload_is_untouched_by_migration() -> None:
    payload = _canonical_work_item()
    assert migrate_contract_payload(payload, WorkItemContract) is payload


def test_non_mapping_input_passes_through_untouched() -> None:
    """Migration must not invent a diagnosis for input it cannot read; pydantic's own
    error for a non-mapping payload is the useful one."""
    for value in (None, "text", 7, ["a"]):
        assert migrate_contract_payload(value, WorkItemContract) is value
    with pytest.raises(Exception) as exc_info:
        WorkItemContract.model_validate("not a mapping")
    assert not isinstance(exc_info.value, ContractMigrationError)


def test_payload_without_a_readable_schema_version_passes_through() -> None:
    for payload in ({"work_class": "CAPABILITY"}, {"schema_version": "nonsense"}):
        assert migrate_contract_payload(payload, WorkItemContract) is payload


@pytest.mark.parametrize("declared", ["1.0", "0.3"])
def test_version_incompatibility_outranks_token_migration(declared: str) -> None:
    """A payload from an incompatible version is not a migration problem.

    Migration declines to speak: it hands the payload back untouched so the version
    incompatibility — the larger fact — is what gets reported. Claiming the token
    would imply the file could be salvaged by editing one word.
    """
    payload = _canonical_work_item(schema_version=declared)
    payload["work_class"] = "CAPABILITY"
    assert migrate_contract_payload(payload, WorkItemContract) is payload
    with pytest.raises(Exception) as exc_info:
        WorkItemContract.model_validate(payload)
    assert not isinstance(exc_info.value, ContractMigrationError)


def test_canonical_fixtures_declare_the_current_schema_version() -> None:
    """`tests/fixtures/valid/` is the current contract, not a migration input."""
    for path in sorted(CANONICAL.glob("*.yaml")) + sorted(CANONICAL.glob("*.json")):
        declared = [
            line for line in path.read_text(encoding="utf-8").splitlines()
            if "schema_version" in line
        ]
        assert declared, path.name
        assert f'"{FOUNDRY_SCHEMA_VERSION}"' in declared[0], path.name


# --- exhaustiveness: a member added later cannot skip migration coverage ----------


def test_every_work_class_value_is_lowercase_kebab() -> None:
    for member in WorkClass:
        assert member.value == member.value.lower(), member.name
        assert "_" not in member.value, member.name
        assert member.value.replace("-", "").isalnum(), member.name


def _work_class_typed_fields() -> dict[str, set[str]]:
    """Every model field whose declared type is `WorkClass`, or a container of it.

    Reflection over the annotations rather than a hand-written list: the risk this
    guard exists for is a *new* `WorkClass`-typed field being added to some model and
    nobody remembering the migration registry. A list would have to be edited by the
    same person who forgot.

    Returns field name -> the model class names declaring it, so a failure names the
    model that needs registering rather than only the field.
    """
    import importlib
    import pkgutil

    import agent_foundry.models as models_pkg

    found: dict[str, set[str]] = {}
    for module_info in pkgutil.iter_modules(models_pkg.__path__):
        module = importlib.import_module(f"agent_foundry.models.{module_info.name}")
        for attribute_name in dir(module):
            candidate = getattr(module, attribute_name)
            fields = getattr(candidate, "model_fields", None)
            if not isinstance(fields, dict) or getattr(candidate, "__name__", "") != attribute_name:
                continue
            for field_name, field in fields.items():
                if WorkClass in _annotation_types(field.annotation):
                    found.setdefault(field_name, set()).add(candidate.__name__)
    return found


def _annotation_types(annotation: object) -> set[object]:
    """Flatten `WorkClass`, `list[WorkClass]`, `WorkClass | None`, `tuple[WorkClass, ...]`."""
    import typing

    seen: set[object] = set()
    stack = [annotation]
    while stack:
        current = stack.pop()
        if current is None:
            continue
        seen.add(current)
        stack.extend(arg for arg in typing.get_args(current) if arg is not Ellipsis)
    return seen


def test_the_reflection_actually_finds_the_known_work_class_fields() -> None:
    """Guard the guard: a reflection that silently finds nothing proves nothing."""
    found = _work_class_typed_fields()
    assert found.get("work_class"), "reflection found no WorkClass-typed `work_class`"
    assert "WorkItemContract" in found["work_class"]
    assert "SkillTriggers" in found.get("work_classes", set())
    assert "AdoptionGap" in found.get("suggested_work_class", set())


def test_every_work_class_typed_field_is_registered_for_migration() -> None:
    """A new `WorkClass`-typed field must not silently skip migration coverage.

    This is the direction that can actually go wrong. The token map itself is derived
    from the enum, so it cannot disagree with it; what can drift is the set of *field
    names* the walker looks at.
    """
    registered = {migration.field_name for migration in TOKEN_MIGRATIONS}
    unregistered = sorted(set(_work_class_typed_fields()) - registered)
    assert unregistered == [], (
        f"WorkClass-typed field(s) {unregistered} are not in the migration registry in "
        "agent_foundry/models/compat.py, so a legacy token there would raise a generic "
        "enum error instead of migrating or failing closed. Declaring fields: "
        + repr({name: sorted(_work_class_typed_fields()[name]) for name in unregistered})
    )


def test_every_registered_field_name_is_declared_by_a_model_that_carries_it() -> None:
    """The reverse direction: a typo in the registry migrates nothing and fails nothing.

    Checked against the `WorkClass`-typed fields specifically, not against the union of
    every field name in every model — that union is large enough to accept almost any
    string, which is how a vacuous guard is built by accident.
    """
    declared = _work_class_typed_fields()
    for migration in TOKEN_MIGRATIONS:
        assert migration.field_name in declared, (
            f"{migration.field_name!r} is registered for migration but no model declares "
            "a WorkClass-typed field of that name"
        )


def test_registry_reachability_is_recorded_where_it_is_partial() -> None:
    """Two registered sites are unreachable, and the module must say so.

    `AdoptionGap.suggested_work_class` and the `CapabilityUnit.work_class` occurrence
    sit only inside `DecompositionInput`, which is not a `VersionedContract`, so the
    before-validator never runs over them. That is a real coverage gap; this pins the
    fact that it is documented rather than implied to be covered.
    """
    from agent_foundry.models import DecompositionInput
    from agent_foundry.models.base import VersionedContract

    assert not issubclass(DecompositionInput, VersionedContract)
    source = (
        Path(__file__).resolve().parents[1]
        / "src" / "agent_foundry" / "models" / "compat.py"
    ).read_text(encoding="utf-8")
    assert "unreachable" in source, (
        "compat.py must state that suggested_work_class and the CapabilityUnit "
        "occurrence of work_class are registered but not reachable"
    )


def test_an_unreachable_site_really_is_unreachable() -> None:
    """The claim above is asserted as behaviour, not only as prose.

    If `DecompositionInput` ever becomes versioned this fails, which is the prompt to
    delete the caveat rather than let it rot into a false statement.
    """
    from agent_foundry.models import DecompositionInput

    payload = {
        "objective": {"id": "O", "title": "t", "description": "d"},
        "outcomes": [],
        "adoption_gaps": [
            {
                "id": "G",
                "target": "t",
                "action": "HARDEN",
                "rationale": "r",
                "suggested_work_class": "ADOPTION",
            }
        ],
    }
    with pytest.raises(Exception) as exc_info:
        DecompositionInput.model_validate(payload)
    assert not isinstance(exc_info.value, ContractMigrationError)


def test_every_versioned_contract_appears_in_the_compatibility_matrix() -> None:
    """Presence only: a new persisted contract must not slip in without a disposition.

    Deliberately *not* an assertion that each row's behavioural claim is true — that
    would be a second mechanism restating the code, and the delta doc is documentation
    rather than a source of truth anything reads. What it does catch is the failure
    mode documentation actually has: a class is added, nobody records what happens to
    a v0.1 file of it, and the omission is invisible.
    """
    from agent_foundry.models.base import VersionedContract

    def descendants(root: type) -> set[type]:
        found: set[type] = set()
        for child in root.__subclasses__():
            found.add(child)
            found |= descendants(child)
        return found

    matrix = DELTA_DOC.read_text(encoding="utf-8")
    section = matrix[matrix.index("## 3. Serialized-artifact compatibility matrix") :]
    section = section[: section.index("## 3a.")]
    shipped = [
        model
        for model in descendants(VersionedContract)
        if model.__module__.startswith("agent_foundry.")
    ]
    assert len(shipped) >= 19, f"reflection found only {len(shipped)} versioned contracts"
    missing = sorted(
        model.__name__ for model in shipped if f"`{model.__name__}`" not in section
    )
    assert missing == [], (
        f"separately-persisted contract(s) {missing} have no row in the "
        "compatibility matrix of docs/contracts/v0.2-contract-delta.md. Every "
        "VersionedContract needs a recorded disposition for a v0.1 artifact of it."
    )


def test_the_matrix_presence_guard_is_not_vacuous() -> None:
    """The section must actually be found and non-trivial, or the guard proves nothing."""
    matrix = DELTA_DOC.read_text(encoding="utf-8")
    section = matrix[matrix.index("## 3. Serialized-artifact compatibility matrix") :]
    section = section[: section.index("## 3a.")]
    assert section.count("\n|") > 10, "matrix table not found or unexpectedly small"


def test_public_export_surface_records_the_new_names() -> None:
    baseline = json.loads(
        (Path(__file__).resolve().parent / "fixtures" / "models_public_exports.json").read_text()
    )
    for name in (
        "ContractMigrationError",
        "UnmigratableContractError",
        "migrate_contract_payload",
    ):
        assert name in baseline, name
        assert name in models.__all__, name
