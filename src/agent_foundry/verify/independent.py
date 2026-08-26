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

from agent_foundry.models.common import (
    EvidenceState,
    ExternalEffectClass,
    IntegrationHealthState,
)

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


def effect_rank(effect: ExternalEffectClass | None) -> int:
    """Position of an external-effect class, with unknown ranking above all."""
    if effect is None:
        return UNDECLARED_BOUND_RANK
    return EXTERNAL_EFFECT_ASCENDING.index(effect)


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


def health_satisfies(
    actual: IntegrationHealthState | None,
    required: IntegrationHealthState,
) -> bool:
    """True when an observed state meets a required one.

    `None` — no observation at all — satisfies nothing. Unobserved is not healthy,
    and this function is the place that refuses to blur the two.
    """
    if actual is None:
        return False
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


def authentication_evidenced(actual: IntegrationHealthState | None) -> bool:
    """True when the observed state is positive evidence of authentication."""
    return actual is not None and actual in AUTHENTICATED_STATES


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
