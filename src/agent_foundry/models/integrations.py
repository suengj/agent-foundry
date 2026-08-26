"""Integration declarations, credential references, and health state."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field, field_serializer, field_validator, model_serializer, model_validator

from agent_foundry.models.base import (
    FreeFormMapping,
    FoundryModel,
    VersionedContract,
    serialize_datetime_utc,
)
from agent_foundry.models.common import (
    AuthorityRequirement,
    IntegrationAuthMethod,
    IntegrationHealthState,
    IntegrationKind,
    IntegrationTransport,
    SecretProvider,
)

_STRING_SCHEME_ALIASES: dict[str, SecretProvider] = {
    "env": SecretProvider.ENV,
    "os-keychain": SecretProvider.OS_KEYCHAIN,
    "managed": SecretProvider.MANAGED,
    "vault": SecretProvider.VAULT,
    "workload-identity": SecretProvider.WORKLOAD_IDENTITY,
    "ci-secret": SecretProvider.CI_SECRET,
}


def _parse_secret_ref_string(value: str) -> dict[str, Any]:
    if ":" not in value:
        raise ValueError(f"SecretRef string must be scheme:name, got {value!r}")
    scheme, name = value.split(":", 1)
    if not scheme or not name:
        raise ValueError(f"SecretRef string must be scheme:name, got {value!r}")
    provider = _STRING_SCHEME_ALIASES.get(scheme)
    if provider is None:
        raise ValueError(f"unknown SecretRef scheme {scheme!r}")
    return {"provider": provider, "name": name}


class SecretRef(FoundryModel):
    """Reference coordinates for a credential — never carries secret values.

    Canonical serialization: structured dict with §8 scheme names as provider values.
    String form (scheme:name) is accepted on input only.
    """

    provider: SecretProvider
    name: str
    version: str | None = None
    scope: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_string_form(cls, value: Any) -> Any:
        if isinstance(value, str):
            return _parse_secret_ref_string(value)
        return value

    @model_serializer(mode="plain")
    def _serialize_canonical(self) -> dict[str, Any]:
        data: dict[str, Any] = {"provider": self.provider, "name": self.name}
        if self.version is not None:
            data["version"] = self.version
        if self.scope is not None:
            data["scope"] = self.scope
        return data

    def __repr__(self) -> str:
        parts = [f"provider={self.provider!r}", f"name={self.name!r}"]
        if self.version is not None:
            parts.append(f"version={self.version!r}")
        if self.scope is not None:
            parts.append(f"scope={self.scope!r}")
        return f"SecretRef({', '.join(parts)})"

    def __str__(self) -> str:
        return self.__repr__()


class IntegrationHealth(FoundryModel):
    """Integration lifecycle / health state."""

    integration_id: str
    state: IntegrationHealthState
    message: str | None = None
    checked_at: datetime | None = None

    @field_validator("checked_at", mode="before")
    @classmethod
    def _parse_checked_at(cls, value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        raise TypeError(f"checked_at must be datetime or ISO-8601 string, got {type(value)!r}")

    @field_serializer("checked_at")
    def _serialize_checked_at(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        return serialize_datetime_utc(value)


class IntegrationPermissions(FoundryModel):
    write_requires: AuthorityRequirement


class IntegrationHealthRequirement(FoundryModel):
    required: IntegrationHealthState


class IntegrationAuth(FoundryModel):
    """Nested auth block per docs/foundry/04 §7 and §8."""

    method: IntegrationAuthMethod
    credential_ref: SecretRef


class IntegrationSpec(VersionedContract):
    """Declared integration — credential positions accept SecretRef only."""

    id: str
    kind: IntegrationKind
    transport: IntegrationTransport
    version: str
    capabilities: list[str] = Field(default_factory=list)
    permissions: IntegrationPermissions
    auth: IntegrationAuth | None = None
    health: IntegrationHealthRequirement
    adapter_options: FreeFormMapping = Field(default_factory=dict)
