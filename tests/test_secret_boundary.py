"""Secret boundary and leak-proofing tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_foundry.models import (
    AdoptionPlan,
    CapabilitySpec,
    ExecutionBundle,
    ExecutionReceipt,
    EvidenceBundle,
    IntegrationSpec,
    ProjectManifest,
    RawSecretError,
    RoleContract,
    SecretProvider,
    SecretRef,
    SkillSpec,
    TaskToolkit,
    ToolkitLock,
    WorkItemContract,
    WorkflowSpec,
    dump_json,
    dump_yaml,
    load_yaml,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "valid"

SECRET_REF_COORDINATE_FIELDS = frozenset({"provider", "name", "version", "scope"})


def test_secret_ref_repr_exposes_only_coordinates() -> None:
    ref = SecretRef(provider=SecretProvider.ENV, name="SERVICE_TOKEN", version="v1", scope="read")
    text = repr(ref)
    assert "provider=" in text
    assert "name='SERVICE_TOKEN'" in text
    assert "version='v1'" in text
    assert "SERVICE_TOKEN" in text
    assert "actual-secret" not in text


def test_secret_ref_str_matches_repr() -> None:
    ref = SecretRef(provider=SecretProvider.VAULT, name="conn-id")
    assert str(ref) == repr(ref)


def test_secret_ref_model_dump_contains_only_coordinate_fields() -> None:
    ref = SecretRef(provider=SecretProvider.MANAGED, name="work-tracker-conn")
    dumped = ref.model_dump()
    assert set(dumped.keys()) <= SECRET_REF_COORDINATE_FIELDS
    assert set(dumped.keys()) >= {"provider", "name"}
    assert "value" not in dumped
    assert "secret_value" not in dumped
    assert "material" not in dumped


def test_secret_ref_has_no_field_for_secret_material() -> None:
    field_names = set(SecretRef.model_fields.keys())
    assert field_names == SECRET_REF_COORDINATE_FIELDS


def test_secret_ref_string_form_parses_to_same_object_as_structured() -> None:
    structured = SecretRef(provider=SecretProvider.ENV, name="SERVICE_TOKEN")
    from_string = SecretRef.model_validate("env:SERVICE_TOKEN")
    assert from_string == structured
    assert from_string.model_dump() == structured.model_dump()


def test_secret_ref_string_forms_for_all_schemes() -> None:
    cases = [
        ("env:NAME", SecretProvider.ENV, "NAME"),
        ("os-keychain:entry", SecretProvider.OS_KEYCHAIN, "entry"),
        ("managed:connection-id", SecretProvider.MANAGED, "connection-id"),
        ("vault:path-or-role", SecretProvider.VAULT, "path-or-role"),
        ("workload-identity:profile", SecretProvider.WORKLOAD_IDENTITY, "profile"),
        ("ci-secret:name", SecretProvider.CI_SECRET, "name"),
    ]
    for text, provider, name in cases:
        ref = SecretRef.model_validate(text)
        assert ref.provider == provider
        assert ref.name == name


def test_raw_secret_key_rejected_with_raw_secret_error() -> None:
    with pytest.raises(RawSecretError) as exc_info:
        IntegrationSpec.model_validate(
            {
                "schema_version": "0.1",
                "id": "svc",
                "kind": "integration",
                "transport": "api",
                "version": "1.0.0",
                "permissions": {"write_requires": "explicit-authority"},
                "health": {"required": "authenticated"},
                "adapter_options": {"token": "leaked-value"},
            }
        )
    assert "IntegrationSpec" in str(exc_info.value)
    assert "token" in str(exc_info.value)


def test_integration_spec_free_form_mapping_rejects_api_key() -> None:
    with pytest.raises(RawSecretError) as exc_info:
        IntegrationSpec.model_validate(
            {
                "schema_version": "0.1",
                "id": "svc",
                "kind": "integration",
                "transport": "api",
                "version": "1.0.0",
                "permissions": {"write_requires": "explicit-authority"},
                "health": {"required": "authenticated"},
                "adapter_options": {"api_key": "leaked"},
            }
        )
    message = str(exc_info.value)
    assert "IntegrationSpec" in message
    assert "api_key" in message


def test_dumped_integration_spec_contains_no_secret_values() -> None:
    source = (FIXTURES / "integration_spec.yaml").read_bytes()
    spec = load_yaml(IntegrationSpec, source)
    yaml_out = dump_yaml(spec).decode("utf-8")
    json_out = dump_json(spec).decode("utf-8")
    forbidden_values = ["raw-secret", "sk-live", "password123"]
    for value in forbidden_values:
        assert value not in yaml_out
        assert value not in json_out
    assert "managed" in yaml_out
    assert "work-tracker" in yaml_out


def test_project_manifest_work_modes_rejects_extra_secret_key() -> None:
    with pytest.raises(ValidationError) as exc_info:
        ProjectManifest.model_validate(
            {
                "schema_version": "0.1",
                "project": {
                    "name": "sample-service",
                    "intake_mode": "greenfield",
                    "work_modes": {"primary": "build", "api_key": "sk-live-LOOKALIKE"},
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
        )
    message = str(exc_info.value)
    assert "ProjectManifest" in message
    assert "api_key" in message


@pytest.mark.parametrize(
    ("model_type", "payload"),
    [
        (
            IntegrationSpec,
            {
                "schema_version": "0.1",
                "id": "svc",
                "kind": "integration",
                "transport": "api",
                "version": "1.0.0",
                "permissions": {"write_requires": "explicit-authority"},
                "health": {"required": "authenticated"},
                "adapter_options": {"api_key": "leaked"},
            },
        ),
    ],
)
def test_free_form_mapping_rejects_api_key(model_type: type, payload: dict) -> None:
    with pytest.raises(RawSecretError) as exc_info:
        model_type.model_validate(payload)
    message = str(exc_info.value)
    assert model_type.__name__ in message
    assert "api_key" in message

