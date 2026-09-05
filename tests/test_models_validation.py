"""Validation failure tests for invalid contract fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_foundry.models import (
    FOUNDRY_SCHEMA_VERSION,
    IntegrationAuthMethod,
    IntegrationSpec,
    ProjectManifest,
    RawSecretError,
    SchemaCompatibilityError,
    WorkItemContract,
    load_yaml,
)

INVALID = Path(__file__).resolve().parent / "fixtures" / "invalid"


def test_unknown_enum_raises_validation_error() -> None:
    data = (INVALID / "unknown_enum.yaml").read_bytes()
    with pytest.raises(ValidationError) as exc_info:
        load_yaml(ProjectManifest, data)
    message = str(exc_info.value)
    assert "ProjectManifest" in message
    assert "intake_mode" in message


def test_extra_field_raises_validation_error() -> None:
    data = (INVALID / "extra_field.yaml").read_bytes()
    with pytest.raises(ValidationError) as exc_info:
        load_yaml(WorkItemContract, data)
    message = str(exc_info.value)
    assert "WorkItemContract" in message
    assert "unexpected_field" in message


def test_missing_required_raises_validation_error() -> None:
    data = (INVALID / "missing_required.yaml").read_bytes()
    with pytest.raises(ValidationError) as exc_info:
        load_yaml(WorkItemContract, data)
    message = str(exc_info.value)
    assert "WorkItemContract" in message
    assert "objective" in message


def test_wrong_type_raises_validation_error() -> None:
    data = (INVALID / "wrong_type.yaml").read_bytes()
    with pytest.raises(ValidationError) as exc_info:
        load_yaml(WorkItemContract, data)
    message = str(exc_info.value)
    assert "WorkItemContract" in message
    assert "current_facts" in message


def test_incompatible_schema_version_major_raises() -> None:
    data = (INVALID / "incompatible_schema_version_major.yaml").read_bytes()
    with pytest.raises(SchemaCompatibilityError) as exc_info:
        load_yaml(WorkItemContract, data)
    message = str(exc_info.value)
    assert "WorkItemContract" in message
    assert "1.0" in message
    assert FOUNDRY_SCHEMA_VERSION in message


def test_incompatible_schema_version_minor_raises() -> None:
    data = (INVALID / "incompatible_schema_version_minor.yaml").read_bytes()
    with pytest.raises(SchemaCompatibilityError) as exc_info:
        load_yaml(WorkItemContract, data)
    message = str(exc_info.value)
    assert "WorkItemContract" in message
    assert "0.3" in message
    assert FOUNDRY_SCHEMA_VERSION in message


def test_raw_secret_in_integration_raises() -> None:
    data = (INVALID / "raw_secret_in_integration.yaml").read_bytes()
    with pytest.raises(RawSecretError) as exc_info:
        load_yaml(IntegrationSpec, data)
    message = str(exc_info.value)
    assert "IntegrationSpec" in message
    assert "api_key" in message


def test_integration_spec_section_7_example_parses() -> None:
    spec = IntegrationSpec.model_validate(
        {
            "schema_version": "0.1",
            "id": "work-tracker",
            "kind": "integration",
            "transport": "mcp",
            "version": "1",
            "capabilities": ["work.read", "work.write"],
            "permissions": {"write_requires": "explicit-authority"},
            "auth": {"method": "oauth", "credential_ref": "managed:work-tracker"},
            "health": {"required": "authenticated"},
        }
    )
    assert spec.auth is not None
    assert spec.auth.method == IntegrationAuthMethod.OAUTH
    assert spec.auth.credential_ref.provider.value == "managed"
    assert spec.auth.credential_ref.name == "work-tracker"

