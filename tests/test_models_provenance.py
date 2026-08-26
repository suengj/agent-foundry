"""Provenance envelope and ReadinessFinding severity tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_foundry.models import (
    ConsequenceClass,
    ProjectManifest,
    ProjectObservation,
    ProvenanceKind,
    ReadinessFinding,
    dump_json,
    dump_yaml,
    load_json,
    load_yaml,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "valid"
INVALID = Path(__file__).resolve().parent / "fixtures" / "invalid"


def test_project_observation_provenance_roundtrip_yaml() -> None:
    observation = ProjectObservation.model_validate(
        {
            "subject": "test-harness",
            "content": "pytest entrypoint present",
            "provenance": {
                "kind": "observed",
                "confidence": 0.9,
                "source_ref": "tests/test_smoke.py",
            },
        }
    )
    dumped = dump_yaml(observation)
    roundtrip = load_yaml(ProjectObservation, dumped)
    assert roundtrip == observation


def test_project_observation_provenance_roundtrip_json() -> None:
    observation = ProjectObservation.model_validate(
        {
            "subject": "test-harness",
            "content": "pytest entrypoint present",
            "provenance": {"kind": "declared", "source_ref": "owner-intake"},
        }
    )
    dumped = dump_json(observation)
    roundtrip = load_json(ProjectObservation, dumped)
    assert roundtrip == observation


def test_readiness_finding_provenance_roundtrip_yaml() -> None:
    finding = ReadinessFinding.model_validate(
        {
            "dimension": "testability",
            "severity": "medium",
            "message": "Deterministic checks available",
            "provenance": {"kind": "inferred", "confidence": 0.75},
        }
    )
    dumped = dump_yaml(finding)
    roundtrip = load_yaml(ReadinessFinding, dumped)
    assert roundtrip == finding


def test_readiness_finding_provenance_roundtrip_json() -> None:
    finding = ReadinessFinding.model_validate(
        {
            "dimension": "legibility",
            "severity": "low",
            "message": "Repository structure is readable",
            "provenance": {"kind": "normative"},
        }
    )
    dumped = dump_json(finding)
    roundtrip = load_json(ReadinessFinding, dumped)
    assert roundtrip == finding


def test_provenance_confidence_omitted_is_valid() -> None:
    finding = ReadinessFinding.model_validate(
        {
            "dimension": "testability",
            "severity": "low",
            "message": "Checks present",
            "provenance": {"kind": "observed"},
        }
    )
    assert finding.provenance.confidence is None


def test_provenance_confidence_below_zero_rejected() -> None:
    with pytest.raises(ValidationError) as exc_info:
        ProjectObservation.model_validate(
            {
                "subject": "svc",
                "content": "fact",
                "provenance": {"kind": "inferred", "confidence": -0.1},
            }
        )
    message = str(exc_info.value)
    assert "ProjectObservation" in message
    assert "confidence" in message


def test_provenance_confidence_above_one_rejected() -> None:
    with pytest.raises(ValidationError) as exc_info:
        ReadinessFinding.model_validate(
            {
                "dimension": "risk",
                "severity": "high",
                "message": "Elevated risk",
                "provenance": {"kind": "inferred", "confidence": 1.1},
            }
        )
    message = str(exc_info.value)
    assert "ReadinessFinding" in message
    assert "confidence" in message


def test_unknown_readiness_severity_rejected() -> None:
    data = (INVALID / "unknown_readiness_severity.yaml").read_bytes()
    with pytest.raises(ValidationError) as exc_info:
        load_yaml(ProjectManifest, data)
    message = str(exc_info.value)
    assert "ProjectManifest" in message
    assert "severity" in message


def test_project_manifest_fixture_includes_provenance_roundtrip() -> None:
    source = (FIXTURES / "project_manifest.yaml").read_bytes()
    manifest = load_yaml(ProjectManifest, source)
    assert len(manifest.observations) == 1
    assert manifest.observations[0].provenance.kind == ProvenanceKind.OBSERVED
    assert manifest.observations[0].provenance.confidence == 0.9
    assert len(manifest.readiness_findings) == 1
    assert manifest.readiness_findings[0].severity == ConsequenceClass.MEDIUM
    assert manifest.readiness_findings[0].provenance.kind == ProvenanceKind.INFERRED
    dumped = dump_yaml(manifest)
    roundtrip = load_yaml(ProjectManifest, dumped)
    assert roundtrip == manifest
