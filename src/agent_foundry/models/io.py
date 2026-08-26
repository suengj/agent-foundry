"""Deterministic YAML/JSON load and dump helpers.

Key ordering: sort_keys=True for both JSON and YAML to ensure byte-stable output.
YAML: no anchors/aliases (enforced by _NoAliasDumper).
Encoding: UTF-8 with trailing newline on every dump.
"""

from __future__ import annotations

import json
from typing import Any, TypeVar

import yaml

from agent_foundry.models.base import FoundryModel
from agent_foundry.secrets import raise_on_embedded_secrets

T = TypeVar("T", bound=FoundryModel)


def _sort_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


class _NoAliasDumper(yaml.SafeDumper):
    """Expand every occurrence of a shared node instead of emitting anchors/aliases.

    Normalization memoizes by object identity, so a subtree reachable from several
    positions is installed as the *same* object. PyYAML would render that as an
    anchor plus aliases, changing the bytes and making a round-trip return shared
    mutable objects rather than independent copies.
    """

    def ignore_aliases(self, data: Any) -> bool:
        return True


def _json_key(key: Any) -> str:
    """Coerce a mapping key exactly as ``json.encoder`` does before quoting it."""
    if isinstance(key, str):
        return key
    if isinstance(key, bool):
        return "true" if key else "false"
    if key is None:
        return "null"
    if isinstance(key, int):
        return int.__repr__(key)
    if isinstance(key, float):
        if key != key:
            return "NaN"
        if key == float("inf"):
            return "Infinity"
        if key == float("-inf"):
            return "-Infinity"
        return float.__repr__(key)
    raise TypeError(f"keys must be str, int, float, bool or None, not {type(key).__name__}")


def _normalize_for_serialization(data: Any) -> Any:
    if not isinstance(data, (dict, list, tuple, set, frozenset)):
        return data

    memo: dict[int, Any] = {}
    post_order: list[Any] = []
    stack: list[tuple[Any, bool]] = [(data, False)]
    visiting: set[int] = set()

    while stack:
        node, post = stack.pop()
        if not isinstance(node, (dict, list, tuple, set, frozenset)):
            memo[id(node)] = node
            continue
        node_id = id(node)
        if post:
            post_order.append(node)
            continue
        if node_id in visiting:
            continue
        visiting.add(node_id)
        stack.append((node, True))
        if isinstance(node, dict):
            for key in sorted(node.keys(), reverse=True):
                stack.append((node[key], False))
        elif isinstance(node, (list, tuple)):
            for item in reversed(node):
                stack.append((item, False))
        elif isinstance(node, (set, frozenset)):
            for item in reversed(sorted(node, key=_sort_key)):
                stack.append((item, False))

    # A child missing from memo means it was skipped as already-visiting, i.e. a cycle.
    try:
        for node in post_order:
            node_id = id(node)
            if isinstance(node, dict):
                memo[node_id] = {key: memo[id(node[key])] for key in sorted(node.keys())}
            elif isinstance(node, list):
                memo[node_id] = [memo[id(item)] for item in node]
            elif isinstance(node, tuple):
                memo[node_id] = [memo[id(item)] for item in node]
            elif isinstance(node, (set, frozenset)):
                sorted_items = sorted(node, key=_sort_key)
                memo[node_id] = [memo[id(item)] for item in sorted_items]
    except KeyError as exc:
        raise ValueError("Circular reference detected") from exc

    if id(data) not in memo:
        raise ValueError("Circular reference detected")
    return memo[id(data)]


def _json_dumps_deterministic(data: Any) -> str:
    """Serialize normalized trees without deep recursion in the JSON encoder."""
    if not isinstance(data, (dict, list)):
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    memo: dict[int, str] = {}
    post_order: list[Any] = []
    stack: list[tuple[Any, bool]] = [(data, False)]
    visiting: set[int] = set()

    while stack:
        node, post = stack.pop()
        if not isinstance(node, (dict, list)):
            memo[id(node)] = json.dumps(node, ensure_ascii=False, separators=(",", ":"))
            continue
        node_id = id(node)
        if post:
            post_order.append(node)
            continue
        if node_id in visiting:
            continue
        visiting.add(node_id)
        stack.append((node, True))
        if isinstance(node, dict):
            for key in sorted(node.keys(), reverse=True):
                stack.append((node[key], False))
        else:
            for item in reversed(node):
                stack.append((item, False))

    try:
        for node in post_order:
            node_id = id(node)
            if isinstance(node, dict):
                items = [
                    f"{json.dumps(_json_key(key), ensure_ascii=False, separators=(',', ':'))}"
                    f":{memo[id(node[key])]}"
                    for key in sorted(node.keys())
                ]
                memo[node_id] = "{" + ",".join(items) + "}"
            else:
                memo[node_id] = "[" + ",".join(memo[id(item)] for item in node) + "]"
    except KeyError as exc:
        raise ValueError("Circular reference detected") from exc

    if id(data) not in memo:
        raise ValueError("Circular reference detected")
    return memo[id(data)]


def dump_json(model: FoundryModel, *, allow_paths: tuple[str, ...] = ()) -> bytes:
    """Serialize a model to deterministic UTF-8 JSON bytes with trailing newline."""
    payload = _normalize_for_serialization(model.model_dump(mode="json"))
    raise_on_embedded_secrets(payload, allow_paths=allow_paths)
    text = _json_dumps_deterministic(payload)
    return (text + "\n").encode("utf-8")


def load_json(model_type: type[T], data: bytes | str) -> T:
    """Parse UTF-8 JSON bytes or str into a validated model."""
    if isinstance(data, bytes):
        text = data.decode("utf-8")
    else:
        text = data
    parsed = json.loads(text)
    return model_type.model_validate(parsed)


def dump_yaml(model: FoundryModel, *, allow_paths: tuple[str, ...] = ()) -> bytes:
    """Serialize a model to deterministic UTF-8 YAML bytes with trailing newline."""
    payload = _normalize_for_serialization(model.model_dump(mode="json"))
    raise_on_embedded_secrets(payload, allow_paths=allow_paths)
    text = yaml.dump(
        payload,
        Dumper=_NoAliasDumper,
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


def dump_json_raw(data: Any, *, allow_paths: tuple[str, ...] = ()) -> bytes:
    """Dump arbitrary JSON-serializable data deterministically."""
    normalized = _normalize_for_serialization(data)
    raise_on_embedded_secrets(normalized, allow_paths=allow_paths)
    text = _json_dumps_deterministic(normalized)
    return (text + "\n").encode("utf-8")


def dump_yaml_raw(data: Any, *, allow_paths: tuple[str, ...] = ()) -> bytes:
    """Dump arbitrary YAML-serializable data deterministically."""
    normalized = _normalize_for_serialization(data)
    raise_on_embedded_secrets(normalized, allow_paths=allow_paths)
    text = yaml.dump(
        normalized,
        Dumper=_NoAliasDumper,
        sort_keys=True,
        default_flow_style=False,
        allow_unicode=True,
    )
    if not text.endswith("\n"):
        text += "\n"
    return text.encode("utf-8")
