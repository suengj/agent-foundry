"""Deterministic YAML/JSON load and dump helpers.

Key ordering: sort_keys=True for both JSON and YAML to ensure byte-stable output.
YAML: no anchors/aliases (default PyYAML safe_dump behaviour).
Encoding: UTF-8 with trailing newline on every dump.
"""

from __future__ import annotations

import json
from typing import Any, TypeVar

import yaml

from agent_foundry.models.base import FoundryModel

T = TypeVar("T", bound=FoundryModel)


def _normalize_for_serialization(data: Any) -> Any:
    if isinstance(data, dict):
        return {key: _normalize_for_serialization(value) for key, value in sorted(data.items())}
    if isinstance(data, list):
        return [_normalize_for_serialization(item) for item in data]
    return data


def dump_json(model: FoundryModel) -> bytes:
    """Serialize a model to deterministic UTF-8 JSON bytes with trailing newline."""
    payload = _normalize_for_serialization(model.model_dump(mode="json"))
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return (text + "\n").encode("utf-8")


def load_json(model_type: type[T], data: bytes | str) -> T:
    """Parse UTF-8 JSON bytes or str into a validated model."""
    if isinstance(data, bytes):
        text = data.decode("utf-8")
    else:
        text = data
    parsed = json.loads(text)
    return model_type.model_validate(parsed)


def dump_yaml(model: FoundryModel) -> bytes:
    """Serialize a model to deterministic UTF-8 YAML bytes with trailing newline."""
    payload = _normalize_for_serialization(model.model_dump(mode="json"))
    text = yaml.safe_dump(
        payload,
        sort_keys=True,
        default_flow_style=False,
        allow_unicode=True,
    )
    if not text.endswith("\n"):
        text += "\n"
    return text.encode("utf-8")


def load_yaml(model_type: type[T], data: bytes | str) -> T:
    """Parse UTF-8 YAML bytes or str into a validated model."""
    if isinstance(data, bytes):
        text = data.decode("utf-8")
    else:
        text = data
    parsed = yaml.safe_load(text)
    return model_type.model_validate(parsed)


def parse_json(text: bytes | str) -> Any:
    """Parse JSON without model validation — for byte-stable re-dump tests."""
    if isinstance(text, bytes):
        text = text.decode("utf-8")
    return json.loads(text)


def parse_yaml(text: bytes | str) -> Any:
    """Parse YAML without model validation — for byte-stable re-dump tests."""
    if isinstance(text, bytes):
        text = text.decode("utf-8")
    return yaml.safe_load(text)


def dump_json_raw(data: Any) -> bytes:
    """Dump arbitrary JSON-serializable data deterministically."""
    normalized = _normalize_for_serialization(data)
    text = json.dumps(normalized, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return (text + "\n").encode("utf-8")


def dump_yaml_raw(data: Any) -> bytes:
    """Dump arbitrary YAML-serializable data deterministically."""
    normalized = _normalize_for_serialization(data)
    text = yaml.safe_dump(
        normalized,
        sort_keys=True,
        default_flow_style=False,
        allow_unicode=True,
    )
    if not text.endswith("\n"):
        text += "\n"
    return text.encode("utf-8")
