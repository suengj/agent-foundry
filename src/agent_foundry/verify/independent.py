"""Primitives re-derived for validation, independent of the code that produces artifacts.

Every helper here restates a property from the durable contract in
`docs/foundry/`, not from the implementation that computes it. That is the whole
point: a validator built on `compile.authority` or `toolkit.ceiling` agrees with a
wrong compiler by construction, which is what AF6 was blocked for twice.

Two rules hold for this module:

1. It must not import from `agent_foundry.compile`, `agent_foundry.toolkit`,
   `agent_foundry.work`, `agent_foundry.adopt`, or `agent_foundry.inspect`. A test
   enforces this by reading the import graph, so the rule survives a refactor.
2. Where a second derivation is impossible, the caller says so out loud rather than
   quietly importing the original.

A second implementation that agrees is evidence. The same implementation calling
itself is not.
"""

from __future__ import annotations

import ntpath
import posixpath
from typing import TYPE_CHECKING

from agent_foundry.models.common import (
    ValidationOutcome,
    EvidenceState,
    ExternalEffectClass,
    IntegrationHealthState,
)

if TYPE_CHECKING:  # pragma: no cover - import cycle avoidance only
    from agent_foundry.models.verification import ValidationFinding, ValidationReport

# Ascending authority. Ordered from the contract's own progression (read, then
# repository, then shared services, then data, then live runtime, then publication),
# not copied from a rank table elsewhere in the package.
EXTERNAL_EFFECT_ASCENDING: tuple[ExternalEffectClass, ...] = (
    ExternalEffectClass.READ_ONLY,
    ExternalEffectClass.REPOSITORY_WRITE,
    ExternalEffectClass.SHARED_SERVICE_WRITE,
    ExternalEffectClass.DATA_MUTATION,
    ExternalEffectClass.RUNTIME_MUTATION,
    ExternalEffectClass.PUBLICATION,
)

UNDECLARED_BOUND_RANK = len(EXTERNAL_EFFECT_ASCENDING)
"""Rank of an undeclared *requirement*.

A component whose required effect is unknown is treated as demanding more than any
declared level, so an unknown requirement can never slip under a ceiling.
"""


def effect_rank(effect: ExternalEffectClass | str | None) -> int:
    """Position of an external-effect class, with anything unrecognised ranking above all.

    Total by construction. A value that names no effect class — which is what a
    forged or drifted artifact carries — ranks above every declared level rather than
    raising `ValueError` from `tuple.index`. An exception is not a fail-closed
    verdict: it aborts the caller and records nothing about why the artifact was
    rejected, so the caller cannot report it. Callers still scan the vocabulary first
    and emit a finding; this is the backstop that keeps them from crashing if one
    forgets.
    """
    if effect is None:
        return UNDECLARED_BOUND_RANK
    value = getattr(effect, "value", effect)
    for index, member in enumerate(EXTERNAL_EFFECT_ASCENDING):
        if member.value == value:
            return index
    return UNDECLARED_BOUND_RANK


def exceeds(effect: ExternalEffectClass | None, ceiling: ExternalEffectClass | None) -> bool:
    """True when `effect` demands more authority than `ceiling` grants.

    An undeclared ceiling grants nothing above read-only: the project has not said
    it may write, and silence is not permission.
    """
    ceiling_rank = 0 if ceiling is None else effect_rank(ceiling)
    return effect_rank(effect) > ceiling_rank


def declared_ceiling(effect: ExternalEffectClass | None) -> ExternalEffectClass:
    """The authority a declaration actually grants; silence grants read-only."""
    return ExternalEffectClass.READ_ONLY if effect is None else effect


def tightest(*bounds: ExternalEffectClass | None) -> ExternalEffectClass:
    """Lowest authority among the supplied bounds, treating silence as read-only."""
    resolved = [declared_ceiling(bound) for bound in bounds]
    if not resolved:
        return ExternalEffectClass.READ_ONLY
    return min(resolved, key=effect_rank)


def normalize_repository_path(raw: str) -> str | None:
    """Resolve a repository-relative write bound, or None when it bounds nothing.

    `None` means "grants no path". A bound that resolves to the repository root, an
    absolute path, a drive-rooted or UNC path, a URL-shaped string, or anything that
    escapes the root all return `None` rather than a bound that would compare
    favourably by text.

    Derived by delegating resolution to `posixpath.normpath` and then testing the
    result, which is a different construction from walking segments by hand.
    """
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    # A Windows separator cannot appear in a POSIX repository-relative bound; folding
    # it here means a drive- or UNC-rooted path is recognised below instead of being
    # treated as one long directory name.
    text = text.replace("\\", "/")
    if ntpath.splitdrive(text)[0]:
        return None
    head = text.split("/", 1)[0]
    if ":" in head:
        # "C:", "http:" and anything else scheme-shaped is not repository-relative.
        return None
    normalized = posixpath.normpath(text)
    if posixpath.isabs(normalized):
        return None
    if normalized == "." or normalized == "..":
        return None
    if normalized.startswith("../"):
        return None
    return normalized


def path_within(bound: str, candidate: str) -> bool:
    """True when `candidate` resolves inside (or equal to) `bound`.

    Both sides are resolved first. An unusable bound contains nothing, and an
    unusable candidate is inside nothing.
    """
    bound_path = normalize_repository_path(bound)
    candidate_path = normalize_repository_path(candidate)
    if bound_path is None or candidate_path is None:
        return False
    if candidate_path == bound_path:
        return True
    return candidate_path.startswith(f"{bound_path}/")


def contained_in_any(candidate: str, bounds: list[str]) -> bool:
    """True when at least one bound contains the candidate path."""
    return any(path_within(bound, candidate) for bound in bounds)


def parse_major_minor(version: str) -> tuple[int, int] | None:
    """Parse a MAJOR.MINOR schema version, or None when it is not one."""
    if not isinstance(version, str):
        return None
    parts = version.strip().split(".")
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def parse_release_version(version: str) -> tuple[int, int] | None:
    """Parse the MAJOR.MINOR prefix of a package version such as `0.1.0.dev0`."""
    if not isinstance(version, str):
        return None
    parts = version.strip().split(".")
    if len(parts) < 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def compat_clause_satisfied(clause: str, current: tuple[int, int]) -> bool | None:
    """Evaluate one `>=0.1` style clause, or None when it cannot be parsed."""
    text = clause.strip()
    for operator in (">=", "<=", "==", ">", "<"):
        if text.startswith(operator):
            target = parse_release_version(text[len(operator) :])
            if target is None:
                return None
            if operator == ">=":
                return current >= target
            if operator == "<=":
                return current <= target
            if operator == "==":
                return current == target
            if operator == ">":
                return current > target
            return current < target
    return None


# Health progression from docs/foundry/04 §12. DEGRADED is deliberately outside the
# ladder: it is a reachable operating state, not a rung, and only a requirement of
# HEALTHY may accept it.
HEALTH_LADDER: tuple[IntegrationHealthState, ...] = (
    IntegrationHealthState.DESIRED,
    IntegrationHealthState.AVAILABLE,
    IntegrationHealthState.CONFIGURED,
    IntegrationHealthState.AUTHENTICATED,
    IntegrationHealthState.AUTHORIZED,
    IntegrationHealthState.HEALTHY,
)

AUTHENTICATED_STATES: frozenset[IntegrationHealthState] = frozenset(
    {
        IntegrationHealthState.AUTHENTICATED,
        IntegrationHealthState.AUTHORIZED,
        IntegrationHealthState.HEALTHY,
        IntegrationHealthState.DEGRADED,
    }
)
"""States that positively evidence a completed authentication.

DEGRADED belongs here: a degraded integration is one we are talking to. DESIRED,
AVAILABLE, CONFIGURED and UNAVAILABLE do not, whatever credentials are declared.
"""


def _health_member(state: IntegrationHealthState | str | None) -> IntegrationHealthState | None:
    """Resolve a health value to a known member, or None when it names none."""
    if state is None:
        return None
    if isinstance(state, IntegrationHealthState):
        return state
    for member in IntegrationHealthState:
        if member.value == state:
            return member
    return None


def health_satisfies(
    actual: IntegrationHealthState | str | None,
    required: IntegrationHealthState | str,
) -> bool:
    """True when an observed state meets a required one.

    `None` — no observation at all — satisfies nothing. Unobserved is not healthy,
    and this function is the place that refuses to blur the two. A value that names
    no health state satisfies nothing either, and returns False rather than raising
    from `tuple.index`.
    """
    actual = _health_member(actual)
    required_member = _health_member(required)
    if actual is None or required_member is None:
        return False
    required = required_member
    if actual == IntegrationHealthState.UNAVAILABLE:
        return False
    if actual == IntegrationHealthState.DEGRADED:
        # A degraded integration is reachable and authorized but not fully healthy;
        # it may stand in for HEALTHY, which admits degradation, and for anything
        # below AUTHORIZED, but it is not evidence of a stricter requirement.
        return required in {IntegrationHealthState.HEALTHY, *HEALTH_LADDER[:5]}
    if required == IntegrationHealthState.DEGRADED:
        return actual == IntegrationHealthState.DEGRADED
    return HEALTH_LADDER.index(actual) >= HEALTH_LADDER.index(required)


def authentication_evidenced(actual: IntegrationHealthState | str | None) -> bool:
    """True when the observed state is positive evidence of authentication.

    An unrecognised value evidences nothing, so it resolves to False rather than
    comparing a bare string against a set of members and quietly missing.
    """
    member = _health_member(actual)
    return member is not None and member in AUTHENTICATED_STATES


EVIDENCE_STATE_PROGRESSION: tuple[EvidenceState, ...] = (
    EvidenceState.IMPLEMENTED,
    EvidenceState.VALIDATED,
    EvidenceState.REVIEWED,
    EvidenceState.MERGED_INTEGRATED,
    EvidenceState.SYSTEM_VERIFIED,
    EvidenceState.RUNTIME_APPLIED,
    EvidenceState.RUNTIME_VERIFIED,
    EvidenceState.USER_ACCEPTED,
)
"""Ordered evidence progression from docs/foundry/06 §4.

`NOT_REQUIRED` is absent on purpose: it is an exemption from the ladder, not a rung
on it, and giving it a position would let "exempt" out-rank "proven".
"""

EXEMPTION_MARKER = "NOT_REQUIRED"
"""The one evidence-state name that is a marker rather than a rung.

Spelled once here so both halves of the partition check agree on what it means, and
so neither half has to special-case it from memory.
"""


# --- rules re-derived from the durable contract, not from the producer ---------
#
# The two rules below are enforced by pydantic model validators on `RunFinding` and
# `ExecutionReceipt`. Those model validators are *producers*: they decide whether an
# artifact may be constructed at all. Calling their helper from here would put a
# wrong rule and its purported validator in agreement — the AF6 failure mode, one
# layer down. So each is restated from the contract text and evaluated differently.


def contract_digest(model: object) -> str:
    """Content digest of a contract, recomputed for validation.

    Deliberately not shared with `verify.receipt.artifact_digest`, which is what a
    receipt producer uses to *stamp* a digest. Two separate call sites mean
    neutralizing the stamping function leaves this recomputation intact, so a
    receipt naming the wrong artifact is still caught.

    Both wrap the same deterministic serializer, and that is the honest limit of the
    check: it binds a receipt to the artifact handed in for review, and proves
    nothing about whether the serializer is correct.
    """
    import hashlib

    from agent_foundry.models.io import dump_json

    return hashlib.sha256(dump_json(model)).hexdigest()


# docs/foundry/06 §9 gives each disposition a different obligation:
#
#   BLOCKER        current contract is not satisfied  → repair in current scope
#   RESIDUAL       bounded weakness after acceptance  → create finite follow-up work
#   HYPOTHESIS     requires future/runtime evidence   → record falsifiable prediction
#                                                       and evidence condition
#   HUMAN_REQUIRED reserved authority / open choice   → minimal escalation
#
# Read as a table of "which fields must be present", the obligations become data.
# Evaluating a table is a different construction from the producer's branch-per-
# disposition chain: adding a disposition without an entry here is a visible gap
# rather than a silently unchecked case.
DISPOSITION_REQUIRED_FIELDS: dict[str, tuple[tuple[str, str], ...]] = {
    "BLOCKER": (("evidence_refs", "at least one evidence_ref"),),
    "RESIDUAL": (("follow_up_work_ref", "follow_up_work_ref"),),
    "HYPOTHESIS": (
        ("falsifiable_prediction", "falsifiable_prediction"),
        ("evidence_condition", "evidence_condition"),
    ),
    "HUMAN_REQUIRED": (("escalation_reason", "escalation_reason"),),
}


def finding_obligation_violations(finding: dict[str, object], *, label: str) -> list[str]:
    """Obligations a dispositioned finding owes, read off a serialized payload.

    Takes the raw mapping rather than a constructed object, so a finding that never
    passed through model validation — loaded from a file, hand-written, or built with
    `model_construct` — is examined on the same terms.

    An unrecognised disposition is a violation rather than a pass: a finding whose
    disposition this layer cannot place has no obligations it can be shown to meet.
    """
    disposition = str(finding.get("disposition") or "").strip()
    if not disposition:
        return [f"finding {label!r}: records no disposition"]

    required = DISPOSITION_REQUIRED_FIELDS.get(disposition)
    if required is None:
        return [
            f"finding {label!r}: disposition {disposition!r} carries no known "
            "obligation; it cannot be shown to meet one"
        ]

    return [
        f"finding {label!r}: {disposition} requires {description}"
        for field, description in required
        if not finding.get(field)
    ]


def unrecognised_members(values: list[str], vocabulary: set[str]) -> list[str]:
    """Values that name nothing in the vocabulary they are drawn from.

    One helper, applied to *every* list in a sibling pair, because checking one list
    and not the other is how an unrecognised value reads as safe. A caller that
    validates `attained` must validate `not_required` with the same call; a test
    enumerates the pairs so a new one cannot be added half-checked.
    """
    return sorted(set(values) - vocabulary)


def evidence_state_partition_conflicts(
    *,
    attained: list[str],
    not_required: list[str],
) -> list[str]:
    """Partition rules for a receipt's two evidence-state lists.

    Derived from `EVIDENCE_STATE_PROGRESSION` above rather than restated as a
    special case: `NOT_REQUIRED` has no position on the ladder, so it cannot be a
    thing that was attained, and anything outside the ladder is not an evidence
    state at all. The producer instead names `NOT_REQUIRED` explicitly, which is why
    a defect in one derivation does not hide in the other.

    docs/foundry/06 §4: a Work Item declares which states are required and which are
    NOT_REQUIRED. The two answers are exclusive, so the lists must be disjoint.

    **Both lists are checked against the vocabulary, and an unrecognised value in
    either is a violation rather than an omission.** An exemption is a positive claim
    that some obligation does not apply; a value naming no evidence state identifies
    nothing that could be exempt, so the record is not incomplete — an empty list
    would be that — it is wrong. Checking `attained` and letting `not_required`
    through unexamined is exactly how "unknown reads as safe" gets shipped, and this
    project has now done that five times.
    """
    ladder = {state.value for state in EVIDENCE_STATE_PROGRESSION}
    violations: list[str] = []

    overlap = sorted(set(attained) & set(not_required))
    if overlap:
        violations.append(
            f"evidence states {overlap} are declared both attained and not-required"
        )

    for state in unrecognised_members(attained, ladder):
        if state == EXEMPTION_MARKER:
            violations.append(
                f"{EXEMPTION_MARKER} is an exemption, not an attained evidence state"
            )
        else:
            violations.append(
                f"{state!r} is not a position on the evidence progression and cannot "
                "have been attained"
            )

    for state in unrecognised_members(not_required, ladder):
        if state == EXEMPTION_MARKER:
            violations.append(
                f"{EXEMPTION_MARKER} is the exemption marker itself and names no "
                "evidence state that could be exempt"
            )
        else:
            violations.append(
                f"{state!r} is not an evidence state and cannot be declared "
                "not-required; an exemption must name the obligation it lifts"
            )

    return violations


# --- vocabulary membership, checked before anything is done with a value --------


def _enum_types(annotation: object) -> list[type]:
    """Every enum type mentioned anywhere in a field annotation."""
    from enum import Enum
    from typing import get_args

    found: list[type] = []
    stack: list[object] = [annotation]
    while stack:
        item = stack.pop()
        if isinstance(item, type) and issubclass(item, Enum):
            found.append(item)
        stack.extend(get_args(item) or ())
    return found


def vocabulary_violations(model: object, *, path: str = "") -> list[str]:
    """Values sitting in an enum-typed position that name nothing in that vocabulary.

    Walks a model's declared fields — including nested models and lists of them —
    and reports every position whose value is outside the enum the field is typed
    with. Runs *before* any membership test, rank lookup, or `.value` dereference,
    because all three of those silently mishandle an unrecognised value: membership
    quietly falls through every branch, rank raises, and dereference raises.

    A validator that returns PASS for an artifact carrying an unrecognised lifecycle
    state has accepted a malformed positive claim, and one that raises has returned
    no verdict at all. Both are failures; this is what makes them a BLOCKED finding
    instead.

    The value arrives as a raw string when a model was built with `model_construct`
    or loaded past its validators — which is exactly the artifact a validator exists
    to examine — so comparison is on the declared enum's values, not on member type.
    """
    fields = getattr(type(model), "model_fields", None)
    if not fields:
        return []

    violations: list[str] = []
    for name, field in fields.items():
        value = getattr(model, name, None)
        if value is None:
            continue
        where = f"{path}.{name}" if path else name
        enums = _enum_types(field.annotation)
        items = value if isinstance(value, (list, tuple)) else [value]

        for index, item in enumerate(items):
            position = where if not isinstance(value, (list, tuple)) else f"{where}[{index}]"
            if item is None:
                continue
            if getattr(type(item), "model_fields", None):
                violations.extend(vocabulary_violations(item, path=position))
                continue
            if not enums:
                continue
            raw = getattr(item, "value", item)
            if any(raw in {member.value for member in enum} for enum in enums):
                continue
            names = "/".join(enum.__name__ for enum in enums)
            violations.append(
                f"{position} carries {raw!r}, which names no {names} value"
            )
    return violations


def enum_value_violations(
    values: object,
    enum_type: type,
    *,
    label: str,
) -> list[str]:
    """Caller-supplied values that name nothing in the vocabulary they must come from.

    The parameter analogue of `vocabulary_violations`, which walks a model. A
    vocabulary value can reach a validator two ways — carried on the artifact under
    examination, or handed in as an argument — and both need the same check before
    the value is ranked, compared, or dereferenced. Covering only the artifact is how
    `required_evidence_states=['SOMEDAY']` came to raise instead of returning a
    verdict.

    Accepts a bare value or a sequence, since a caller may pass either, and reads
    through `getattr(..., "value", ...)` because an argument arriving from a config
    file or another process is a plain string.
    """
    if values is None:
        return []
    items = list(values) if isinstance(values, (list, tuple, set, frozenset)) else [values]
    vocabulary = {member.value for member in enum_type}
    raw = [str(getattr(item, "value", item)) for item in items]
    return [
        f"{label} carries {value!r}, which names no {enum_type.__name__} value"
        for value in unrecognised_members(raw, vocabulary)
    ]


# --- the shared vocabulary gate --------------------------------------------------
#
# Lives here rather than in `validators.py` so that every module doing validation
# work — validators, explainability, reconciliation — reaches the same gate. One
# shared call is what keeps "check the vocabulary first" from being a rule each new
# entry point has to remember separately.


def _gate_finding(
    validator_id: str,
    outcome: ValidationOutcome,
    subject: str,
    message: str,
) -> ValidationFinding:
    from agent_foundry.models.verification import ValidationFinding

    return ValidationFinding(
        validator_id=validator_id, outcome=outcome, subject=subject, message=message
    )


def vocabulary_findings(
    validator_id: str,
    subject: str,
    inputs: dict[str, object],
) -> list[ValidationFinding]:
    """BLOCKED findings for every enum position holding an unrecognised value."""
    findings: list[ValidationFinding] = []
    for label, model in inputs.items():
        if model is None:
            continue
        for violation in vocabulary_violations(model):
            findings.append(
                _gate_finding(
                    validator_id,
                    ValidationOutcome.BLOCKED,
                    subject,
                    f"{label}.{violation}",
                )
            )
    return findings


def malformed_vocabulary_report(
    validator_id: str,
    subject_kind: str,
    subject: str,
    inputs: dict[str, object],
    parameters: dict[str, tuple[object, type]] | None = None,
) -> ValidationReport | None:
    """Reject an artifact whose vocabulary is malformed, before examining anything else.

    Every validator calls this first, and returns its result unchanged when it is not
    None. Two reasons it short-circuits rather than merely adding a finding:

    * **Nothing downstream is safe.** Membership tests silently fall through every
      branch for an unrecognised value, rank lookups and `.value` dereferences raise.
      An exception is not a fail-closed verdict — it returns no report at all, so the
      caller cannot record why the artifact was rejected.
    * **Nothing downstream is meaningful.** Properties evaluated over a state nobody
      recognises produce findings that read as authoritative and are not.

    BLOCKED rather than MISSING: an absent field is unrecorded, and MISSING is right
    for that. A *supplied* value naming nothing in its vocabulary is a positive claim
    that is wrong, and it can never establish the state it purports to.
    """
    findings = vocabulary_findings(validator_id, subject, inputs)
    # A vocabulary value reaches a validator two ways: carried on the artifact, or
    # handed in as an argument. Both are checked here, because both are ranked,
    # compared, and dereferenced by the same downstream code.
    for label, (values, enum_type) in (parameters or {}).items():
        findings.extend(
            _gate_finding(validator_id, ValidationOutcome.BLOCKED, subject, message)
            for message in enum_value_violations(values, enum_type, label=label)
        )
    if not findings:
        return None
    from agent_foundry.models.verification import ValidationReport

    return ValidationReport(
        subject_kind=subject_kind, subject_id=subject, findings=findings
    )


def is_contract_like(value: object) -> bool:
    """True when a value can be read as a contract payload.

    `Iterable[tuple[str, Any]]` and a bare `FoundryModel` annotation both admit
    objects that are neither a model nor a mapping. Reading one raises, and an
    exception is not a fail-closed verdict — it returns no report at all. Callers
    test this first and emit BLOCKED, so "you handed me something that is not a
    contract" is a finding rather than a traceback.
    """
    from collections.abc import Mapping

    return isinstance(value, Mapping) or getattr(type(value), "model_fields", None) is not None
