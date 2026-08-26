"""Compat expression guard tests — mutant killers for fullmatch and operator requirements."""

from __future__ import annotations

import pytest

from agent_foundry.models import SchemaCompatibilityError
from agent_foundry.toolkit.compat import (
    CompatExpressionError,
    _parse_compat_clause,
    assert_registry_compat,
    foundry_version_matches_compat,
)


def test_compat_rejects_empty_expression() -> None:
    with pytest.raises(CompatExpressionError, match="must not be empty"):
        foundry_version_matches_compat("")


def test_compat_rejects_bare_version_without_operator() -> None:
    with pytest.raises(CompatExpressionError, match="invalid compat clause"):
        foundry_version_matches_compat("0.1")


def test_parse_compat_clause_requires_operator() -> None:
    with pytest.raises(CompatExpressionError, match="invalid compat clause"):
        _parse_compat_clause("0.1")


def test_assert_registry_compat_rejects_bare_version() -> None:
    with pytest.raises(SchemaCompatibilityError):
        assert_registry_compat("0.1")
