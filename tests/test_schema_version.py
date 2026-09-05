"""Schema version compatibility tests."""

from __future__ import annotations

import pytest

from agent_foundry.models import (
    FOUNDRY_SCHEMA_VERSION,
    ProjectManifest,
    ProjectProfile,
    SchemaCompatibilityError,
    WorkItemContract,
    validate_schema_compatibility,
)


def _minimal_work_item(schema_version: str) -> dict:
    return {
        "schema_version": schema_version,
        "id": "WI-TEST",
        "title": "Test",
        "work_class": "capability",
        "objective": "Test objective",
        "current_facts": ["fact"],
        "scope": ["scope"],
        "out_of_scope": ["out"],
        "acceptance_criteria": ["criteria"],
        "authority_class": "repository-write",
        "consequence_class": "medium",
        "required_evidence": ["evidence"],
        "stop_conditions": ["stop"],
    }


def _minimal_manifest(schema_version: str) -> dict:
    return {
        "schema_version": schema_version,
        "project": {
            "name": "sample-service",
            "intake_mode": "greenfield",
            "work_modes": {"primary": "build"},
        },
        "state": {"persistence": "local", "temporal_mode": "one-shot"},
        "impact": {
            "external_effect": "read-only",
            "reversibility": "trivial",
            "consequence": "low",
        },
        "execution": {
            "autonomy": "suggest",
            "ambiguity": "procedural",
            "concurrency": "single-writer",
        },
        "assurance": {"required": ["deterministic-tests"]},
        "access": {"sensitivity": "internal"},
    }


def _minimal_profile(schema_version: str) -> dict:
    return {
        "schema_version": schema_version,
        "project_name": "sample-service",
        "dimensions": [
            {
                "dimension": "primary-artifact",
                "resolution": "resolved",
                "attributions": [
                    {"value": "service", "provenance": {"kind": "observed"}}
                ],
            }
        ],
    }


def test_supported_schema_version_accepted() -> None:
    obj = WorkItemContract.model_validate(_minimal_work_item(FOUNDRY_SCHEMA_VERSION))
    assert obj.schema_version == FOUNDRY_SCHEMA_VERSION
    manifest = ProjectManifest.model_validate(_minimal_manifest(FOUNDRY_SCHEMA_VERSION))
    assert manifest.schema_version == FOUNDRY_SCHEMA_VERSION
    profile = ProjectProfile.model_validate(_minimal_profile(FOUNDRY_SCHEMA_VERSION))
    assert profile.schema_version == FOUNDRY_SCHEMA_VERSION


def test_profile_major_mismatch_raises_schema_compatibility_error() -> None:
    with pytest.raises(SchemaCompatibilityError) as exc_info:
        ProjectProfile.model_validate(_minimal_profile("1.0"))
    message = str(exc_info.value)
    assert "ProjectProfile" in message
    assert "1.0" in message
    assert FOUNDRY_SCHEMA_VERSION in message


def test_major_mismatch_raises_schema_compatibility_error() -> None:
    with pytest.raises(SchemaCompatibilityError) as exc_info:
        WorkItemContract.model_validate(_minimal_work_item("1.0"))
    message = str(exc_info.value)
    assert "WorkItemContract" in message
    assert "1.0" in message
    assert FOUNDRY_SCHEMA_VERSION in message


def test_newer_minor_raises_schema_compatibility_error() -> None:
    # "0.3" rather than a literal one-past-current: the case under test is a minor
    # newer than the supported one, and that must stay true after a version rebase.
    with pytest.raises(SchemaCompatibilityError) as exc_info:
        WorkItemContract.model_validate(_minimal_work_item("0.3"))
    message = str(exc_info.value)
    assert "WorkItemContract" in message
    assert "0.3" in message
    assert FOUNDRY_SCHEMA_VERSION in message


def test_validate_schema_compatibility_helper_major() -> None:
    with pytest.raises(SchemaCompatibilityError):
        validate_schema_compatibility("TestContract", "2.0")


def test_validate_schema_compatibility_helper_newer_minor() -> None:
    with pytest.raises(SchemaCompatibilityError):
        validate_schema_compatibility("TestContract", "0.9")
