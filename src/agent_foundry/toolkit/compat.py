"""Foundry version compatibility checks for registry components."""

from __future__ import annotations

import re

from agent_foundry import __version__
from agent_foundry.models.base import SchemaCompatibilityError

_COMPAT_PATTERN = re.compile(
    r"(?P<op>>=|<=|>|<|==)?(?P<major>\d+)\.(?P<minor>\d+)(?:\.(?P<patch>\d+))?"
)


def _parse_foundry_version(version: str) -> tuple[int, int, int]:
    base = version.split(".dev")[0]
    parts = base.split(".")
    if len(parts) < 2:
        raise ValueError(f"invalid foundry version {version!r}")
    major = int(parts[0])
    minor = int(parts[1])
    patch = int(parts[2]) if len(parts) > 2 else 0
    return major, minor, patch


def _parse_compat_clause(clause: str) -> tuple[str, tuple[int, int]]:
    match = _COMPAT_PATTERN.match(clause.strip())
    if match is None:
        raise ValueError(f"invalid compat clause {clause!r}")
    op = match.group("op") or "=="
    major = int(match.group("major"))
    minor = int(match.group("minor"))
    return op, (major, minor)


def foundry_version_matches_compat(compat: str) -> bool:
    """Return True when the running foundry version satisfies compat expression."""
    current = _parse_foundry_version(__version__)
    current_pair = (current[0], current[1])
    for part in compat.split(","):
        part = part.strip()
        if not part:
            continue
        op, target = _parse_compat_clause(part)
        if op == ">=":
            if current_pair < target:
                return False
        elif op == "<=":
            if current_pair > target:
                return False
        elif op == ">":
            if current_pair <= target:
                return False
        elif op == "<":
            if current_pair >= target:
                return False
        elif op == "==":
            if current_pair != target:
                return False
        else:
            raise ValueError(f"unsupported compat operator in {part!r}")
    return True


def assert_registry_compat(registry_compat: str, *, contract_name: str = "CapabilityRegistry") -> None:
    if not foundry_version_matches_compat(registry_compat):
        raise SchemaCompatibilityError(
            f"{contract_name}: foundry_compat {registry_compat!r} is incompatible with "
            f"running version {__version__}"
        )
