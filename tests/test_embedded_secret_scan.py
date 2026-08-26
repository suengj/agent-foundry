"""Regression tests for embedded-secret detection at the write/render boundary."""

from __future__ import annotations

import pytest

from typing import Any

from agent_foundry.models import (
    ConfidenceTier,
    EmbeddedSecretError,
    IntegrationSpec,
    SecretProvider,
    SecretRef,
    dump_json,
    dump_json_raw,
    dump_yaml,
    dump_yaml_raw,
    scan_for_embedded_secrets,
)
from agent_foundry.secrets import KEY_PATH_MARKER, format_json_path, parse_allow_path

_INTEGRATION_BASE = {
    "schema_version": "0.1",
    "id": "svc",
    "kind": "integration",
    "transport": "api",
    "version": "1.0.0",
    "permissions": {"write_requires": "explicit-authority"},
    "health": {"required": "authenticated"},
}


def _integration_with_adapter_value(value: str, key: str = "value") -> IntegrationSpec:
    payload = {
        **_INTEGRATION_BASE,
        "adapter_options": {key: value},
    }
    return IntegrationSpec.model_validate(payload)


TIER_A_SAMPLES: dict[str, str] = {
    "openai-style-key": "sk-live-RAWSECRETVALUE12",
    "openai-style-key-sk-prefix": "sk-abcdefghijklmnopqrst",
    "openai-style-key-sk-test": "sk-test-abcdefghijklmnopqrst",
    "github-token": "ghp_1234567890abcdefghijklmnopqrstuvwxyz12",
    "slack-token": "xoxb-123456789012-123456789012-abcdefghijklmnopqrstuv",
    "aws-access-key": "AKIAIOSFODNN7EXAMPLE",
    "google-api-key": "AIzaSyDabcdefghijklmnopqrstuvwxyz123456",
    "gitlab-pat": "glpat-abcdefghijklmnopqrstuvwxyz",
    "npm-token": "npm_abcdefghijklmnopqrstuvwxyz",
    "doppler-token": "dop_v1_abcdefghijklmnopqrstuvwxyz",
    "stripe-secret-key": "sk_live_abcdefghijklmnopqrstuvwxyz",
    "stripe-publishable-key": "pk_live_abcdefghijklmnopqrstuvwxyz",
    "pem-private-key": "-----BEGIN RSA PRIVATE KEY-----",
    "jwt": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.x",
}


SAFE_VALUES: tuple[tuple[str, str], ...] = (
    ("git-sha1", "a1b2c3d4e5f6789012345678abcdef1234567890"),
    ("git-sha256", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
    ("uuid", "550e8400-e29b-41d4-a716-446655440000"),
    ("iso-timestamp", "2026-08-26T12:30:45Z"),
    ("semver-build", "1.2.3+build.20260826"),
    ("posix-path", "/var/log/application/service.log"),
    ("https-url", "https://example.com/api/v1/resources"),
    ("decimal-id", "123456789012345678901234567890"),
    ("lowercase-hex-hash", "deadbeef0123456789abcdef0123456789abcdef"),
    ("english-sentence", "This is an ordinary sentence about configuration."),
    ("short-opaque-id", "aGVsbG8"),
)

HIGH_ENTROPY_NON_VENDOR = "Kj8#mP2$vL9@nQ4!wR7&xT5&zA1#bC3"

VOCABULARY_FALSE_POSITIVES: tuple[str, ...] = (
    "risk-assessment",
    "risk-assessment-v2",
    "task-runner",
    "task-toolkit-resolver",
    "disk-usage-monitor",
    "desk-booking",
    "mask-sensitive-fields",
    "ask-for-approval",
    "brisk-deploy",
    "whisk-service",
    "the task-runner evaluates risk-assessment for each work item",
    "helper_npm_installerscript",
    "xyzAKIAABCDEFGHIJKLMNOP",
    "prefix-glpat-ABCDEFGHIJK",
    "refs/heads/sk-live-feature-toggle",
    "refs/heads/task-runner-fix",
    "sk-live-feature-toggle",
    "https://example.com/v1/sk-live-docs-page",
)

TIER_A_BOUNDARY_SECRETS: dict[str, str] = {
    "openai-style-key": "sk-live-ABCDEFGH12345678",
    "github-token": "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345",
    "slack-token": "xoxb-123456789012-123456789012-abcdefghijklmnopqrstuv",
    "aws-access-key": "AKIAIOSFODNN7EXAMPLE",
    "google-api-key": "AIzaSyDabcdefghijklmnopqrstuvwxyz123456",
    "gitlab-pat": "glpat-abcdefghijklmnopqrstuvwxyz",
    "npm-token": "npm_abcdefghijklmnopqrstuvwxyz",
    "doppler-token": "dop_v1_abcdefghijklmnopqrstuvwxyz",
    "stripe-secret-key": "sk_live_abcdefghijklmnopqrstuvwxyz",
    "stripe-publishable-key": "pk_live_abcdefghijklmnopqrstuvwxyz",
    "pem-private-key": "-----BEGIN RSA PRIVATE KEY-----",
    "jwt": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.x",
}

BOUNDARY_WRAPPERS: dict[str, str] = {
    "start": "{secret}",
    "space": "Bearer {secret}",
    "equals": "api_key={secret}",
    "colon": "token:{secret}",
    "quote": "'{secret}'",
}


@pytest.mark.parametrize("value", VOCABULARY_FALSE_POSITIVES)
def test_vocabulary_false_positives_produce_no_tier_a(value: str) -> None:
    payload = {"note": value}
    dump_yaml_raw(payload)
    dump_json_raw(payload)
    findings = scan_for_embedded_secrets(payload)
    tier_a = [
        finding for finding in findings if finding.confidence_tier == ConfidenceTier.TIER_A
    ]
    assert tier_a == [], f"{value!r} produced Tier A findings: {tier_a}"


@pytest.mark.parametrize("rule_name", TIER_A_BOUNDARY_SECRETS.keys())
@pytest.mark.parametrize("boundary_name", BOUNDARY_WRAPPERS.keys())
def test_tier_a_boundary_detection_still_works(rule_name: str, boundary_name: str) -> None:
    secret = TIER_A_BOUNDARY_SECRETS[rule_name]
    value = BOUNDARY_WRAPPERS[boundary_name].format(secret=secret)
    payload = {"note": value}
    findings = scan_for_embedded_secrets(payload)
    tier_a = [
        finding for finding in findings if finding.confidence_tier == ConfidenceTier.TIER_A
    ]
    assert tier_a, f"{rule_name} at {boundary_name} produced no Tier A findings"
    with pytest.raises(EmbeddedSecretError):
        dump_yaml_raw(payload)
    with pytest.raises(EmbeddedSecretError):
        dump_json_raw(payload)


def test_tier_a_secret_used_as_dict_key_raises_on_dump() -> None:
    secret_key = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
    payload = {secret_key: "value"}
    with pytest.raises(EmbeddedSecretError) as exc_info:
        dump_yaml_raw(payload)
    error = exc_info.value
    assert error.json_path == "[key]"
    assert error.rule_name == "github-token"
    assert secret_key not in str(error)
    assert secret_key not in repr(error)


@pytest.mark.parametrize("rule_name", TIER_A_SAMPLES.keys())
def test_tier_a_true_positive_raises_dump_yaml(rule_name: str) -> None:
    spec = _integration_with_adapter_value(TIER_A_SAMPLES[rule_name])
    with pytest.raises(EmbeddedSecretError):
        dump_yaml(spec)


@pytest.mark.parametrize("rule_name", TIER_A_SAMPLES.keys())
def test_tier_a_true_positive_raises_dump_json(rule_name: str) -> None:
    spec = _integration_with_adapter_value(TIER_A_SAMPLES[rule_name])
    with pytest.raises(EmbeddedSecretError):
        dump_json(spec)


def test_issue_reproduction_integration_spec_adapter_options_fails_dump() -> None:
    spec = _integration_with_adapter_value("sk-live-RAWSECRET1234567", key="custom_option")
    with pytest.raises(EmbeddedSecretError) as exc_info:
        dump_yaml(spec)
    assert exc_info.value.json_path == "adapter_options.custom_option"
    assert exc_info.value.rule_name == "openai-style-key"


@pytest.mark.parametrize(("label", "value"), SAFE_VALUES)
def test_false_positive_tolerance_no_tier_a_or_raise(label: str, value: str) -> None:
    spec = _integration_with_adapter_value(value, key=label)
    dump_yaml(spec)
    dump_json(spec)
    findings = scan_for_embedded_secrets(spec.model_dump(mode="json"))
    tier_a = [finding for finding in findings if finding.confidence_tier == ConfidenceTier.TIER_A]
    assert tier_a == [], f"{label} produced Tier A findings: {tier_a}"


def test_secret_ref_values_never_trigger_scan_or_dump() -> None:
    spec = IntegrationSpec.model_validate(
        {
            **_INTEGRATION_BASE,
            "auth": {
                "method": "oauth",
                "credential_ref": SecretRef(provider=SecretProvider.MANAGED, name="work-tracker"),
            },
            "adapter_options": {
                "credential_ref": "managed:connection-id",
                "structured_ref": {
                    "provider": "env",
                    "name": "SERVICE_TOKEN",
                },
            },
        }
    )
    dump_yaml(spec)
    dump_json(spec)
    findings = scan_for_embedded_secrets(spec.model_dump(mode="json"))
    assert findings == []


def test_redaction_never_echoes_full_secret() -> None:
    secret = "sk-live-THISISSECRETVALUE9"
    spec = _integration_with_adapter_value(secret)
    with pytest.raises(EmbeddedSecretError) as exc_info:
        dump_json(spec)
    error = exc_info.value
    message = str(error)
    repr_text = repr(error)
    assert secret not in message
    assert secret not in repr_text
    assert error.json_path == "adapter_options.value"
    assert error.rule_name == "openai-style-key"
    assert "rule=openai-style-key" in message


def test_allow_paths_per_path_not_global() -> None:
    secret = "sk-live-ALLOWED12ATONEPATH00"
    allowed_spec = _integration_with_adapter_value(secret, key="allowed")
    blocked_spec = _integration_with_adapter_value(secret, key="blocked")

    dump_yaml(allowed_spec, allow_paths=("adapter_options.allowed",))
    dump_json(allowed_spec, allow_paths=("adapter_options.allowed",))

    with pytest.raises(EmbeddedSecretError) as exc_info:
        dump_yaml(blocked_spec, allow_paths=("adapter_options.allowed",))
    assert exc_info.value.json_path == "adapter_options.blocked"


def test_tier_b_entropy_is_advisory_only() -> None:
    spec = _integration_with_adapter_value(HIGH_ENTROPY_NON_VENDOR)
    dump_yaml(spec)
    dump_json(spec)
    findings = scan_for_embedded_secrets(spec.model_dump(mode="json"))
    tier_b = [
        finding
        for finding in findings
        if finding.confidence_tier == ConfidenceTier.TIER_B
    ]
    assert len(tier_b) == 1
    assert tier_b[0].rule_name == "high-entropy"
    assert tier_b[0].json_path == "adapter_options.value"


def test_dump_raw_helpers_enforce_same_boundary() -> None:
    with pytest.raises(EmbeddedSecretError):
        dump_yaml_raw({"token": TIER_A_SAMPLES["github-token"]})
    with pytest.raises(EmbeddedSecretError):
        dump_json_raw({"token": TIER_A_SAMPLES["github-token"]})


def test_secret_ref_masquerade_with_extra_field_is_detected() -> None:
    payload = {
        "adapter_options": {
            "x": {
                "provider": "env",
                "name": "SAFE_NAME",
                "other": "sk-live-ABCDEFGH12345678",
            }
        }
    }
    with pytest.raises(EmbeddedSecretError):
        dump_json_raw(payload)
    with pytest.raises(EmbeddedSecretError):
        dump_yaml_raw(payload)


def test_genuine_secret_ref_subtree_is_still_skipped() -> None:
    payload = {
        "adapter_options": {
            "ref": {"provider": "env", "name": "SAFE_NAME"},
        }
    }
    dump_json_raw(payload)
    dump_yaml_raw(payload)
    assert scan_for_embedded_secrets(payload) == []


def test_allow_literal_dotted_key_does_not_cover_nested_path() -> None:
    secret = "sk-live-ABCDEFGH12345678"
    literal_payload = {"adapter_options": {"a.b": secret}}
    nested_payload = {"adapter_options": {"a": {"b": secret}}}
    dump_yaml_raw(literal_payload, allow_paths=("adapter_options.a\\.b",))
    with pytest.raises(EmbeddedSecretError):
        dump_yaml_raw(nested_payload, allow_paths=("adapter_options.a\\.b",))


def test_allow_nested_path_does_not_cover_literal_dotted_key() -> None:
    secret = "sk-live-ABCDEFGH12345678"
    literal_only = {"adapter_options": {"a.b": secret}}
    with pytest.raises(EmbeddedSecretError):
        dump_yaml_raw(literal_only, allow_paths=("adapter_options.a.b",))
    nested_only = {"adapter_options": {"a": {"b": secret}}}
    dump_yaml_raw(nested_only, allow_paths=("adapter_options.a.b",))


@pytest.mark.parametrize(
    "payload",
    [
        {"a": ("sk-live-ABCDEFGH12345678",)},
        {"set": {"sk-live-ABCDEFGH12345678"}},
        {"frozen": frozenset(["sk-live-ABCDEFGH12345678"])},
    ],
)
def test_collection_payloads_raise_on_dump_json_raw(payload: dict) -> None:
    with pytest.raises(EmbeddedSecretError):
        dump_json_raw(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"a": ("sk-live-ABCDEFGH12345678",)},
        {"set": {"sk-live-ABCDEFGH12345678"}},
        {"frozen": frozenset(["sk-live-ABCDEFGH12345678"])},
    ],
)
def test_collection_payloads_raise_on_dump_yaml_raw(payload: dict) -> None:
    with pytest.raises(EmbeddedSecretError):
        dump_yaml_raw(payload)


def test_collection_payloads_raise_on_dump_json_model() -> None:
    spec = IntegrationSpec.model_validate(
        {
            **_INTEGRATION_BASE,
            "adapter_options": {
                "items": [TIER_A_BOUNDARY_SECRETS["openai-style-key"]],
            },
        }
    )
    with pytest.raises(EmbeddedSecretError):
        dump_json(spec)


def test_collection_payloads_raise_on_dump_yaml_model() -> None:
    spec = IntegrationSpec.model_validate(
        {
            **_INTEGRATION_BASE,
            "adapter_options": {
                "items": [TIER_A_BOUNDARY_SECRETS["openai-style-key"]],
            },
        }
    )
    with pytest.raises(EmbeddedSecretError):
        dump_yaml(spec)


def test_git_ref_prose_does_not_block_dump() -> None:
    payload = {"reason": "refs/heads/sk-live-feature-toggle"}
    dump_json_raw(payload)
    dump_yaml_raw(payload)
    findings = scan_for_embedded_secrets(payload)
    tier_a = [f for f in findings if f.confidence_tier == ConfidenceTier.TIER_A]
    assert tier_a == []


@pytest.mark.parametrize(
    ("label", "segments"),
    [
        ("plain", ("plain",)),
        ("dot", ("a.b",)),
        ("bracket", ("a[b]",)),
        ("backslash", ("a\\b",)),
        ("number-like", ("123",)),
        ("list-index", ("x", 0)),
        ("key-marker", ("y", KEY_PATH_MARKER)),
        ("literal-atkey", ("y", "@key")),
        ("plain-key", ("y", "key")),
        ("digit-key", ("x", "0")),
        ("nested-awkward", ("a.b", "c[d]", 2, KEY_PATH_MARKER)),
        ("empty-key", ("",)),
    ],
)
def test_path_encoding_round_trip_and_injective(label: str, segments: tuple) -> None:
    segment_tuple = tuple(segments)
    formatted = format_json_path(segment_tuple)
    assert parse_allow_path(formatted) == segment_tuple, (
        f"{label}: {segment_tuple!r} -> {formatted!r} -> {parse_allow_path(formatted)!r}"
    )

    all_formatted = [format_json_path(tuple(case[1])) for case in [
        ("plain", ("plain",)),
        ("dot", ("a.b",)),
        ("bracket", ("a[b]",)),
        ("backslash", ("a\\b",)),
        ("number-like", ("123",)),
        ("list-index", ("x", 0)),
        ("key-marker", ("y", KEY_PATH_MARKER)),
        ("literal-atkey", ("y", "@key")),
        ("plain-key", ("y", "key")),
        ("digit-key", ("x", "0")),
        ("nested-awkward", ("a.b", "c[d]", 2, KEY_PATH_MARKER)),
        ("empty-key", ("",)),
    ]]
    assert len(all_formatted) == len(set(all_formatted)), (
        f"path encodings are not injective: {all_formatted}"
    )


def test_key_marker_allow_does_not_cover_literal_atkey_value() -> None:
    secret = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
    under_atkey = {"y": {"@key": secret}}
    as_key = {"y": {secret: "v"}}
    finding_as_key = scan_for_embedded_secrets(as_key)[0]
    assert finding_as_key.path_segments == ("y", KEY_PATH_MARKER)
    assert finding_as_key.json_path == "y[key]"
    dump_yaml_raw(as_key, allow_paths=(finding_as_key.json_path,))
    with pytest.raises(EmbeddedSecretError):
        dump_yaml_raw(under_atkey, allow_paths=(finding_as_key.json_path,))


def test_literal_atkey_allow_does_not_cover_key_marker() -> None:
    secret = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
    under_atkey = {"y": {"@key": secret}}
    as_key = {"y": {secret: "v"}}
    finding_under = scan_for_embedded_secrets(under_atkey)[0]
    assert finding_under.path_segments == ("y", "@key")
    assert finding_under.json_path == "y.@key"
    dump_yaml_raw(under_atkey, allow_paths=(finding_under.json_path,))
    with pytest.raises(EmbeddedSecretError):
        dump_yaml_raw(as_key, allow_paths=(finding_under.json_path,))


def test_diagnostic_path_round_trips_for_literal_dotted_key() -> None:
    secret = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
    payload = {"opt": {"a.b": secret}}
    finding = scan_for_embedded_secrets(payload)[0]
    assert parse_allow_path(finding.json_path) == finding.path_segments
    dump_yaml_raw(payload, allow_paths=(finding.json_path,))


TIER_A_MUST_CATCH: tuple[tuple[str, str], ...] = (
    ("sk-live-alnum", "sk-live-ABCDEFGH12345678"),
    ("sk-live-bearer", "Bearer sk-live-ABCDEFGH12345678"),
    ("sk-live-equals", "api_key=sk-live-ABCDEFGH12345678"),
    ("sk-live-lowercase", "sk-live-aaaaaaaaaaaaaaaa"),
    ("ghp-lowercase", "ghp_aaaaaaaaaaaaaaaaaaaaaaaa"),
    ("ghp-digits", "ghp_" + "1" * 36),
    ("aws-all-a", "AKIAAAAAAAAAAAAAAAAA"),
    ("aws-mixed", "AKIAABCDEFGHIJKLMNOP"),
    ("aws-digits", "AKIA1234567890123456"),
    ("slack-realistic", "xoxb-111111111111-abcdefghijklmnopqrst"),
    ("gitlab", "glpat-abcdefghijklmnopqrst"),
    ("npm-lowercase", "npm_" + "a" * 36),
    ("stripe-sk-lowercase", "sk_live_" + "a" * 20),
    ("stripe-pk-lowercase", "pk_live_" + "a" * 20),
    ("doppler-lowercase", "dop_v1_" + "a" * 20),
    ("google", "AIzaSyDabcdefghijklmnopqrstuvwxyz123456"),
    (
        "jwt",
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.x",
    ),
    ("pem", "-----BEGIN RSA PRIVATE KEY-----"),
)

TIER_A_MUST_NOT_CATCH: tuple[str, ...] = (
    *VOCABULARY_FALSE_POSITIVES,
    "refs/heads/sk-live-feature-toggle",
    "refs/heads/task-runner-fix",
    "sk-live-feature-toggle",
    "https://example.com/v1/sk-live-docs-page",
)


@pytest.mark.parametrize(("label", "value"), TIER_A_MUST_CATCH)
def test_tier_a_must_catch_parametrized(label: str, value: str) -> None:
    payload = {"credential": value}
    findings = scan_for_embedded_secrets(payload)
    tier_a = [f for f in findings if f.confidence_tier == ConfidenceTier.TIER_A]
    assert tier_a, f"{label}: expected Tier A finding for {value!r}"
    with pytest.raises(EmbeddedSecretError):
        dump_json_raw(payload)
    with pytest.raises(EmbeddedSecretError):
        dump_yaml_raw(payload)


@pytest.mark.parametrize("value", TIER_A_MUST_NOT_CATCH)
def test_tier_a_must_not_catch_parametrized(value: str) -> None:
    payload = {"note": value}
    dump_json_raw(payload)
    dump_yaml_raw(payload)
    findings = scan_for_embedded_secrets(payload)
    tier_a = [f for f in findings if f.confidence_tier == ConfidenceTier.TIER_A]
    assert tier_a == [], f"{value!r} produced Tier A findings: {tier_a}"


def test_slack_lowercase_bot_token_is_detected() -> None:
    token = "xoxb-111111111111-abcdefghijklmnopqrst"
    payload = {"credential": token}
    findings = scan_for_embedded_secrets(payload)
    assert any(f.rule_name == "slack-token" for f in findings)
    with pytest.raises(EmbeddedSecretError):
        dump_json_raw(payload)


def test_secret_ref_scheme_prefix_does_not_bypass_tier_a() -> None:
    with pytest.raises(EmbeddedSecretError):
        dump_json_raw({"value": "env:sk-live-ABCDEFGH12345678"})


def test_deep_nested_clean_payload_serializes() -> None:
    payload: dict[str, Any] = {"value": "clean"}
    for _ in range(2000):
        payload = {"x": payload}
    dump_json_raw(payload)


def test_well_formed_url_path_does_not_produce_tier_b() -> None:
    payload = {
        "url": "https://example.com/artifact/QwErTyUiOpAsDfGhJkLzXcVbNm123456",
    }
    dump_json_raw(payload)
    findings = scan_for_embedded_secrets(payload)
    tier_b = [f for f in findings if f.confidence_tier == ConfidenceTier.TIER_B]
    assert tier_b == []
