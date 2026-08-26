"""Work Item compiler, authority intersection, render, and determinism tests."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from agent_foundry.compile import (
    CompileError,
    compile_work_item,
    compute_compiled_authority,
    validate_execution_bundle_authority,
)
from agent_foundry.compile.authority import CompileAuthorityError
from agent_foundry.models import (
    ConsequenceClass,
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
    result = compile_work_item(work_item, manifest, lock, "builder", "RUN-GUARD")

    def _fail(*_args: object, **_kwargs: object) -> None:
        raise CompileAuthorityError("guard stub")

    monkeypatch.setattr(
        "agent_foundry.compile.api.validate_execution_bundle_authority",
        _fail,
    )
    with pytest.raises(CompileAuthorityError, match="guard stub"):
        compile_work_item(work_item, manifest, lock, "builder", "RUN-GUARD-2")


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


def test_rendered_markdown_is_concise_against_large_project_context():
    manifest = _sample_manifest()
    work_item = _sample_work_item()
    _, lock = resolve_toolkit(manifest)

    large_conventions = [
        ConventionSpec(
            subject=f"convention-topic-{index:04d}",
            pattern=f"pattern-{index}",
            source_ref=f"docs/topic-{index}.md",
            evidence=f"evidence about unrelated topic {index}",
            confidence=0.5,
            provenance=Provenance(kind=ProvenanceKind.OBSERVED, source_ref=f"docs/topic-{index}.md"),
        )
        for index in range(200)
    ]
    large_observations = [
        ProjectObservation(
            subject=f"observation-{index:04d}",
            content=f"unrelated fact {index}",
            provenance=Provenance(kind=ProvenanceKind.OBSERVED, source_ref=f"fact-{index}"),
        )
        for index in range(200)
    ]
    context_size = sum(len(item.subject) + len(item.evidence) for item in large_conventions)
    context_size += sum(len(item.subject) + len(item.content) for item in large_observations)

    result = compile_work_item(
        work_item,
        manifest,
        lock,
        "builder",
        "RUN-CONCISE",
        conventions=large_conventions,
        observations=large_observations,
    )
    rendered = render_execution_bundle_markdown(result.bundle)
    assert len(rendered) < context_size / 10
    assert len(result.bundle.selected_conventions) <= 5
    assert len(result.bundle.selected_observations) <= 5


_DETERMINISM_DIGESTS: tuple[str, str] | None = None


@pytest.mark.parametrize("hash_seed", ["0", "1", "42"])
@pytest.mark.parametrize("cwd", [".", ".."])
def test_compile_determinism_across_hash_seeds_and_cwds(hash_seed: str, cwd: str):
    global _DETERMINISM_DIGESTS
    env = {**_subprocess_env(), "PYTHONHASHSEED": hash_seed}
    _assert_imports_worktree(env)
    script = """
import json
from pathlib import Path
from agent_foundry.compile import compile_work_item
from agent_foundry.models import ProjectManifest, WorkItemContract
from agent_foundry.render import render_execution_bundle_markdown
from agent_foundry.toolkit import resolve_toolkit

manifest = ProjectManifest.model_validate(json.loads(Path("manifest.json").read_text()))
work_item = json.loads(Path("work_item.json").read_text())
work_item = WorkItemContract.model_validate(work_item)
_, lock = resolve_toolkit(manifest)
result = compile_work_item(work_item, manifest, lock, "builder", "RUN-DET")
print(json.dumps(json.loads(result.bundle.model_dump_json()), sort_keys=True))
print(render_execution_bundle_markdown(result.bundle), end="")
"""
    manifest = _sample_manifest()
    work_item = _sample_work_item()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")
        (root / "work_item.json").write_text(work_item.model_dump_json(), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env=env,
            cwd=root,
            check=True,
        )
        bundle_line, markdown = completed.stdout.split("\n", 1)
        digest_bundle = hashlib.sha256(bundle_line.encode()).hexdigest()
        digest_markdown = hashlib.sha256(markdown.encode()).hexdigest()
        if _DETERMINISM_DIGESTS is None:
            _DETERMINISM_DIGESTS = (digest_bundle, digest_markdown)
        else:
            assert digest_bundle == _DETERMINISM_DIGESTS[0]
            assert digest_markdown == _DETERMINISM_DIGESTS[1]


def test_compile_determinism_across_working_directories():
    env = _subprocess_env()
    _assert_imports_worktree(env)
    script = """
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
result = compile_work_item(work_item, manifest, lock, "builder", "RUN-CWD")
print(render_execution_bundle_markdown(result.bundle), end="")
"""
    manifest = _sample_manifest()
    work_item = _sample_work_item()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        inputs = root / "inputs"
        inputs.mkdir()
        nested = root / "nested"
        nested.mkdir()
        (inputs / "manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")
        (inputs / "work_item.json").write_text(work_item.model_dump_json(), encoding="utf-8")

        from_root = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env=env,
            cwd=root,
            check=True,
        )
        from_nested = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env=env,
            cwd=nested,
            check=True,
        )
        assert from_root.stdout == from_nested.stdout


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


def test_render_contains_no_secret_material():
    manifest = _sample_manifest()
    work_item = _sample_work_item()
    _, lock = resolve_toolkit(manifest)
    result = compile_work_item(work_item, manifest, lock, "builder", "RUN-SECRET")
    rendered = render_execution_bundle_markdown(result.bundle)
    assert "sk-" not in rendered
    assert "AKIA" not in rendered
