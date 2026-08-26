"""Work Item compiler, authority intersection, render, and determinism tests."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
from itertools import product
from pathlib import Path

import pytest

from agent_foundry.compile import (
    CompileError,
    compile_work_item,
    compute_compiled_authority,
    validate_execution_bundle_authority,
)
from agent_foundry.compile.authority import (
    CompileAuthorityError,
    _intersect_write_scopes,
    _scope_contained_in_bounds,
)
from agent_foundry.models import (
    ConsequenceClass,
    EmbeddedSecretError,
    ExternalEffectClass,
    ProjectAccess,
    ProjectAssurance,
    ProjectExecution,
    ProjectImpact,
    ProjectInfo,
    ProjectManifest,
    ProjectObservation,
    ProjectState,
    Provenance,
    ProvenanceKind,
    ResolutionSource,
    WorkClass,
    WorkItemContract,
    dump_json,
    dump_yaml,
)
from agent_foundry.models.base import FOUNDRY_SCHEMA_VERSION
from agent_foundry.models.common import PrimaryArtifactState, PrimaryWorkMode
from agent_foundry.models.project import ConventionSpec, WorkModes
from agent_foundry.render import render_execution_bundle_markdown
from agent_foundry.toolkit import default_registry, resolve_toolkit
from agent_foundry.toolkit.builtin_registry import build_default_registry_permission_profiles
from agent_foundry.toolkit.ceiling import EFFECT_RANK

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "valid"
_AWS_SECRET_SAMPLE = "AKIAIOSFODNN7EXAMPLE"
_RENDER_BYTE_CEILING = 2500


def _subprocess_env() -> dict[str, str]:
    return {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}


def _assert_imports_worktree(env: dict[str, str]) -> None:
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "import agent_foundry; print(agent_foundry.__file__)",
        ],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    resolved = Path(probe.stdout.strip()).resolve()
    assert resolved.is_relative_to(REPO_ROOT.resolve())


def _sample_manifest(**overrides: object) -> ProjectManifest:
    base = {
        "schema_version": FOUNDRY_SCHEMA_VERSION,
        "project": {
            "name": "sample-service",
            "intake_mode": "brownfield",
            "work_modes": {"primary": "build"},
            "primary_artifact": "code",
        },
        "state": {"persistence": "persistent-shared-external", "temporal_mode": "long-running"},
        "impact": {
            "external_effect": "repository-write",
            "reversibility": "versioned",
            "consequence": "medium",
        },
        "execution": {
            "autonomy": "bounded-external-write",
            "ambiguity": "bounded-judgment",
            "concurrency": "single-writer",
        },
        "assurance": {"required": ["deterministic-tests"]},
        "access": {"sensitivity": "internal"},
    }
    base.update(overrides)
    return ProjectManifest.model_validate(base)


def _sample_work_item(**overrides: object) -> WorkItemContract:
    base = {
        "schema_version": FOUNDRY_SCHEMA_VERSION,
        "id": "WI-COMPILE-001",
        "title": "Implement toolkit resolver",
        "work_class": "CAPABILITY",
        "objective": "Deliver bounded toolkit changes in src/",
        "current_facts": ["bootstrap exists"],
        "scope": ["src/", "toolkit resolver"],
        "out_of_scope": ["execution runtime"],
        "acceptance_criteria": ["pytest green"],
        "dependencies": [],
        "authority_class": "repository-write",
        "consequence_class": "medium",
        "required_evidence": ["pytest"],
        "stop_conditions": ["cannot express semantics"],
    }
    base.update(overrides)
    return WorkItemContract.model_validate(base)


def _compile_sample(**manifest_overrides: object) -> tuple[bytes, bytes]:
    manifest = _sample_manifest(**manifest_overrides)
    work_item = _sample_work_item()
    _, lock = resolve_toolkit(manifest)
    result = compile_work_item(work_item, manifest, lock, "builder", "RUN-COMPILE-001")
    bundle_bytes = dump_json(result.bundle)
    markdown_bytes = render_execution_bundle_markdown(result.bundle).encode("utf-8")
    return bundle_bytes, markdown_bytes


def test_compile_produces_task_toolkit_subset_and_bundle():
    manifest = _sample_manifest()
    work_item = _sample_work_item()
    _, lock = resolve_toolkit(manifest)
    result = compile_work_item(work_item, manifest, lock, "builder", "RUN-001")

    assert result.task_toolkit.work_item_id == work_item.id
    assert set(result.task_toolkit.capability_ids) <= set(lock.capability_ids)
    assert set(result.task_toolkit.skill_ids) <= set(lock.skill_ids)
    assert result.bundle.work_item_id == work_item.id
    assert result.bundle.role_id == "builder"
    assert result.bundle.authority is not None
    assert result.bundle.task_toolkit is not None
    assert result.bundle.provenance


def test_authority_intersection_cannot_exceed_work_item_role_toolkit_or_policy():
    """Named authority-intersection test — compiled authority must not exceed any bound."""
    manifest = _sample_manifest()
    work_item = _sample_work_item(authority_class="read-only")
    _, lock = resolve_toolkit(manifest)
    profiles = build_default_registry_permission_profiles()
    task_profile = next(profile for profile in profiles if profile.id == lock.permission_profile_ids[0])
    reg = default_registry()

    result = compile_work_item(work_item, manifest, lock, "builder", "RUN-AUTH-001")
    authority = result.bundle.authority
    assert authority is not None

    assert EFFECT_RANK[authority.external_effect] <= EFFECT_RANK[work_item.authority_class]
    assert EFFECT_RANK[authority.external_effect] <= EFFECT_RANK[task_profile.external_effect]
    assert EFFECT_RANK[authority.external_effect] <= EFFECT_RANK[manifest.impact.external_effect]

    role_contract = next(item for item in reg.roles if item.id == "builder")
    compiled = compute_compiled_authority(
        work_item,
        manifest,
        result.task_toolkit,
        role_contract,
        task_profile,
        reg,
    )
    assert authority.external_effect == compiled.external_effect
    assert authority.external_effect == ExternalEffectClass.READ_ONLY

    validate_execution_bundle_authority(
        authority,
        work_item,
        manifest,
        result.task_toolkit,
        role_contract,
        task_profile,
        reg,
    )


def test_validate_execution_bundle_authority_guard_is_exercised(monkeypatch: pytest.MonkeyPatch):
    manifest = _sample_manifest()
    work_item = _sample_work_item()
    _, lock = resolve_toolkit(manifest)

    def _fail(*_args: object, **_kwargs: object) -> None:
        raise CompileAuthorityError("guard stub")

    monkeypatch.setattr(
        "agent_foundry.compile.api.validate_execution_bundle_authority",
        _fail,
    )
    with pytest.raises(CompileAuthorityError, match="guard stub"):
        compile_work_item(work_item, manifest, lock, "builder", "RUN-GUARD-2")


def _read_only_discovery_work_item() -> WorkItemContract:
    return _sample_work_item(
        work_class="DISCOVERY",
        authority_class="read-only",
        objective="Inspect project conventions read-only",
    )


def test_read_only_work_item_compiles_on_read_only_project():
    manifest = ProjectManifest(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        project=ProjectInfo(
            name="read-only-service",
            work_modes=WorkModes(primary=PrimaryWorkMode.BUILD),
            primary_artifact=PrimaryArtifactState.CODE,
        ),
        state=ProjectState(),
        impact=ProjectImpact(
            external_effect=ExternalEffectClass.READ_ONLY,
            consequence=ConsequenceClass.LOW,
        ),
        execution=ProjectExecution(),
        assurance=ProjectAssurance(),
        access=ProjectAccess(),
    )
    work_item = _read_only_discovery_work_item()
    _, lock = resolve_toolkit(manifest)
    result = compile_work_item(work_item, manifest, lock, "explorer", "RUN-RO-PROJ")
    assert result.bundle.authority is not None
    assert result.bundle.authority.external_effect == ExternalEffectClass.READ_ONLY
    assert "explorer" in result.task_toolkit.role_ids


def test_read_only_work_item_compiles_on_repository_write_project():
    manifest = _sample_manifest(
        impact={
            "external_effect": "repository-write",
            "reversibility": "versioned",
            "consequence": "medium",
        }
    )
    work_item = _read_only_discovery_work_item()
    _, lock = resolve_toolkit(manifest)
    result = compile_work_item(work_item, manifest, lock, "explorer", "RUN-RO-REPO")
    assert result.bundle.authority.external_effect == ExternalEffectClass.READ_ONLY
    assert "explorer" in result.task_toolkit.role_ids
    assert "builder" not in result.task_toolkit.role_ids


def test_read_only_work_item_compiles_on_publication_project():
    manifest = _sample_manifest(
        impact={
            "external_effect": "publication",
            "reversibility": "versioned",
            "consequence": "high",
        }
    )
    work_item = _read_only_discovery_work_item()
    _, lock = resolve_toolkit(manifest)
    result = compile_work_item(work_item, manifest, lock, "reviewer", "RUN-RO-PUB")
    assert result.bundle.authority.external_effect == ExternalEffectClass.READ_ONLY
    assert "builder" not in result.task_toolkit.role_ids


def test_repository_write_work_item_compiles_as_control():
    manifest = _sample_manifest()
    work_item = _sample_work_item()
    _, lock = resolve_toolkit(manifest)
    result = compile_work_item(work_item, manifest, lock, "builder", "RUN-CONTROL")
    assert result.bundle.authority.external_effect == ExternalEffectClass.REPOSITORY_WRITE
    assert "builder" in result.task_toolkit.role_ids


def test_incident_work_class_compiles_on_supportive_project():
    manifest = _sample_manifest()
    work_item = _sample_work_item(
        work_class="INCIDENT",
        authority_class="repository-write",
        consequence_class="high",
        objective="Diagnose and contain broken operating state",
    )
    _, lock = resolve_toolkit(manifest)
    result = compile_work_item(work_item, manifest, lock, "builder", "RUN-INCIDENT")
    assert "builder" in result.task_toolkit.role_ids
    assert "bounded-change" in result.task_toolkit.skill_ids


def test_contract_amendment_work_class_compiles_on_supportive_project():
    manifest = _sample_manifest(
        assurance={"required": ["deterministic-tests", "independent-review"]},
    )
    work_item = _sample_work_item(
        work_class="CONTRACT_AMENDMENT",
        authority_class="repository-write",
        consequence_class="high",
        objective="Amend durable project contract with review",
    )
    _, lock = resolve_toolkit(manifest)
    result = compile_work_item(work_item, manifest, lock, "builder", "RUN-AMEND")
    assert "reviewer" in result.task_toolkit.role_ids
    assert "independent-review" in result.task_toolkit.skill_ids


def test_unknown_manifest_external_effect_tightens_compiled_authority():
    manifest = ProjectManifest(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        project=ProjectInfo(
            name="unspecified",
            work_modes=WorkModes(primary=PrimaryWorkMode.ANALYZE),
            primary_artifact=PrimaryArtifactState.CODE,
        ),
        state=ProjectState(),
        impact=ProjectImpact(external_effect=None, consequence=ConsequenceClass.LOW),
        execution=ProjectExecution(),
        assurance=ProjectAssurance(),
        access=ProjectAccess(),
    )
    work_item = _sample_work_item(
        work_class="DISCOVERY",
        authority_class="repository-write",
    )
    _, lock = resolve_toolkit(manifest)
    result = compile_work_item(work_item, manifest, lock, "explorer", "RUN-UNKNOWN")
    assert result.bundle.authority is not None
    assert result.bundle.authority.external_effect == ExternalEffectClass.READ_ONLY


def test_provenance_records_selected_and_excluded_skills():
    manifest = _sample_manifest()
    work_item = _sample_work_item()
    _, lock = resolve_toolkit(manifest)
    result = compile_work_item(work_item, manifest, lock, "builder", "RUN-PROV")

    selected = next(
        record
        for record in result.bundle.provenance
        if record.component_kind == "skill" and record.selected
    )
    excluded = next(
        record
        for record in result.bundle.provenance
        if record.component_kind == "skill" and not record.selected
    )
    assert selected.source == ResolutionSource.WORK_ITEM
    assert excluded.source == ResolutionSource.WORK_ITEM
    assert selected.component_id in result.task_toolkit.skill_ids
    assert excluded.component_id not in result.task_toolkit.skill_ids


def test_render_is_fully_determined_by_bundle():
    manifest = _sample_manifest()
    work_item = _sample_work_item()
    _, lock = resolve_toolkit(manifest)
    result = compile_work_item(work_item, manifest, lock, "builder", "RUN-RENDER")

    first = render_execution_bundle_markdown(result.bundle)
    second = render_execution_bundle_markdown(result.bundle)
    assert first == second

    mutated = result.bundle.model_copy(update={"objective": "Changed objective text"})
    altered = render_execution_bundle_markdown(mutated)
    assert altered != first
    assert "Changed objective text" in altered


def test_intersect_write_scopes_four_widening_cases():
    """B1 widening paths must return true intersection, never role-only fallback."""
    assert _intersect_write_scopes(["src/", "tests/"], ["docs/"]) == []
    assert _intersect_write_scopes(["src/af/compile"], ["src/"]) == ["src/af/compile"]
    assert _intersect_write_scopes([], ["src/"]) == []
    assert _intersect_write_scopes(["src/", "tests/"], ["/"]) == []


def test_authority_adversarial_sweep_effect_and_write_scope_axes():
    """Adversarial compile sweep — 0 effect-axis and write-scope violations."""
    manifest = _sample_manifest(
        assurance={"required": ["deterministic-tests", "independent-review"]},
    )
    _, lock = resolve_toolkit(manifest)
    reg = default_registry()
    profiles = build_default_registry_permission_profiles()
    task_profile = next(profile for profile in profiles if profile.id == lock.permission_profile_ids[0])

    role_ids = ("builder", "explorer", "reviewer", "validator")
    authorities = (
        ExternalEffectClass.READ_ONLY,
        ExternalEffectClass.REPOSITORY_WRITE,
        ExternalEffectClass.PUBLICATION,
        ExternalEffectClass.SHARED_SERVICE_WRITE,
    )
    work_item_scopes = (
        ["docs/"],
        ["src/"],
        ["src/", "toolkit resolver"],
        ["src/af/compile"],
        ["infra/terraform"],
    )
    manifest_effects = (
        None,
        ExternalEffectClass.READ_ONLY,
        ExternalEffectClass.REPOSITORY_WRITE,
        ExternalEffectClass.PUBLICATION,
    )

    effect_violations: list[str] = []
    write_scope_violations: list[str] = []
    successful_compiles = 0
    total_attempts = 0

    for work_class, authority, role_id, wi_scopes, manifest_effect in product(
        WorkClass,
        authorities,
        role_ids,
        work_item_scopes,
        manifest_effects,
    ):
        manifest_override = _sample_manifest(
            assurance={"required": ["deterministic-tests", "independent-review"]},
        )
        if manifest_effect is not None:
            manifest_override = manifest_override.model_copy(
                update={
                    "impact": manifest_override.impact.model_copy(
                        update={"external_effect": manifest_effect}
                    )
                }
            )

        work_item = _sample_work_item(
            work_class=work_class.value,
            authority_class=authority.value,
            scope=wi_scopes,
            consequence_class=(
                ConsequenceClass.HIGH.value
                if work_class in {WorkClass.INCIDENT, WorkClass.CONTRACT_AMENDMENT}
                else ConsequenceClass.MEDIUM.value
            ),
        )
        _, sweep_lock = resolve_toolkit(manifest_override)
        role = next(item for item in reg.roles if item.id == role_id)

        total_attempts += 1
        try:
            result = compile_work_item(
                work_item,
                manifest_override,
                sweep_lock,
                role_id,
                f"RUN-SWEEP-{total_attempts}",
            )
        except (CompileError, CompileAuthorityError):
            continue

        successful_compiles += 1
        bundle_authority = result.bundle.authority
        assert bundle_authority is not None

        compiled = compute_compiled_authority(
            work_item,
            manifest_override,
            result.task_toolkit,
            role,
            task_profile,
            reg,
        )
        if bundle_authority.external_effect != compiled.external_effect:
            effect_violations.append(
                f"{work_class.value}/{authority.value}/{role_id}: "
                f"{bundle_authority.external_effect} != {compiled.external_effect}"
            )
        if bundle_authority.write_scope != compiled.write_scope:
            write_scope_violations.append(
                f"{work_class.value}/{authority.value}/{role_id}: "
                f"{bundle_authority.write_scope!r} != {compiled.write_scope!r}"
            )

        for scope_path in bundle_authority.write_scope:
            if not _scope_contained_in_bounds(scope_path, work_item.scope):
                write_scope_violations.append(
                    f"{work_class.value}: {scope_path!r} escapes work item scope"
                )
            if role.write_scope and not _scope_contained_in_bounds(scope_path, role.write_scope):
                write_scope_violations.append(
                    f"{role_id}: {scope_path!r} escapes role write_scope"
                )

        try:
            validate_execution_bundle_authority(
                bundle_authority,
                work_item,
                manifest_override,
                result.task_toolkit,
                role,
                task_profile,
                reg,
            )
        except CompileAuthorityError as exc:
            write_scope_violations.append(str(exc))

    assert total_attempts == 2240
    assert successful_compiles > 0
    assert effect_violations == []
    assert write_scope_violations == []


def test_validate_execution_bundle_authority_rejects_forged_write_scope(
    monkeypatch: pytest.MonkeyPatch,
):
    work_item = _sample_work_item(scope=["docs/", "infra/terraform"])
    manifest = _sample_manifest()
    _, lock = resolve_toolkit(manifest)
    result = compile_work_item(work_item, manifest, lock, "builder", "RUN-FORGE")
    assert result.bundle.authority is not None

    forged = result.bundle.authority.model_copy(
        update={"write_scope": ["src/", "tests/"]},
    )
    profiles = build_default_registry_permission_profiles()
    task_profile = next(profile for profile in profiles if profile.id == lock.permission_profile_ids[0])
    reg = default_registry()
    role = next(item for item in reg.roles if item.id == "builder")

    monkeypatch.setattr(
        "agent_foundry.compile.authority.compute_compiled_authority",
        lambda *_args, **_kwargs: forged,
    )

    with pytest.raises(CompileAuthorityError, match="not contained in work item scope"):
        validate_execution_bundle_authority(
            forged,
            work_item,
            manifest,
            result.task_toolkit,
            role,
            task_profile,
            reg,
        )


def test_write_scope_union_mutation_killed(monkeypatch: pytest.MonkeyPatch):
    from agent_foundry.compile import authority as authority_module

    def _union_write_scopes(
        role_scopes: list[str],
        work_item_scopes: list[str],
    ) -> list[str]:
        normalized = {
            scope.rstrip("/")
            for scope in [*role_scopes, *work_item_scopes]
            if scope.strip() and scope.strip() != "/"
        }
        return sorted(normalized)

    monkeypatch.setattr(authority_module, "_intersect_write_scopes", _union_write_scopes)
    with pytest.raises(AssertionError):
        assert authority_module._intersect_write_scopes(["src/", "tests/"], ["docs/"]) == []


def test_read_only_explorer_markdown_advertises_no_write_scope():
    manifest = _sample_manifest()
    work_item = _read_only_discovery_work_item()
    _, lock = resolve_toolkit(manifest)
    result = compile_work_item(work_item, manifest, lock, "explorer", "RUN-RO-MD")
    assert result.bundle.write_scope == []
    rendered = render_execution_bundle_markdown(result.bundle)
    assert "## Write scope" not in rendered
    assert result.bundle.authority is not None
    assert result.bundle.authority.external_effect == ExternalEffectClass.READ_ONLY


def test_convention_provenance_reports_fields_that_drove_selection():
    manifest = _sample_manifest()
    work_item = _sample_work_item(scope=["alpha-topic"])
    _, lock = resolve_toolkit(manifest)
    convention = ConventionSpec(
        subject="zzz-unrelated-alpha",
        pattern="alpha-topic-pattern",
        source_ref="docs/alpha.md",
        evidence="unrelated",
        confidence=1.0,
        provenance=Provenance(kind=ProvenanceKind.OBSERVED, source_ref="docs/alpha.md"),
    )
    result = compile_work_item(
        work_item,
        manifest,
        lock,
        "builder",
        "RUN-PROV",
        conventions=[convention],
    )
    record = next(
        item for item in result.bundle.provenance if item.component_id == convention.subject
    )
    assert record.selected is True
    assert "pattern" in record.rationale
    assert "subject overlaps" not in record.rationale
    assert "selection score=" in record.rationale
    assert "pattern" in (record.project_fact or "")


def test_execution_bundle_provenance_covers_required_fields():
    manifest = _sample_manifest()
    work_item = _sample_work_item()
    _, lock = resolve_toolkit(manifest)
    result = compile_work_item(
        work_item,
        manifest,
        lock,
        "builder",
        "RUN-PROV-FIELDS",
        context_refs=["docs/context.md"],
    )
    kinds = {record.component_kind for record in result.bundle.provenance}
    for required in (
        "required-evidence",
        "budget-profile",
        "context-ref",
        "interaction-output",
        "stop-condition",
        "write-scope",
    ):
        assert required in kinds


def test_rendered_markdown_respects_constant_byte_ceiling_with_relevant_context():
    manifest = _sample_manifest()
    work_item = _sample_work_item()
    _, lock = resolve_toolkit(manifest)

    relevant_conventions = [
        ConventionSpec(
            subject=f"toolkit-resolver-src-{index:03d}",
            pattern="pytest toolkit resolver",
            source_ref=f"docs/toolkit-{index}.md",
            evidence="toolkit resolver conventions in src/",
            confidence=0.9,
            provenance=Provenance(
                kind=ProvenanceKind.OBSERVED,
                source_ref=f"docs/toolkit-{index}.md",
            ),
        )
        for index in range(60)
    ]

    result = compile_work_item(
        work_item,
        manifest,
        lock,
        "builder",
        "RUN-CONCISE",
        conventions=relevant_conventions,
    )
    rendered = render_execution_bundle_markdown(result.bundle)
    assert len(result.bundle.selected_conventions) == 5
    assert len(rendered.encode("utf-8")) <= _RENDER_BYTE_CEILING


def test_render_conciseness_mutation_killed(monkeypatch: pytest.MonkeyPatch):
    from agent_foundry.compile import context as context_module

    monkeypatch.setattr(context_module, "_MAX_CONTEXT_ITEMS", 100_000)
    manifest = _sample_manifest()
    work_item = _sample_work_item()
    _, lock = resolve_toolkit(manifest)
    relevant_conventions = [
        ConventionSpec(
            subject=f"toolkit-resolver-src-{index:03d}",
            pattern="pytest toolkit resolver",
            source_ref=f"docs/toolkit-{index}.md",
            evidence="toolkit resolver conventions in src/",
            confidence=0.9,
            provenance=Provenance(
                kind=ProvenanceKind.OBSERVED,
                source_ref=f"docs/toolkit-{index}.md",
            ),
        )
        for index in range(60)
    ]
    result = compile_work_item(
        work_item,
        manifest,
        lock,
        "builder",
        "RUN-M4",
        conventions=relevant_conventions,
    )
    rendered = render_execution_bundle_markdown(result.bundle)
    with pytest.raises(AssertionError):
        assert len(rendered.encode("utf-8")) <= _RENDER_BYTE_CEILING


@pytest.mark.parametrize(
    ("vector_name", "work_item_overrides", "compile_kwargs"),
    [
        (
            "objective",
            {"objective": f"verify models package contract tests key {_AWS_SECRET_SAMPLE}"},
            {},
        ),
        ("context_refs", {}, {"context_refs": [_AWS_SECRET_SAMPLE]}),
        (
            "convention_subject",
            {},
            {
                "conventions": [
                    ConventionSpec(
                        subject=_AWS_SECRET_SAMPLE,
                        pattern="toolkit",
                        source_ref="docs/toolkit.md",
                        evidence="toolkit resolver conventions",
                        confidence=0.9,
                        provenance=Provenance(
                            kind=ProvenanceKind.OBSERVED,
                            source_ref="docs/toolkit.md",
                        ),
                    )
                ]
            },
        ),
        (
            "observation_subject",
            {},
            {
                "observations": [
                    ProjectObservation(
                        subject=_AWS_SECRET_SAMPLE,
                        content="toolkit resolver observation",
                        provenance=Provenance(
                            kind=ProvenanceKind.OBSERVED,
                            source_ref="obs-toolkit",
                        ),
                    )
                ]
            },
        ),
    ],
)
def test_render_refuses_embedded_secrets_for_all_vectors(
    vector_name: str,
    work_item_overrides: dict[str, object],
    compile_kwargs: dict[str, object],
):
    manifest = _sample_manifest()
    work_item = _sample_work_item(**work_item_overrides)
    _, lock = resolve_toolkit(manifest)
    result = compile_work_item(
        work_item,
        manifest,
        lock,
        "builder",
        f"RUN-SECRET-{vector_name}",
        **compile_kwargs,
    )
    with pytest.raises(EmbeddedSecretError, match="aws-access-key"):
        render_execution_bundle_markdown(result.bundle)


def _write_secret_work_item_yaml(path: Path) -> None:
    path.write_text(
        f"""schema_version: '0.1'
id: WI-COMPILE-001
title: Implement toolkit resolver
work_class: CAPABILITY
objective: verify models package contract tests key {_AWS_SECRET_SAMPLE}
current_facts:
- bootstrap exists
scope:
- src/
- toolkit resolver
out_of_scope:
- execution runtime
acceptance_criteria:
- pytest green
dependencies: []
authority_class: repository-write
consequence_class: medium
required_evidence:
- pytest
stop_conditions:
- cannot express semantics
""",
        encoding="utf-8",
    )


def test_compile_cli_render_refuses_embedded_secret():
    env = _subprocess_env()
    _assert_imports_worktree(env)
    manifest = _sample_manifest()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        manifest_path = root / "manifest.yaml"
        work_item_path = root / "work_item.yaml"
        manifest_path.write_bytes(dump_yaml(manifest))
        _write_secret_work_item_yaml(work_item_path)
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "agent_foundry",
                "compile",
                "--manifest",
                str(manifest_path),
                "--work-item",
                str(work_item_path),
                "--role-id",
                "builder",
                "--run-id",
                "RUN-CLI-SECRET",
                "--render",
            ],
            capture_output=True,
            text=True,
            env=env,
        )
    assert completed.returncode != 0
    assert _AWS_SECRET_SAMPLE not in completed.stdout
    assert "EmbeddedSecretError" in completed.stderr or "embedded secret" in completed.stderr.lower()


def test_compile_cli_include_bundle_refuses_embedded_secret():
    env = _subprocess_env()
    _assert_imports_worktree(env)
    manifest = _sample_manifest()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        manifest_path = root / "manifest.yaml"
        work_item_path = root / "work_item.yaml"
        manifest_path.write_bytes(dump_yaml(manifest))
        _write_secret_work_item_yaml(work_item_path)
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "agent_foundry",
                "compile",
                "--manifest",
                str(manifest_path),
                "--work-item",
                str(work_item_path),
                "--role-id",
                "builder",
                "--run-id",
                "RUN-CLI-BUNDLE-SECRET",
                "--include-bundle",
                "--format",
                "json",
            ],
            capture_output=True,
            text=True,
            env=env,
        )
    assert completed.returncode != 0
    assert _AWS_SECRET_SAMPLE not in completed.stdout


_COMPILE_DETERMINISM_SCRIPT = """
import json
from pathlib import Path
from agent_foundry.compile import compile_work_item
from agent_foundry.models import ProjectManifest, WorkItemContract
from agent_foundry.render import render_execution_bundle_markdown
from agent_foundry.toolkit import resolve_toolkit

root = Path.cwd()
if not (root / "inputs").is_dir():
    root = root.parent
manifest = ProjectManifest.model_validate(json.loads((root / "inputs/manifest.json").read_text()))
work_item = WorkItemContract.model_validate(json.loads((root / "inputs/work_item.json").read_text()))
_, lock = resolve_toolkit(manifest)
result = compile_work_item(work_item, manifest, lock, "builder", "RUN-DET")
print(json.dumps(json.loads(result.bundle.model_dump_json()), sort_keys=True))
print(render_execution_bundle_markdown(result.bundle), end="")
"""


def _run_compile_determinism_subprocess(
    *,
    env: dict[str, str],
    cwd: Path,
) -> tuple[str, str]:
    completed = subprocess.run(
        [sys.executable, "-c", _COMPILE_DETERMINISM_SCRIPT],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
        check=True,
    )
    bundle_line, markdown = completed.stdout.split("\n", 1)
    return (
        hashlib.sha256(bundle_line.encode()).hexdigest(),
        hashlib.sha256(markdown.encode()).hexdigest(),
    )


def test_compile_determinism_across_hash_seeds_and_cwds():
    """Self-contained determinism guard across hash seeds and working directories."""
    env_base = _subprocess_env()
    _assert_imports_worktree(env_base)
    manifest = _sample_manifest()
    work_item = _sample_work_item()

    reference_bundle: str | None = None
    reference_markdown: str | None = None

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        inputs = root / "inputs"
        inputs.mkdir()
        nested = root / "nested"
        nested.mkdir()
        (inputs / "manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")
        (inputs / "work_item.json").write_text(work_item.model_dump_json(), encoding="utf-8")

        for hash_seed in ("0", "1", "42"):
            for cwd in (root, nested):
                env = {**env_base, "PYTHONHASHSEED": hash_seed}
                bundle_digest, markdown_digest = _run_compile_determinism_subprocess(
                    env=env,
                    cwd=cwd,
                )
                if reference_bundle is None:
                    reference_bundle = bundle_digest
                    reference_markdown = markdown_digest
                    continue
                assert bundle_digest == reference_bundle
                assert markdown_digest == reference_markdown


def test_compile_determinism_test_catches_injected_renderer_nondeterminism(
    monkeypatch: pytest.MonkeyPatch,
):
    import random

    original_render = render_execution_bundle_markdown

    def _nondeterministic_render(bundle: object) -> str:
        return original_render(bundle) + str(random.random())  # type: ignore[arg-type]

    monkeypatch.setattr(
        "agent_foundry.render.markdown.render_execution_bundle_markdown",
        _nondeterministic_render,
    )

    manifest = _sample_manifest()
    work_item = _sample_work_item()
    _, lock = resolve_toolkit(manifest)
    bundle = compile_work_item(work_item, manifest, lock, "builder", "RUN-NONDET").bundle
    first = _nondeterministic_render(bundle)
    second = _nondeterministic_render(bundle)
    assert first != second

    reference: str | None = None
    with pytest.raises(AssertionError):
        for _attempt in range(2):
            digest = hashlib.sha256(_nondeterministic_render(bundle).encode()).hexdigest()
            if reference is None:
                reference = digest
            else:
                assert digest == reference


def test_compile_determinism_same_input_twice():
    first_bundle, first_markdown = _compile_sample()
    second_bundle, second_markdown = _compile_sample()
    assert first_bundle == second_bundle
    assert first_markdown == second_markdown


def test_compile_determinism_permuted_convention_input_order():
    manifest = _sample_manifest()
    work_item = _sample_work_item()
    _, lock = resolve_toolkit(manifest)
    conventions_a = [
        ConventionSpec(
            subject="toolkit",
            pattern="pytest",
            source_ref="docs/toolkit.md",
            evidence="toolkit resolver conventions",
            confidence=0.9,
            provenance=Provenance(kind=ProvenanceKind.OBSERVED, source_ref="docs/toolkit.md"),
        ),
        ConventionSpec(
            subject="resolver",
            pattern="deterministic",
            source_ref="docs/resolver.md",
            evidence="resolver ordering",
            confidence=0.8,
            provenance=Provenance(kind=ProvenanceKind.OBSERVED, source_ref="docs/resolver.md"),
        ),
    ]
    conventions_b = list(reversed(conventions_a))
    result_a = compile_work_item(
        work_item, manifest, lock, "builder", "RUN-ORDER", conventions=conventions_a
    )
    result_b = compile_work_item(
        work_item, manifest, lock, "builder", "RUN-ORDER", conventions=conventions_b
    )
    assert dump_json(result_a.bundle) == dump_json(result_b.bundle)
    assert render_execution_bundle_markdown(result_a.bundle) == render_execution_bundle_markdown(
        result_b.bundle
    )


def test_compile_rejects_role_not_in_task_toolkit():
    manifest = _sample_manifest()
    work_item = _sample_work_item()
    _, lock = resolve_toolkit(manifest)
    with pytest.raises(CompileError, match="not compatible with task toolkit"):
        compile_work_item(work_item, manifest, lock, "runtime-verifier", "RUN-BAD-ROLE")


def test_compile_cli_render_subcommand():
    env = _subprocess_env()
    _assert_imports_worktree(env)
    manifest_path = FIXTURES / "project_manifest.yaml"
    work_item_path = FIXTURES / "work_item_contract.yaml"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_foundry",
            "compile",
            "--manifest",
            str(manifest_path),
            "--work-item",
            str(work_item_path),
            "--role-id",
            "builder",
            "--run-id",
            "RUN-CLI",
            "--render",
        ],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    assert "# Execution Contract" in completed.stdout
    assert "builder" in completed.stdout


def test_compile_test_module_has_no_unused_assignments():
    import ast

    source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    class _FunctionUnusedAssignmentChecker(ast.NodeVisitor):
        def __init__(self) -> None:
            self._stack: list[dict[str, set[str]]] = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            assigned: set[str] = set()
            loaded: set[str] = set()
            self._stack.append({"assigned": assigned, "loaded": loaded})
            for child in ast.walk(node):
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                    assigned.add(child.id)
                elif isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                    loaded.add(child.id)
            self._stack.pop()
            unused = sorted(name for name in assigned if name not in loaded and not name.startswith("_"))
            if unused:
                raise AssertionError(
                    f"unused assignment(s) in {node.name}: {', '.join(unused)}"
                )
            self.generic_visit(node)

    _FunctionUnusedAssignmentChecker().visit(tree)
