"""FoundryModel base, schema-version machinery, and contract errors."""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Annotated, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, model_validator

FOUNDRY_SCHEMA_VERSION = "0.1"

_RAW_SECRET_KEY_PATTERN = re.compile(
    r"^(api_key|apikey|token|secret|password|passwd|private_key|"
    r"client_secret|access_key|credential|authorization)$",
    re.IGNORECASE,
)


class FoundryModelError(Exception):
    """Base error for Foundry contract failures."""


class SchemaCompatibilityError(FoundryModelError):
    """Raised when a contract schema_version is incompatible with the supported version."""


class RawSecretError(FoundryModelError):
    """Raised when a mapping field appears to carry raw secret material."""


class EmbeddedSecretError(FoundryModelError):
    """Raised when serialized output would embed credential-shaped secret material."""

    def __init__(
        self,
        *,
        json_path: str,
        rule_name: str,
        redacted_excerpt: str,
    ) -> None:
        self.json_path = json_path
        self.rule_name = rule_name
        self.redacted_excerpt = redacted_excerpt
        super().__init__(
            f"embedded secret at {json_path}: rule={rule_name} ({redacted_excerpt})"
        )


class WorkDecompositionError(FoundryModelError):
    """Base error for work decomposition failures."""


class DependencyGraphError(WorkDecompositionError):
    """Raised when the work-item dependency graph is invalid."""

    def __init__(
        self,
        message: str,
        *,
        node_ids: list[str] | None = None,
        cycle_path: list[str] | None = None,
    ) -> None:
        ordered = cycle_path if cycle_path is not None else (node_ids or [])
        self.cycle_path = list(ordered)
        self.node_ids = sorted(node_ids if node_ids is not None else self.cycle_path)
        detail = message
        if self.cycle_path:
            detail = f"{message}: {' -> '.join(self.cycle_path)}"
        elif self.node_ids:
            detail = f"{message}: {', '.join(self.node_ids)}"
        super().__init__(detail)


def parse_schema_version(version: str) -> tuple[int, int]:
    parts = version.split(".")
    if len(parts) != 2:
        raise ValueError(f"schema_version must be MAJOR.MINOR, got {version!r}")
    try:
        major, minor = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise ValueError(f"schema_version must be MAJOR.MINOR, got {version!r}") from exc
    return major, minor


def validate_schema_compatibility(contract_name: str, found_version: str) -> None:
    found_major, found_minor = parse_schema_version(found_version)
    supported_major, supported_minor = parse_schema_version(FOUNDRY_SCHEMA_VERSION)
    if found_major != supported_major:
        raise SchemaCompatibilityError(
            f"{contract_name}: schema_version {found_version} is incompatible with "
            f"supported version {FOUNDRY_SCHEMA_VERSION} (major mismatch)"
        )
    if found_minor > supported_minor:
        raise SchemaCompatibilityError(
            f"{contract_name}: schema_version {found_version} is incompatible with "
            f"supported version {FOUNDRY_SCHEMA_VERSION} (minor newer than supported)"
        )


def _redact_path_segment(segment: str) -> str:
    """Never echo a credential-shaped mapping key inside a diagnostic path."""
    from agent_foundry.secrets import _match_tier_a

    rule = _match_tier_a(segment)
    return f"[redacted:{rule}]" if rule is not None else segment


def lint_no_raw_secrets(value: Any, path: str = "") -> None:
    """Reject mapping keys that resemble credential material unless value is SecretRef."""
    # SecretRef imported lazily to avoid circular import at module load.
    from agent_foundry.models.integrations import SecretRef

    if isinstance(value, SecretRef):
        return
    if isinstance(value, BaseModel):
        for field_name in type(value).model_fields:
            field_value = getattr(value, field_name)
            child_path = f"{path}.{field_name}" if path else field_name
            lint_no_raw_secrets(field_value, child_path)
        return
    if isinstance(value, Enum):
        return
    if isinstance(value, dict):
        for key, child in value.items():
            safe_key = _redact_path_segment(str(key))
            key_path = f"{path}.{safe_key}" if path else safe_key
            if _RAW_SECRET_KEY_PATTERN.match(str(key)):
                if not isinstance(child, SecretRef):
                    if isinstance(child, dict) and {"provider", "name"} <= set(child.keys()):
                        try:
                            SecretRef.model_validate(child)
                            continue
                        except Exception:
                            pass
                    if isinstance(child, str) and ":" in child:
                        try:
                            SecretRef.model_validate(child)
                            continue
                        except Exception:
                            pass
                    contract = path.split(".")[0] if path else "contract"
                    raise RawSecretError(
                        f"{contract}: raw secret key {key!r} at {key_path} "
                        "must use SecretRef, not raw value"
                    )
            lint_no_raw_secrets(child, key_path)
        return
    if isinstance(value, (list, tuple)):
        for idx, item in enumerate(value):
            lint_no_raw_secrets(item, f"{path}[{idx}]")


def _validate_free_form_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("free-form mapping must be a dict")
    return value


FreeFormMapping = Annotated[dict[str, Any], BeforeValidator(_validate_free_form_mapping)]


class FoundryModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_assignment=True,
        use_enum_values=False,
    )

    @model_validator(mode="after")
    def _lint_no_raw_secrets_tree(self) -> Self:
        lint_no_raw_secrets(self, self.__class__.__name__)
        return self


class VersionedContract(FoundryModel):
    """Mixin-style base for separately-persisted contracts carrying schema_version."""

    schema_version: str

    @model_validator(mode="after")
    def _validate_schema_version(self) -> Self:
        validate_schema_compatibility(self.__class__.__name__, self.schema_version)
        return self


def serialize_datetime_utc(value: Any) -> str:
    """Serialize datetimes to canonical ISO-8601 UTC (Z suffix)."""
    from datetime import datetime, timezone

    if not isinstance(value, datetime):
        raise TypeError(f"expected datetime, got {type(value)!r}")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")
