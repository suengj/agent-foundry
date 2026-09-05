"""ProjectProfile: descriptive truth that stays deterministic and grants nothing.

The tests here are written against the properties the contract has to hold, not
against its field list: that a profile can never become a place authority is
declared, that "we don't know" and "the sources disagree" survive as first-class
outcomes, and that two semantically equal profiles serialize to identical bytes.
"""

from __future__ import annotations

import typing

import pytest
from pydantic import BaseModel, ValidationError

from agent_foundry.models import (
    ProfileAttribution,
    ProfileDimension,
    ProfileResolution,
    ProjectAuthority,
    ProjectProfile,
    Provenance,
    ProvenanceKind,
    SchemaCompatibilityError,
    dump_json,
    dump_yaml,
    load_json,
    load_yaml,
)

AUTHORITY_FIELD_NAMES = frozenset(
    {"write_scope", "authority", "permissions", "scopes", "grants", "allow"}
)


def _attribution(value: str, kind: ProvenanceKind) -> ProfileAttribution:
    return ProfileAttribution(
        value=value,
        provenance=Provenance(kind=kind, confidence=0.5, source_ref=f"ref/{value}"),
        evidence_refs=[f"ref/{value}#L1"],
    )


def _sample_profile() -> ProjectProfile:
    return ProjectProfile(
        schema_version="0.1",
        project_name="sample-service",
        source_intake_ref="intake://sample-service/rev-1",
        dimensions=[
            ProfileDimension(
                dimension="primary-artifact",
                resolution=ProfileResolution.RESOLVED,
                attributions=[_attribution("service", ProvenanceKind.OBSERVED)],
            ),
            ProfileDimension(
                dimension="release-cadence",
                resolution=ProfileResolution.CONFLICTED,
                attributions=[
                    _attribution("continuous", ProvenanceKind.OBSERVED),
                    _attribution("scheduled", ProvenanceKind.DECLARED),
                ],
            ),
            ProfileDimension(
                dimension="data-sensitivity",
                resolution=ProfileResolution.UNKNOWN,
            ),
        ],
    )


def _model_types(annotation: object) -> list[type[BaseModel]]:
    """Every pydantic model reachable from a field annotation, unwrapping containers."""
    found: list[type[BaseModel]] = []
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        found.append(annotation)
    for arg in typing.get_args(annotation):
        found.extend(_model_types(arg))
    return found


def _walk_fields(model: type[BaseModel]) -> list[tuple[str, str, object]]:
    """(owner, field name, annotation) for the whole recursive field tree."""
    seen: set[type[BaseModel]] = set()
    rows: list[tuple[str, str, object]] = []
    queue: list[type[BaseModel]] = [model]
    while queue:
        current = queue.pop()
        if current in seen:
            continue
        seen.add(current)
        for name, field in current.model_fields.items():
            rows.append((current.__name__, name, field.annotation))
            for nested in _model_types(field.annotation):
                if nested not in seen:
                    queue.append(nested)
    return rows


def test_field_walk_actually_reaches_nested_models() -> None:
    """Guard the guard: an empty walk would make the authority test vacuous."""
    rows = _walk_fields(ProjectProfile)
    owners = {owner for owner, _, _ in rows}
    assert {"ProjectProfile", "ProfileDimension", "ProfileAttribution", "Provenance"} <= owners
    # And the same walk must be able to see authority when it is genuinely there.
    manifest_rows = _walk_fields(ProjectAuthority)
    assert any(name in AUTHORITY_FIELD_NAMES for _, name, _ in manifest_rows)


def test_profile_carries_no_authority_bearing_field_anywhere() -> None:
    offenders = []
    for owner, name, annotation in _walk_fields(ProjectProfile):
        if name in AUTHORITY_FIELD_NAMES:
            offenders.append(f"{owner}.{name}")
        if ProjectAuthority in _model_types(annotation):
            offenders.append(f"{owner}.{name}:ProjectAuthority")
    assert offenders == [], (
        f"ProjectProfile reaches authority-bearing field(s): {offenders}. A profile is "
        "descriptive; it must never be a place where authority is granted."
    )


def test_unknown_dimension_may_not_carry_attributions() -> None:
    with pytest.raises(ValidationError):
        ProfileDimension(
            dimension="data-sensitivity",
            resolution=ProfileResolution.UNKNOWN,
            attributions=[_attribution("internal", ProvenanceKind.OBSERVED)],
        )


def test_dimension_without_attributions_cannot_be_resolved() -> None:
    with pytest.raises(ValidationError):
        ProfileDimension(
            dimension="primary-artifact",
            resolution=ProfileResolution.RESOLVED,
        )


def test_resolved_allows_the_same_value_from_several_sources() -> None:
    dimension = ProfileDimension(
        dimension="primary-artifact",
        resolution=ProfileResolution.RESOLVED,
        attributions=[
            _attribution("service", ProvenanceKind.OBSERVED),
            ProfileAttribution(
                value="service",
                provenance=Provenance(kind=ProvenanceKind.DECLARED),
            ),
        ],
    )
    assert len(dimension.attributions) == 2


def test_resolved_rejects_two_distinct_values() -> None:
    with pytest.raises(ValidationError):
        ProfileDimension(
            dimension="release-cadence",
            resolution=ProfileResolution.RESOLVED,
            attributions=[
                _attribution("continuous", ProvenanceKind.OBSERVED),
                _attribution("scheduled", ProvenanceKind.DECLARED),
            ],
        )


def test_conflicted_requires_two_distinct_values() -> None:
    with pytest.raises(ValidationError):
        ProfileDimension(
            dimension="release-cadence",
            resolution=ProfileResolution.CONFLICTED,
            attributions=[
                _attribution("continuous", ProvenanceKind.OBSERVED),
                ProfileAttribution(
                    value="continuous",
                    provenance=Provenance(kind=ProvenanceKind.DECLARED),
                ),
            ],
        )


def test_conflict_survives_a_full_round_trip_with_both_provenances() -> None:
    restored = load_json(ProjectProfile, dump_json(_sample_profile()))
    conflicted = [
        dimension
        for dimension in restored.dimensions
        if dimension.resolution is ProfileResolution.CONFLICTED
    ]
    assert len(conflicted) == 1
    attributions = conflicted[0].attributions
    assert {attribution.value for attribution in attributions} == {"continuous", "scheduled"}
    assert {attribution.provenance.kind for attribution in attributions} == {
        ProvenanceKind.OBSERVED,
        ProvenanceKind.DECLARED,
    }
    by_value = {attribution.value: attribution for attribution in attributions}
    assert by_value["continuous"].provenance.kind is ProvenanceKind.OBSERVED
    assert by_value["scheduled"].provenance.kind is ProvenanceKind.DECLARED
    assert by_value["scheduled"].evidence_refs == ["ref/scheduled#L1"]


def test_unknown_dimension_survives_round_trip_as_unknown() -> None:
    restored = load_yaml(ProjectProfile, dump_yaml(_sample_profile()))
    unknown = [
        dimension
        for dimension in restored.dimensions
        if dimension.dimension == "data-sensitivity"
    ]
    assert len(unknown) == 1
    assert unknown[0].resolution is ProfileResolution.UNKNOWN
    assert unknown[0].attributions == []


def test_json_and_yaml_dumps_are_byte_stable_through_a_round_trip() -> None:
    profile = _sample_profile()
    json_bytes = dump_json(profile)
    assert json_bytes == dump_json(load_json(ProjectProfile, json_bytes))
    yaml_bytes = dump_yaml(profile)
    assert yaml_bytes == dump_yaml(load_yaml(ProjectProfile, yaml_bytes))


def test_key_ordering_is_stable_across_differently_ordered_constructions() -> None:
    """Two semantically equal profiles built in different field order dump identically."""
    first = ProjectProfile(
        schema_version="0.1",
        project_name="sample-service",
        source_intake_ref="intake://sample-service/rev-1",
        dimensions=[
            ProfileDimension(
                dimension="primary-artifact",
                resolution=ProfileResolution.RESOLVED,
                attributions=[
                    ProfileAttribution(
                        value="service",
                        provenance=Provenance(
                            kind=ProvenanceKind.OBSERVED,
                            confidence=0.5,
                            source_ref="ref/service",
                        ),
                        evidence_refs=["ref/service#L1"],
                    )
                ],
            )
        ],
    )
    second = ProjectProfile(
        dimensions=[
            ProfileDimension(
                attributions=[
                    ProfileAttribution(
                        evidence_refs=["ref/service#L1"],
                        provenance=Provenance(
                            source_ref="ref/service",
                            confidence=0.5,
                            kind=ProvenanceKind.OBSERVED,
                        ),
                        value="service",
                    )
                ],
                resolution=ProfileResolution.RESOLVED,
                dimension="primary-artifact",
            )
        ],
        source_intake_ref="intake://sample-service/rev-1",
        project_name="sample-service",
        schema_version="0.1",
    )
    assert first == second
    assert dump_json(first) == dump_json(second)
    assert dump_yaml(first) == dump_yaml(second)


def _minimal_profile_payload(schema_version: str) -> dict:
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


def test_supported_schema_version_loads() -> None:
    profile = ProjectProfile.model_validate(_minimal_profile_payload("0.1"))
    assert profile.schema_version == "0.1"


def test_incompatible_major_schema_version_raises() -> None:
    with pytest.raises(SchemaCompatibilityError) as exc_info:
        ProjectProfile.model_validate(_minimal_profile_payload("1.0"))
    message = str(exc_info.value)
    assert "ProjectProfile" in message
    assert "1.0" in message


def test_unknown_key_is_rejected() -> None:
    payload = _minimal_profile_payload("0.1")
    payload["write_scope"] = ["src/"]
    with pytest.raises(ValidationError):
        ProjectProfile.model_validate(payload)
