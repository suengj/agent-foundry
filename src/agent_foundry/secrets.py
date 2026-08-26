"""Embedded-secret detection at the serialization (write/render) boundary."""

from __future__ import annotations

import base64
import binascii
import json
import math
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class KeyPathMarker:
    """Sentinel path segment: the credential was carried as a dict key, not a value."""


KEY_PATH_MARKER = KeyPathMarker()

PathSegment = str | int | KeyPathMarker

_SHA1_HEX_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_ISO8601_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
_LOWERCASE_HEX_RE = re.compile(r"^[0-9a-f]+$")
_DECIMAL_RE = re.compile(r"^[0-9]+$")
_POSIX_PATH_RE = re.compile(r"^(?:/|\./|\.\./).+")

_TOKEN_BOUNDARY = r"(?<![A-Za-z0-9_-])"

# Weak prefix: sk- collides with ordinary language — optional closed label set, then unbroken body.
_OPENAI_KNOWN_LABELS = "(?:live|test|proj|svcacct|admin)"
_OPENAI_STYLE_KEY_RE = re.compile(
    _TOKEN_BOUNDARY
    + rf"(?:sk-(?:{_OPENAI_KNOWN_LABELS})-[A-Za-z0-9_]{{16,}}|sk-[A-Za-z0-9_]{{16,}})"
)

# Real project/service-account keys are base64url, so the body may contain "-". A hyphenated
# body cannot be distinguished from a dictionary phrase ("sk-live-feature-toggle-enabled") by
# shape alone, so a hyphenated body additionally requires a digit and an upper-case character.
# Prose keeps serializing; a genuine base64url key of 16+ chars effectively always qualifies.
_OPENAI_HYPHENATED_KEY_RE = re.compile(
    _TOKEN_BOUNDARY + rf"sk-{_OPENAI_KNOWN_LABELS}-([A-Za-z0-9_-]{{16,}})"
)


def _match_openai_style_key(value: str) -> bool:
    if _OPENAI_STYLE_KEY_RE.search(value):
        return True
    for match in _OPENAI_HYPHENATED_KEY_RE.finditer(value):
        body = match.group(1)
        if any(c.isdigit() for c in body) and any(c.isupper() for c in body):
            return True
    return False

# Strong prefixes: unambiguous on their own — match prefix + documented body length/charset only.
_TIER_A_STRONG_RULE_BODIES: tuple[tuple[str, str], ...] = (
    (
        "github-token",
        r"(?:gh[opurs]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})",
    ),
    ("slack-token", r"xox[bpars]-[A-Za-z0-9-]{10,}"),
    ("aws-access-key", r"(?:AKIA|ASIA)[A-Z0-9]{16}"),
    ("google-api-key", r"AIza[0-9A-Za-z_-]{35}"),
    ("gitlab-pat", r"glpat-[A-Za-z0-9_-]{10,}"),
    ("npm-token", r"npm_[A-Za-z0-9]{10,}"),
    ("doppler-token", r"dop_v1_[A-Za-z0-9]{10,}"),
    ("stripe-secret-key", r"sk_live_[A-Za-z0-9]{10,}"),
    ("stripe-publishable-key", r"pk_live_[A-Za-z0-9]{10,}"),
    ("pem-private-key", r"-----BEGIN[A-Z ]*PRIVATE KEY[A-Z ]*-----"),
)

_TIER_A_STRONG_RULES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (rule_name, re.compile(_TOKEN_BOUNDARY + body))
    for rule_name, body in _TIER_A_STRONG_RULE_BODIES
)

_TIER_B_MIN_LENGTH = 20
_TIER_B_ENTROPY_THRESHOLD = 4.2

_JWT_CANDIDATE_RE = re.compile(
    _TOKEN_BOUNDARY + r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"
)


class ConfidenceTier(StrEnum):
    TIER_A = "tier-a-known-format"
    TIER_B = "tier-b-entropy"


@dataclass(frozen=True)
class SecretFinding:
    json_path: str
    rule_name: str
    confidence_tier: ConfidenceTier
    redacted_excerpt: str
    path_segments: tuple[PathSegment, ...]


def _redact(value: str, rule_name: str) -> str:
    prefix = value[:4]
    return f"{prefix}… (len={len(value)}, rule={rule_name})"


def _shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts: dict[str, int] = {}
    for char in value:
        counts[char] = counts.get(char, 0) + 1
    length = len(value)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def _char_class_count(value: str) -> int:
    classes = 0
    if any(char.islower() for char in value):
        classes += 1
    if any(char.isupper() for char in value):
        classes += 1
    if any(char.isdigit() for char in value):
        classes += 1
    if any(not char.isalnum() for char in value):
        classes += 1
    return classes


def _is_well_formed_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _is_safe_url(value: str) -> bool:
    if not _is_well_formed_http_url(value):
        return False
    return _match_tier_a(value) is None


def _is_entropy_exempt(value: str) -> bool:
    if _SHA1_HEX_RE.fullmatch(value):
        return True
    if _SHA256_HEX_RE.fullmatch(value):
        return True
    if _UUID_RE.fullmatch(value):
        return True
    if _ISO8601_RE.fullmatch(value):
        return True
    if _SEMVER_RE.fullmatch(value):
        return True
    if _LOWERCASE_HEX_RE.fullmatch(value):
        return True
    if _DECIMAL_RE.fullmatch(value):
        return True
    if _POSIX_PATH_RE.fullmatch(value):
        return True
    if _is_safe_url(value):
        return True
    return False


def _is_jwt(value: str) -> bool:
    parts = value.split(".")
    if len(parts) != 3:
        return False
    header_segment = parts[0]
    if not header_segment:
        return False
    try:
        padded = header_segment + "=" * (-len(header_segment) % 4)
        decoded = base64.urlsafe_b64decode(padded)
    except (ValueError, binascii.Error):
        return False
    # RFC 7515 imposes no member ordering on the JOSE header, so a prefix test on {"alg
    # misses any issuer that emits typ/kid first. Parse and look the member up instead.
    try:
        header = json.loads(decoded)
    except (ValueError, UnicodeDecodeError):
        return False
    return isinstance(header, dict) and "alg" in header


def _find_jwt(value: str) -> bool:
    for match in _JWT_CANDIDATE_RE.finditer(value):
        if _is_jwt(match.group(0)):
            return True
    return False


def _match_tier_a(value: str) -> str | None:
    if _find_jwt(value):
        return "jwt"
    if _match_openai_style_key(value):
        return "openai-style-key"
    for rule_name, pattern in _TIER_A_STRONG_RULES:
        if pattern.search(value):
            return rule_name
    return None


def parse_allow_path(path: str) -> tuple[PathSegment, ...]:
    """Parse a dotted allow-path into structural segments.

    Dots separate nesting. Escape a literal dot inside a key with ``\\.``.
    Bracket ``[key]`` marks a dict-key credential (``KeyPathMarker``), not a
    literal key named ``@key``. Bracket ``[0]`` selects a list index. An empty
    string key is encoded as ``\\0``.
    """
    segments: list[PathSegment] = []
    token = ""
    index = 0
    length = len(path)

    while index < length:
        char = path[index]
        if char == "\\" and index + 1 < length:
            next_char = path[index + 1]
            if next_char == "0":
                if token:
                    raise ValueError(
                        f"empty-segment escape must be a full segment in allow path: {path!r}"
                    )
                segments.append("")
                index += 2
                continue
            token += next_char
            index += 2
            continue
        if char == "[":
            if token:
                segments.append(token)
                token = ""
            index += 1
            bracket = ""
            while index < length and path[index] != "]":
                bracket += path[index]
                index += 1
            if index >= length:
                raise ValueError(f"unclosed bracket in allow path: {path!r}")
            index += 1
            if bracket == "key":
                segments.append(KEY_PATH_MARKER)
            elif bracket.isdigit():
                segments.append(int(bracket))
            else:
                raise ValueError(f"invalid bracket segment in allow path: {path!r}")
            continue
        if char == ".":
            if token:
                segments.append(token)
                token = ""
            index += 1
            continue
        token += char
        index += 1

    if token:
        segments.append(token)
    return tuple(segments)


def _escape_path_segment(segment: str) -> str:
    if segment == "":
        return "\\0"
    return (
        segment.replace("\\", "\\\\")
        .replace(".", "\\.")
        .replace("[", "\\[")
        .replace("]", "\\]")
    )


def format_json_path(segments: tuple[PathSegment, ...]) -> str:
    """Format structural path segments for allow_paths round-trip diagnostics."""
    if not segments:
        return ""

    rendered: list[str] = []
    for segment in segments:
        if isinstance(segment, KeyPathMarker):
            rendered.append("[key]")
        elif isinstance(segment, bool) or not isinstance(segment, (str, int)):
            # Defensive: a non-str/int mapping key must never crash the guard.
            rendered.append(_escape_path_segment(str(segment)))
        elif isinstance(segment, int):
            rendered.append(f"[{segment}]")
        elif _match_tier_a(segment) is not None:
            # An ancestor key that is itself a credential must not be echoed in the
            # diagnostic for a descendant finding. Such a path is intentionally not
            # pasteable into allow_paths: the fix is to remove the credential, not
            # to allow the path.
            rendered.append(f"[redacted:{_match_tier_a(segment)}]")
        else:
            rendered.append(_escape_path_segment(segment))

    result = ""
    for part in rendered:
        if part.startswith("[") and part.endswith("]"):
            result += part
            continue
        if not result:
            result = part
        else:
            result += f".{part}"
    return result


def _key_path_segments(parent_segments: tuple[PathSegment, ...]) -> tuple[PathSegment, ...]:
    return (*parent_segments, KEY_PATH_MARKER)


def _scan_key(segments: tuple[PathSegment, ...], key: str) -> list[SecretFinding]:
    tier_a_rule = _match_tier_a(key)
    if tier_a_rule is None:
        return []
    path = format_json_path(segments)
    return [
        SecretFinding(
            json_path=path,
            rule_name=tier_a_rule,
            confidence_tier=ConfidenceTier.TIER_A,
            redacted_excerpt=_redact(key, tier_a_rule),
            path_segments=segments,
        )
    ]


def _match_tier_b(value: str) -> str | None:
    if len(value) < _TIER_B_MIN_LENGTH:
        return None
    if _is_well_formed_http_url(value) and _match_tier_a(value) is None:
        return None
    if _is_entropy_exempt(value):
        return None
    if _match_tier_a(value) is not None:
        return None
    if _char_class_count(value) < 3:
        return None
    if _shannon_entropy(value) < _TIER_B_ENTROPY_THRESHOLD:
        return None
    return "high-entropy"


def _scan_value(segments: tuple[PathSegment, ...], value: str) -> list[SecretFinding]:
    path = format_json_path(segments)
    tier_a_rule = _match_tier_a(value)
    if tier_a_rule is not None:
        return [
            SecretFinding(
                json_path=path,
                rule_name=tier_a_rule,
                confidence_tier=ConfidenceTier.TIER_A,
                redacted_excerpt=_redact(value, tier_a_rule),
                path_segments=segments,
            )
        ]

    tier_b_rule = _match_tier_b(value)
    if tier_b_rule is not None:
        return [
            SecretFinding(
                json_path=path,
                rule_name=tier_b_rule,
                confidence_tier=ConfidenceTier.TIER_B,
                redacted_excerpt=_redact(value, tier_b_rule),
                path_segments=segments,
            )
        ]

    return []


def _is_sequence(value: Any) -> bool:
    return isinstance(value, (list, tuple, set, frozenset))


def _scan_node(value: Any) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    # Ancestors travel with each stack entry: a container may legitimately appear at several
    # positions, but re-entering one already on its own path would not terminate on a cycle.
    stack: list[tuple[tuple[PathSegment, ...], Any, frozenset[int]]] = [((), value, frozenset())]

    while stack:
        segments, current, ancestors = stack.pop()

        if isinstance(current, (dict, list, tuple, set, frozenset)):
            if id(current) in ancestors:
                continue
            ancestors = ancestors | {id(current)}

        if isinstance(current, dict):
            for key, child in current.items():
                if isinstance(key, str):
                    findings.extend(_scan_key(_key_path_segments(segments), key))
                stack.append(((*segments, key), child, ancestors))
            continue

        if _is_sequence(current):
            for index, item in enumerate(current):
                stack.append(((*segments, index), item, ancestors))
            continue

        if isinstance(current, str):
            findings.extend(_scan_value(segments, current))

    return findings


def scan_for_embedded_secrets(
    data: Any,
    *,
    allow_paths: tuple[str, ...] = (),
) -> list[SecretFinding]:
    """Scan serialized data for embedded secret-shaped values."""
    allowed = {parse_allow_path(path) for path in allow_paths}
    findings = _scan_node(data)
    if not allowed:
        return findings
    return [finding for finding in findings if finding.path_segments not in allowed]


def raise_on_embedded_secrets(
    data: Any,
    *,
    allow_paths: tuple[str, ...] = (),
) -> None:
    """Raise EmbeddedSecretError on Tier A findings not covered by allow_paths."""
    from agent_foundry.models.base import EmbeddedSecretError

    allowed = {parse_allow_path(path) for path in allow_paths}
    for finding in _scan_node(data):
        if finding.confidence_tier == ConfidenceTier.TIER_A and finding.path_segments not in allowed:
            raise EmbeddedSecretError(
                json_path=finding.json_path,
                rule_name=finding.rule_name,
                redacted_excerpt=finding.redacted_excerpt,
            )
