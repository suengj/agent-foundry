"""Declarative contract migration and fail-closed compatibility for wire tokens.

A breaking wire change is only honest if it is *versioned*: an artifact written
before the change must keep loading, and an artifact that claims to be written
after the change must not be allowed to carry the old spelling. Both halves live
here.

The registry below is explicit and closed. There is no heuristic, no
case-insensitive fallback, and no "looks close enough" matching: a token is
either a declared legacy spelling of a declared field, or it is not this
module's business and pydantic reports it.

"Declared field" is meant literally, and the traversal is **type-directed** to
keep it so. The walker descends the contract's own `model_fields` annotations,
not the payload's key names, and rewrites a value only where the enclosing model
declares that field as `WorkClass`-typed. Where an annotation does not pin down a
single declared type — a union naming two different nested models, or one with more
than one arm that reaches a model — the walker refuses to plan the field at all
rather than picking one. Descending against a guessed type rewrites data that type
may not own, and skipping the arm not taken under-migrates the payloads that used it. A key-name match at arbitrary depth
would reach into free-form data: `IntegrationSpec.adapter_options` is an
adapter-owned namespace, and a provider that happens to use the key
`work_class` there must get its value back unchanged. Core rewriting a
provider's option value is the opposite of provider-neutral, and it would be an
unversioned compatibility break riding along with the versioned one.

The same traversal supplies the nested-contract boundary: a field whose declared
type is itself a `VersionedContract` is not descended into, because it carries
its own `schema_version` and migrates against that when pydantic validates it.

Placement: `VersionedContract` runs `migrate_contract_payload` as a
`model_validator(mode="before")`, so every separately-persisted contract gets it
on every entry path — `model_validate`, and therefore `load_yaml`/`load_json`
in `agent_foundry.models.io`, which both funnel into `model_validate`.
"""

from __future__ import annotations

import collections.abc as _abc
import types as _types
import typing
from functools import lru_cache
from typing import Any, Mapping, NamedTuple, Sequence

from pydantic import BaseModel

from agent_foundry.models.base import (
    FOUNDRY_SCHEMA_VERSION,
    FoundryModelError,
    SchemaCompatibilityError,
    VersionedContract,
    parse_schema_version,
)
from agent_foundry.models.common import WorkClass

__all__ = [
    "ContractMigrationError",
    "TOKEN_MIGRATIONS",
    "TokenMigration",
    "UnmigratableContractError",
    "migrate_contract_payload",
]

#: Fields carrying an owner-declared normative compatibility assertion that this
#: module refuses to rewrite. Migrating an artifact that pins one of these to a range
#: excluding the running version fails closed rather than being silently broadened.
UNMIGRATABLE_DECLARED_FIELDS: tuple[str, ...] = ("foundry_compat",)


class ContractMigrationError(SchemaCompatibilityError):
    """Raised when a payload carries a legacy token it is too new to be allowed.

    A `SchemaCompatibilityError` rather than a new root: this *is* a schema
    compatibility failure, and existing handlers that already treat schema
    incompatibility as fatal must not start letting it through.
    """

    def __init__(
        self,
        *,
        contract_name: str,
        json_path: str,
        legacy_token: str,
        canonical_token: str,
        changed_in: str,
        declared_version: str,
    ) -> None:
        self.contract_name = contract_name
        self.json_path = json_path
        self.legacy_token = legacy_token
        self.canonical_token = canonical_token
        self.changed_in = changed_in
        self.declared_version = declared_version
        super().__init__(
            f"{contract_name}: {json_path} carries legacy token {legacy_token!r}, "
            f"which was replaced by {canonical_token!r} in schema_version {changed_in}. "
            f"The payload declares schema_version {declared_version}, at or after that "
            f"change, so the legacy token is not accepted. Either declare an older "
            f"schema_version so the payload is migrated, or write {canonical_token!r}."
        )


class UnmigratableContractError(SchemaCompatibilityError):
    """Raised when migrating an artifact would leave it self-contradictory.

    `foundry_compat` is an owner-declared *normative* compatibility assertion, not a
    derived value. Migration will not broaden it: inferring a wider range than the
    owner wrote would widen a compatibility authority on the strength of a guess,
    which is exactly what this repository forbids.

    So the artifact is refused here, at load, where the diagnosis is available.
    Letting it through produces an object declaring schema 0.2 while pinning a range
    that excludes 0.2 — a contradiction that surfaces much later, during toolkit
    resolution, as a complaint about the range rather than about the artifact being
    an unmigrated v0.1 file.
    """

    def __init__(
        self,
        *,
        contract_name: str,
        field_name: str,
        declared_value: str,
        running_version: str,
        from_version: str,
        to_version: str,
    ) -> None:
        self.contract_name = contract_name
        self.field_name = field_name
        self.declared_value = declared_value
        self.running_version = running_version
        self.from_version = from_version
        self.to_version = to_version
        super().__init__(
            f"{contract_name}: cannot migrate schema_version {from_version} -> "
            f"{to_version} because {field_name} declares {declared_value!r}, which "
            f"excludes the running package version {running_version}. No migration is "
            f"provided for {field_name}: it is an owner-declared compatibility "
            f"assertion, and widening it would be an inference, not a migration. "
            f"Re-declare {field_name} for the {to_version} line, or read this artifact "
            f"with a package version its range admits."
        )


class MigrationPlanError(FoundryModelError):
    """Raised when a model's field declarations cannot be planned unambiguously.

    This is a defect in the *contract definitions*, not in any artifact, so it is a
    `FoundryModelError` rather than a schema-compatibility error and it fires the
    moment the model is first planned rather than depending on a payload reaching the
    ambiguous field.

    It is loud on purpose. The alternative to raising is guessing which declared type
    a payload subtree is, and a wrong guess rewrites data the guessed-at model does
    not own — the same silent corruption that scoping the traversal by declared type
    was meant to remove. Refusing to plan is the fail-closed answer.
    """


class TokenMigration:
    """One field's legacy-to-canonical token map, and when it changed.

    `field_name` is matched wherever it appears in the payload tree, at any depth,
    for both scalar and sequence-valued occurrences. Contracts nest (a `WorkPlan`
    carries `WorkItemContract`s; a `SkillSpec` carries its `triggers`), so a
    top-level-only rewrite would migrate the outer artifact and leave the inner
    one broken.
    """

    __slots__ = ("field_name", "changed_in", "legacy_to_canonical")

    def __init__(
        self,
        *,
        field_name: str,
        changed_in: str,
        legacy_to_canonical: Mapping[str, str],
    ) -> None:
        self.field_name = field_name
        self.changed_in = changed_in
        self.legacy_to_canonical = dict(legacy_to_canonical)


#: Legacy spellings of `WorkClass`, which serialized SCREAMING_SNAKE before 0.2.
#: Derived from the member names so a member added later cannot be silently
#: omitted here; `tests/test_contract_compat_v02.py` asserts the coverage.
WORK_CLASS_LEGACY_TOKENS: dict[str, str] = {member.name: member.value for member in WorkClass}

#: Every field name whose declared type is `WorkClass` (or a sequence of it), across
#: the model modules. Registered together so a `WorkClass`-typed field added later
#: cannot silently skip migration; `tests/test_contract_compat_v02.py` discovers the
#: annotated fields by reflection and asserts this tuple covers them.
#:
#: **Reachability is not uniform, and this is deliberate.** The migration runs as a
#: `VersionedContract` before-validator, so a field only migrates when it sits inside
#: a contract that carries `schema_version`:
#:
#: * `work_class` on `WorkItemContract` — reachable (a versioned contract).
#: * `work_classes` on `SkillTriggers` — reachable (nested under `SkillSpec`).
#: * `suggested_work_class` on `AdoptionGap` — **registered but currently
#:   unreachable.** `AdoptionGap` is only ever nested in `DecompositionInput`, a plain
#:   `FoundryModel` with no `schema_version`, so no before-validator runs and a legacy
#:   token there produces a generic pydantic enum error, not a migration.
#: * `work_class` on `CapabilityUnit` — same: reachable via `WorkItemContract`, but the
#:   `CapabilityUnit` occurrence is only nested in `DecompositionInput` and is
#:   therefore unreachable at that site.
#:
#: They stay registered so that the day either container becomes a versioned contract,
#: migration is already correct rather than newly missing. Making them reachable now
#: would mean versioning a decomposition *input*, which is a contract decision this
#: slice did not take.
_WORK_CLASS_FIELDS = (
    "work_class",
    "suggested_work_class",
    "work_classes",
)

TOKEN_MIGRATIONS: tuple[TokenMigration, ...] = tuple(
    TokenMigration(
        field_name=field_name,
        changed_in="0.2",
        legacy_to_canonical=WORK_CLASS_LEGACY_TOKENS,
    )
    for field_name in _WORK_CLASS_FIELDS
)


_MIGRATIONS_BY_FIELD: dict[str, TokenMigration] = {
    migration.field_name: migration for migration in TOKEN_MIGRATIONS
}


def _annotation_types(annotation: Any) -> set[Any]:
    """Flatten an annotation into every type mentioned anywhere inside it.

    `list[WorkClass]`, `WorkClass | None` and `tuple[WorkClass, ...]` all have to
    answer "is this field WorkClass-typed?" the same way.
    """
    seen: set[Any] = set()
    stack = [annotation]
    while stack:
        current = stack.pop()
        if current is None or current is Ellipsis:
            continue
        try:
            seen.add(current)
        except TypeError:  # pragma: no cover - unhashable annotation
            continue
        stack.extend(typing.get_args(current))
    return seen


class _MigrationPlan(NamedTuple):
    """What migration may touch on one model class, derived from its own fields.

    `tokens` are the fields this model declares as `WorkClass`-typed *and* that the
    registry knows about. `children` are the fields whose declared type contains a
    nested non-versioned model worth descending into. Everything else — every
    free-form mapping, every plain string, every versioned sub-contract — is absent,
    and absent means untouched.
    """

    tokens: Mapping[str, TokenMigration]
    children: Mapping[str, Any]


def _nested_model_candidates(annotation: Any) -> tuple[type[BaseModel], ...]:
    """Every distinct non-versioned model an annotation mentions, in a stable order.

    Versioned contracts are excluded: they carry their own `schema_version` and
    migrate against it when pydantic descends into them.
    """
    found: list[type[BaseModel]] = []
    for candidate in _annotation_types(annotation):
        if (
            isinstance(candidate, type)
            and issubclass(candidate, BaseModel)
            and not issubclass(candidate, VersionedContract)
            and candidate not in found
        ):
            found.append(candidate)
    return tuple(sorted(found, key=lambda model: model.__name__))


@lru_cache(maxsize=None)
def _plan_for(contract: type[BaseModel]) -> _MigrationPlan:
    if not getattr(contract, "__pydantic_complete__", True):
        # A model still carrying an unresolved `ForwardRef` would be planned from the
        # ref rather than the type, and the plan is cached — so a wrong plan built
        # once would persist. Resolve first, and refuse rather than plan blind.
        contract.model_rebuild(raise_errors=False)
    if not getattr(contract, "__pydantic_complete__", True):
        raise MigrationPlanError(
            f"{contract.__name__}: cannot plan contract migration because its field "
            "annotations are unresolved (model_rebuild did not complete). Migration "
            "reads declared types, so an unresolved annotation would be planned as a "
            "forward reference and the wrong plan cached."
        )

    tokens: dict[str, TokenMigration] = {}
    children: dict[str, Any] = {}
    for field_name, field in contract.model_fields.items():
        annotation = field.annotation
        mentioned = _annotation_types(annotation)
        if WorkClass in mentioned:
            migration = _MIGRATIONS_BY_FIELD.get(field_name)
            if migration is not None:
                tokens[field_name] = migration
            # A WorkClass-typed field that is *not* registered is left alone here;
            # `tests/test_contract_compat_v02.py` fails if one ever exists, so this
            # cannot become a silent gap.
            continue
        candidates = _nested_model_candidates(annotation)
        if len(candidates) > 1:
            raise MigrationPlanError(
                f"{contract.__name__}.{field_name}: annotation {annotation!r} mentions "
                f"more than one non-versioned model "
                f"({', '.join(model.__name__ for model in candidates)}). Migration "
                "descends by declared type, and there is no declared type here — "
                "picking one would rewrite a payload against a model that may not own "
                "it. Give the field a single nested model type, wrap the alternatives "
                "in a versioned contract, or extend agent_foundry.models.compat to "
                "discriminate them explicitly."
            )
        if _descent_route(annotation) is not None:
            children[field_name] = annotation
    return _MigrationPlan(tokens, children)


def _migrate_value(
    value: Any,
    *,
    migration: TokenMigration,
    contract_name: str,
    json_path: str,
    declared_version: str,
    rewrite: bool,
) -> Any:
    """Apply one field's token map to a scalar or a sequence of scalars."""
    if isinstance(value, str):
        canonical = migration.legacy_to_canonical.get(value)
        if canonical is None or canonical == value:
            return value
        if not rewrite:
            raise ContractMigrationError(
                contract_name=contract_name,
                json_path=json_path,
                legacy_token=value,
                canonical_token=canonical,
                changed_in=migration.changed_in,
                declared_version=declared_version,
            )
        return canonical
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [
            _migrate_value(
                item,
                migration=migration,
                contract_name=contract_name,
                json_path=f"{json_path}[{index}]",
                declared_version=declared_version,
                rewrite=rewrite,
            )
            for index, item in enumerate(value)
        ]
    # Anything else (None, int, a nested mapping) is not a token this registry
    # knows how to speak about. Leave it for pydantic to reject or accept.
    return value


def _walk_model(
    node: Any,
    contract: type[BaseModel],
    *,
    contract_name: str,
    json_path: str,
    declared: tuple[int, int],
    declared_version: str,
) -> Any:
    """Return a migrated copy of one model-shaped mapping, guided by its own fields.

    A key the model does not declare is copied through untouched. So is every field
    the plan does not name — free-form mappings, plain scalars, and nested versioned
    contracts alike. The input is never mutated.
    """
    if not isinstance(node, Mapping):
        return node
    plan = _plan_for(contract)
    migrated: dict[Any, Any] = {}
    for key, child in node.items():
        child_path = f"{json_path}.{key}" if json_path else str(key)
        migration = plan.tokens.get(key) if isinstance(key, str) else None
        if migration is not None:
            migrated[key] = _migrate_value(
                child,
                migration=migration,
                contract_name=contract_name,
                json_path=child_path,
                declared_version=declared_version,
                rewrite=declared < parse_schema_version(migration.changed_in),
            )
            continue
        annotation = plan.children.get(key) if isinstance(key, str) else None
        if annotation is not None:
            migrated[key] = _descend(
                child,
                annotation,
                contract_name=contract_name,
                json_path=child_path,
                declared=declared,
                declared_version=declared_version,
            )
            continue
        migrated[key] = child
    return migrated


def _origin_kind(origin: Any) -> str | None:
    """Classify a generic origin as a mapping, a collection, or neither.

    Compared against `collections.abc`, not the `typing` aliases. `typing.get_origin`
    normalises `Sequence[X]` to `collections.abc.Sequence` and `Mapping[K, V]` to
    `collections.abc.Mapping`, so an identity test against `typing.Sequence` /
    `typing.Mapping` silently misses those spellings — the field is admitted to the
    plan as descendable and then never descended, which is the plan/descent
    disagreement the structural test exists to prevent.
    """
    if not isinstance(origin, type):
        return None
    if issubclass(origin, _abc.Mapping):
        return "mapping"
    if issubclass(origin, (_abc.Sequence, _abc.Set)) and not issubclass(
        origin, (str, bytes)
    ):
        return "collection"
    return None


class _DescentRoute(NamedTuple):
    """The single way `_descend` may follow one annotation into a payload.

    `kind` says which branch applies; `annotation` is the concrete, union-free
    annotation that branch operates on, so a union collapses to the arm actually
    taken *here* rather than being re-resolved during descent.
    """

    kind: str  # "model" | "collection" | "mapping"
    annotation: Any


def _descent_route(annotation: Any) -> _DescentRoute | None:
    """The one route this annotation offers into a nested model, or `None`.

    This is the single definition of "descendable" in the module. `_plan_for` uses it
    to decide whether a field is a child, and `_descend` uses it to decide what to do.
    They cannot disagree, because there is nothing left to disagree about: the
    plan/descent split that let a union-shaped field be registered and then never
    walked came from two functions re-deriving the same classification from
    `_descend`'s branch structure. There is deliberately no second "is this
    descendable?" helper — a previous one existed only for a test to call, agreed with
    the plan, and disagreed with the walk.

    A route exists only when a model is genuinely reachable. `list[str]` and
    `dict[str, Any]` — the latter being what `FreeFormMapping` reduces to — reach
    nothing and return `None`, so free-form data stays out of the plan entirely.

    A union with more than one arm that reaches a model raises rather than choosing.
    `Model | None` is unaffected, since `None` reaches nothing; what is refused is the
    one-or-many idiom `list[Model] | Model`, where there is no declared type to
    descend against and picking an arm would under-migrate or corrupt depending on
    declaration order.
    """
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        if issubclass(annotation, VersionedContract):
            return None
        return _DescentRoute("model", annotation)

    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)

    if origin in (typing.Union, getattr(_types, "UnionType", typing.Union)) and args:
        routed = [
            arg
            for arg in args
            if arg is not type(None) and _descent_route(arg) is not None
        ]
        if len(routed) > 1:
            raise MigrationPlanError(
                f"annotation {annotation!r} has more than one arm that reaches a "
                f"nested model ({', '.join(repr(arm) for arm in routed)}). Migration "
                "descends by declared type, and a union of descendable shapes names "
                "no single one — following either arm would migrate some payloads and "
                "silently skip others depending on which arm was written first. "
                "Declare one shape, or wrap the alternatives in a versioned contract."
            )
        return _descent_route(routed[0]) if routed else None

    kind = _origin_kind(origin)
    if kind == "mapping" and len(args) > 1:
        return _DescentRoute("mapping", annotation) if _descent_route(args[1]) else None
    if kind == "collection" and args:
        reaching = any(
            _descent_route(arg) is not None for arg in args if arg is not Ellipsis
        )
        return _DescentRoute("collection", annotation) if reaching else None
    return None


def _descend(
    value: Any,
    annotation: Any,
    *,
    contract_name: str,
    json_path: str,
    declared: tuple[int, int],
    declared_version: str,
) -> Any:
    """Follow one declared annotation into the payload beneath it.

    Containers are unwrapped by their *declared* element type, never by inspecting
    what the payload happens to hold, and the route is taken from `_descent_route` so
    that what is descended is exactly what the plan registered.
    """
    route = _descent_route(annotation)
    if route is None:
        return value

    if route.kind == "model":
        return _walk_model(
            value,
            route.annotation,
            contract_name=contract_name,
            json_path=json_path,
            declared=declared,
            declared_version=declared_version,
        )

    args = typing.get_args(route.annotation)

    if route.kind == "mapping":
        if not isinstance(value, Mapping):
            return value
        element = args[1]
        return {
            key: _descend(
                item,
                element,
                contract_name=contract_name,
                json_path=f"{json_path}.{key}",
                declared=declared,
                declared_version=declared_version,
            )
            for key, item in value.items()
        }

    # route.kind == "collection"
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return value
    # `tuple[X, Y]` is positional; `tuple[X, ...]`, `list[X]` and every set form are
    # homogeneous. Descending a heterogeneous tuple against args[0] would be the same
    # category of wrong-type descent an ambiguous union is refused for.
    positional = (
        typing.get_origin(route.annotation) is tuple
        and len(args) > 1
        and args[1] is not Ellipsis
    )
    return [
        _descend(
            item,
            args[index] if positional and index < len(args) else args[0],
            contract_name=contract_name,
            json_path=f"{json_path}[{index}]",
            declared=declared,
            declared_version=declared_version,
        )
        for index, item in enumerate(value)
    ]


def _reject_unmigratable_declarations(
    payload: Mapping[str, Any],
    *,
    contract_name: str,
    from_version: str,
    to_version: str,
) -> None:
    """Refuse to migrate an artifact whose own compatibility range would then be false.

    Imported lazily and locally: the compat-expression evaluator lives in
    `agent_foundry.toolkit.compat` today, which makes this a models -> toolkit
    reference. It is deliberately confined to this one call so nothing is coupled at
    import time; relocating that evaluator under `models/` is a separate decision.
    """
    from agent_foundry import __version__
    from agent_foundry.toolkit.compat import (
        CompatExpressionError,
        foundry_version_matches_compat,
    )

    for field_name in UNMIGRATABLE_DECLARED_FIELDS:
        declared = payload.get(field_name)
        if not isinstance(declared, str):
            continue
        try:
            admits_running_version = foundry_version_matches_compat(declared)
        except CompatExpressionError:
            # A malformed range is not this module's diagnosis to make; the
            # existing compat validator owns that error.
            continue
        if admits_running_version:
            continue
        raise UnmigratableContractError(
            contract_name=contract_name,
            field_name=field_name,
            declared_value=declared,
            running_version=__version__,
            from_version=from_version,
            to_version=to_version,
        )


def migrate_contract_payload(payload: Any, contract: type[BaseModel]) -> Any:
    """Migrate legacy wire tokens in a raw parsed payload of `contract`.

    `contract` is the model class the payload is being validated as. It is required,
    not optional: the traversal is type-directed, and without the declaring type
    there is no way to tell a declared `work_class` field from a same-named key
    inside somebody's free-form adapter options.

    Behaviour, by the `schema_version` the payload declares:

    * **older than the version a token changed in** — legacy tokens are rewritten
      to their canonical spelling and the payload's declared `schema_version` is
      raised to `FOUNDRY_SCHEMA_VERSION`. A migrated artifact *is* a
      current-version artifact; leaving it declaring the old version would make
      the next dump self-contradictory.
    * **at or newer than that version** — a legacy token is a contradiction, not
      an old file, and raises `ContractMigrationError`.

    Anything that is not a mapping, that declares no `schema_version`, that
    declares an unparseable one, or that declares a version already incompatible
    on MAJOR/MINOR grounds is returned untouched, so the caller's own error
    (pydantic's, or `validate_schema_compatibility`'s) is the one reported. This
    module never invents a diagnosis for a payload it cannot read.

    A payload that would migrate but declares a field in
    `UNMIGRATABLE_DECLARED_FIELDS` excluding the running package version raises
    `UnmigratableContractError` instead: migration will not silently broaden an
    owner-declared compatibility assertion.

    The input is never mutated; a migrated payload is a new tree.
    """
    if not isinstance(payload, Mapping):
        return payload
    if not (isinstance(contract, type) and issubclass(contract, BaseModel)):
        return payload
    contract_name = contract.__name__

    declared_version = payload.get("schema_version")
    if not isinstance(declared_version, str):
        return payload
    try:
        declared = parse_schema_version(declared_version)
        supported = parse_schema_version(FOUNDRY_SCHEMA_VERSION)
    except ValueError:
        return payload
    if declared[0] != supported[0] or declared[1] > supported[1]:
        # Already incompatible on version grounds; that is the honest failure.
        return payload

    # Each registry entry decides rewrite-vs-fail against its own `changed_in`, so a
    # later entry landing in a different schema version keeps its own boundary.
    upgraded = any(
        declared < parse_schema_version(migration.changed_in)
        for migration in TOKEN_MIGRATIONS
    )
    result = _walk_model(
        payload,
        contract,
        contract_name=contract_name,
        json_path="",
        declared=declared,
        declared_version=declared_version,
    )

    if upgraded:
        _reject_unmigratable_declarations(
            payload,
            contract_name=contract_name,
            from_version=declared_version,
            to_version=FOUNDRY_SCHEMA_VERSION,
        )

    if not upgraded:
        # No migration applied: hand back the original object so a canonical
        # payload is a genuine no-op rather than a silently rebuilt copy.
        return payload

    migrated = dict(result)
    migrated["schema_version"] = FOUNDRY_SCHEMA_VERSION
    return migrated
