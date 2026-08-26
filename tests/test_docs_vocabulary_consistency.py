"""Regression guard: docs classification table must match canonical enum vocabularies."""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path

import pytest

from agent_foundry.models.common import (
    Ambiguity,
    AssuranceMode,
    Autonomy,
    ConsequenceClass,
    Concurrency,
    ExternalEffectClass,
    IntegrationHealthState,
    PrimaryArtifactState,
    PrimaryWorkMode,
    Reversibility,
    Statefulness,
    TemporalMode,
    AccessSensitivity,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
INTAKE_DOC = REPO_ROOT / "docs" / "foundry" / "02-project-intake-and-adoption.md"
TOOLKIT_DOC = REPO_ROOT / "docs" / "foundry" / "04-toolkit-and-integrations.md"

DIMENSION_TO_ENUM: dict[str, type[StrEnum]] = {
    "Primary work mode": PrimaryWorkMode,
    "Primary artifact/state": PrimaryArtifactState,
    "Statefulness": Statefulness,
    "External effect": ExternalEffectClass,
    "Reversibility": Reversibility,
    "Autonomy": Autonomy,
    "Consequence severity": ConsequenceClass,
    "Assurance mode": AssuranceMode,
    "Ambiguity": Ambiguity,
    "Access sensitivity": AccessSensitivity,
    "Temporal mode": TemporalMode,
    "Concurrency": Concurrency,
}

INTEGRATION_HEALTH_HEADING = "## 12. Integration lifecycle / health"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _enum_values(enum: type[StrEnum]) -> set[str]:
    return {member.value for member in enum}


def _parse_classification_table(text: str) -> dict[str, str]:
    """Parse the '| Dimension | Examples |' markdown table in section 3."""
    rows: dict[str, str] = {}
    in_table = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "| Dimension | Examples |":
            in_table = True
            continue
        if not in_table:
            continue
        if stripped == "|---|---|":
            continue
        if not stripped.startswith("|"):
            break
        match = re.match(r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|$", stripped)
        if match is None:
            break
        rows[match.group(1)] = match.group(2)
    if not rows:
        pytest.fail("classification table not found in intake doc section 3")
    return rows


def _parse_text_codeblock_after_heading(text: str, heading: str) -> list[str]:
    idx = text.find(heading)
    if idx == -1:
        pytest.fail(f"heading not found: {heading}")
    rest = text[idx:]
    fence_start = rest.find("```text")
    if fence_start == -1:
        pytest.fail(f"```text block not found after heading: {heading}")
    content_start = rest.find("\n", fence_start) + 1
    fence_end = rest.find("```", content_start)
    if fence_end == -1:
        pytest.fail(f"unclosed ```text block after heading: {heading}")
    return [line.strip() for line in rest[content_start:fence_end].splitlines() if line.strip()]


def _assert_vocabulary_match(
    dimension: str,
    doc_values: set[str],
    enum_values: set[str],
) -> None:
    unknown = sorted(doc_values - enum_values)
    missing = sorted(enum_values - doc_values)
    if unknown or missing:
        details: list[str] = []
        if unknown:
            details.append(f"unknown in doc: {unknown}")
        if missing:
            details.append(f"missing from doc: {missing}")
        pytest.fail(f"{dimension}: " + "; ".join(details))


def test_classification_table_matches_enums() -> None:
    table = _parse_classification_table(_read(INTAKE_DOC))

    unmapped = sorted(set(table) - set(DIMENSION_TO_ENUM))
    if unmapped:
        pytest.fail(
            "classification table has unmapped dimension(s): "
            + ", ".join(unmapped)
        )

    absent = sorted(set(DIMENSION_TO_ENUM) - set(table))
    if absent:
        pytest.fail(
            "classification table is missing mapped dimension(s): "
            + ", ".join(absent)
        )

    for dimension, enum in DIMENSION_TO_ENUM.items():
        examples = table[dimension]
        doc_values = {part.strip() for part in examples.split(",")}
        _assert_vocabulary_match(dimension, doc_values, _enum_values(enum))


def test_integration_health_codeblock_matches_enum() -> None:
    listed = _parse_text_codeblock_after_heading(
        _read(TOOLKIT_DOC),
        INTEGRATION_HEALTH_HEADING,
    )
    doc_values = set(listed)
    enum_values = _enum_values(IntegrationHealthState)
    _assert_vocabulary_match("IntegrationHealthState", doc_values, enum_values)
