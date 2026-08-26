"""Regressions for defects found reviewing the SUE-318 write/render guard.

Each test here pins a defect that shipped in #7 and was repaired afterwards:
four serialization regressions introduced by the iterative dump rewrite, and
three Tier A gaps in the scanner itself.
"""

from __future__ import annotations

import base64
import json

import pytest

from agent_foundry.models import (
    dump_json_raw,
    dump_yaml_raw,
    parse_json,
    parse_yaml,
    scan_for_embedded_secrets,
)
from agent_foundry.secrets import _match_tier_a, parse_allow_path

GITHUB_TOKEN = "ghp_" + "0aZ9bY8cX7dW6eV5fU4gT3hS2iR1jQ"


def _json_dumps_reference(payload: object) -> str:
    """The pre-rewrite encoder, which these dumps must stay byte-identical to."""
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


# --- serialization regressions -------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {1: "a", 2: "b", 10: "c"},
        {True: "t", False: "f"},
        {None: "n"},
        {1.5: "a", 2.25: "b"},
        {-1: "a", 3: "b"},
        {float("nan"): "x"},
        {float("inf"): "p", float("-inf"): "m"},
    ],
)
def test_non_string_mapping_keys_match_reference_encoder(payload: dict) -> None:
    """Rendering a non-str key as a JSON *value* emitted unquoted, invalid JSON."""
    rendered = dump_json_raw(payload).decode("utf-8").strip()
    assert rendered == _json_dumps_reference(payload)


@pytest.mark.parametrize("payload", [{1: "a"}, {None: "n"}, {1.5: "x"}, {True: "t"}])
def test_non_string_key_output_is_parseable_json(payload: dict) -> None:
    assert parse_json(dump_json_raw(payload)) == {
        _json_dumps_reference(payload).split('"')[1]: next(iter(payload.values()))
    }


@pytest.mark.parametrize("payload", [{None: "n"}, {1.5: "hello"}, {True: "t"}, {7: "s"}])
def test_non_string_key_does_not_crash_the_secret_guard(payload: dict) -> None:
    """format_json_path assumed str/int and raised AttributeError on the scan path."""
    dump_json_raw(payload)
    dump_yaml_raw(payload)
    assert scan_for_embedded_secrets(payload) == []


def test_shared_subtree_is_expanded_not_aliased_in_yaml() -> None:
    """Identity memoization made PyYAML emit anchors/aliases, changing the bytes."""
    shared = {"z": 1, "a": [1, 2]}
    text = dump_yaml_raw({"b": shared, "a": shared, "c": [shared, shared]}).decode("utf-8")
    assert "&id" not in text and "*id" not in text

    loaded = parse_yaml(text)
    # Independent copies, not four references to one mutable object.
    loaded["b"]["z"] = 99
    assert loaded["a"]["z"] == 1
    assert loaded["c"][0]["z"] == 1


@pytest.mark.parametrize("kind", ["dict", "list"])
def test_reference_cycle_raises_clean_value_error(kind: str) -> None:
    """Cycles surfaced as KeyError(<id>) instead of a meaningful error."""
    if kind == "dict":
        payload: object = {}
        payload["self"] = payload  # type: ignore[index]
    else:
        payload = []
        payload.append(payload)  # type: ignore[attr-defined]

    with pytest.raises(ValueError, match="Circular reference detected"):
        dump_json_raw(payload)
    with pytest.raises(ValueError, match="Circular reference detected"):
        dump_yaml_raw(payload)


def test_scanner_terminates_on_reference_cycle() -> None:
    """scan_for_embedded_secrets is public API and looped forever on a cycle."""
    payload: dict = {}
    payload["self"] = payload
    assert scan_for_embedded_secrets(payload) == []


def test_repeated_subtree_is_still_scanned_not_skipped_as_a_cycle() -> None:
    """The cycle guard must bound only the current path, never sibling repeats."""
    leaf = {"cred": GITHUB_TOKEN}
    findings = scan_for_embedded_secrets({"a": leaf, "b": leaf})
    assert {finding.json_path for finding in findings} == {"a.cred", "b.cred"}


# --- scanner Tier A gaps -------------------------------------------------------


def test_credential_shaped_ancestor_key_is_not_echoed_in_a_descendant_path() -> None:
    """json_path rendered an ancestor key verbatim, leaking it via advisory findings."""
    payload = {"adapter_options": {GITHUB_TOKEN: {"opaque": "Zx9Q!kL2mN7pR4sT8vW1yB"}}}
    findings = scan_for_embedded_secrets(payload)
    assert findings, "expected at least the key finding"
    for finding in findings:
        assert GITHUB_TOKEN not in finding.json_path
        assert GITHUB_TOKEN not in finding.redacted_excerpt
    assert any("[redacted:github-token]" in f.json_path for f in findings)


@pytest.mark.parametrize(
    "value",
    [
        # Realistic shapes: long base64url bodies with sparse hyphens.
        "sk-proj-aB3dEf9hIjKlMnOpqrStUvWx-YzAbCdEf9hIjKlMnOpQrStUv",
        "sk-svcacct-aB3dEf9hIjKlMnOpqrStUvWxYz-AbCdEf9hIjKlMn",
        "sk-admin-aB3dEf9hIjKlMnOpqrStUvWx-YzAbCdEf9h",
        "sk-proj-" + "aB3" * 30,
    ],
)
def test_hyphenated_openai_project_key_is_detected(value: str) -> None:
    """base64url bodies contain "-", which the alnum-only body charset missed."""
    assert _match_tier_a(value) == "openai-style-key"
    with pytest.raises(Exception):
        dump_json_raw({"credential": value})


@pytest.mark.parametrize(
    "value",
    [
        "sk-live-feature-toggle",
        "sk-proj-feature-toggle",
        "sk-live-feature-toggle-enabled-for-prod",
        "sk-test-rollout-plan-for-next-quarter",
        # Title-Case vocabulary satisfies "has a digit and an upper-case char".
        "sk-live-Feature-Toggle-2024",
        "sk-test-Migration-Plan-V2",
        "sk-proj-Agent-Foundry-V2-Spec",
        "sk-live-SUE-318-Serialization",
        "sk-live-2024-Q3-Release-Notes",
        "sk-live-Feature-Toggle-2024-Release-Candidate",
        "refs/heads/sk-live-Feature-Toggle-2024",
        "the sk-live-Feature-Toggle-2024 flag is on",
    ],
)
def test_hyphenated_prose_still_serializes(value: str) -> None:
    """Widening the body charset must not start blocking ordinary vocabulary."""
    assert _match_tier_a(value) is None
    dump_json_raw({"note": value})


@pytest.mark.parametrize(
    "header",
    [
        {"alg": "HS256", "typ": "JWT"},
        {"typ": "JWT", "alg": "HS256"},
        {"kid": "abc", "alg": "RS256"},
    ],
)
def test_jwt_detection_is_independent_of_jose_header_member_order(header: dict) -> None:
    """RFC 7515 imposes no ordering; a {"alg prefix test missed typ-first issuers."""
    encoded = base64.urlsafe_b64encode(json.dumps(header).encode()).rstrip(b"=").decode()
    assert _match_tier_a(f"{encoded}.eyJzdWIiOiIxIn0.x") == "jwt"


def test_non_jwt_three_part_token_is_not_flagged_as_jwt() -> None:
    header = base64.urlsafe_b64encode(b'{"typ":"JWT"}').rstrip(b"=").decode()
    assert _match_tier_a(f"{header}.eyJzdWIiOiIxIn0.x") is None


@pytest.mark.parametrize(
    "armor",
    [
        "-----BEGIN PGP PRIVATE KEY BLOCK-----",
        "-----BEGIN RSA PRIVATE KEY-----",
        "-----BEGIN OPENSSH PRIVATE KEY-----",
    ],
)
def test_private_key_armor_variants_are_detected(armor: str) -> None:
    assert _match_tier_a(armor) == "pem-private-key"


def test_deeply_nested_jwt_candidate_does_not_raise_recursion_error() -> None:
    """json.loads raises RecursionError, which is not a ValueError — it must not escape."""
    encoded = base64.urlsafe_b64encode(b"[" * 2000).rstrip(b"=").decode()
    payload = {"note": f"{encoded}.aaaa.bbbb"}
    assert scan_for_embedded_secrets(payload) == []
    dump_json_raw(payload)
    dump_yaml_raw(payload)


@pytest.mark.parametrize("key", [None, True, False, 1.5, 7])
def test_non_string_key_diagnostic_path_is_addressable_by_allow_paths(key: object) -> None:
    """A reported path is only useful if it can actually be pasted back into allow_paths."""
    payload = {key: {"tok": GITHUB_TOKEN}}
    findings = scan_for_embedded_secrets(payload)
    assert findings, f"expected a finding under key {key!r}"
    reported = findings[0].json_path
    assert GITHUB_TOKEN not in reported

    # Round-trips structurally, and actually suppresses the finding at that path.
    assert parse_allow_path(reported) == findings[0].path_segments
    dump_json_raw(payload, allow_paths=(reported,))


def test_int_key_uses_int_repr_not_str() -> None:
    """int.__repr__ is what json.encoder uses; a subclass may override __str__."""

    class Weird(int):
        def __str__(self) -> str:
            return "WEIRD"

    assert dump_json_raw({Weird(5): "a"}).decode().strip() == '{"5":"a"}'
