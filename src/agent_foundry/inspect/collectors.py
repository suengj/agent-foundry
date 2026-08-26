"""Collect typed observations from a bounded repository walk."""

from __future__ import annotations

from pathlib import Path

from agent_foundry.models.common import Provenance, ProvenanceKind
from agent_foundry.models.project import ProjectObservation
from agent_foundry.inspect.traversal import (
    AGENT_RULE_RELATIVE_PATHS,
    CI_WORKFLOW_GLOB_PARTS,
    FOUNDRY_DIR_NAME,
    PACKAGE_METADATA_FILES,
    RepoEntry,
    read_text_bounded,
    relative_posix,
)


def _observed(subject: str, content: str, source_ref: str, *, confidence: float = 1.0) -> ProjectObservation:
    return ProjectObservation(
        subject=subject,
        content=content,
        provenance=Provenance(
            kind=ProvenanceKind.OBSERVED,
            confidence=confidence,
            source_ref=source_ref,
        ),
    )


def _declared(subject: str, content: str, source_ref: str) -> ProjectObservation:
    return ProjectObservation(
        subject=subject,
        content=content,
        provenance=Provenance(
            kind=ProvenanceKind.DECLARED,
            source_ref=source_ref,
        ),
    )


def collect_structure_observations(
    root: Path,
    entries: list[RepoEntry],
) -> list[ProjectObservation]:
    observations: list[ProjectObservation] = []
    file_count = sum(1 for e in entries if not e.is_dir)
    dir_count = sum(1 for e in entries if e.is_dir)
    observations.append(
        _observed(
            "repository-structure",
            f"visited {file_count} files and {dir_count} directories within traversal bounds",
            ".",
        )
    )
    top_level = sorted({e.relative_path.split("/")[0] for e in entries if e.relative_path})
    if top_level:
        observations.append(
            _observed(
                "repository-structure",
                "top-level entries: " + ", ".join(top_level),
                ".",
            )
        )
    return observations


def collect_metadata_observations(root: Path, entries: list[RepoEntry]) -> list[ProjectObservation]:
    observations: list[ProjectObservation] = []
    for entry in entries:
        if entry.is_dir:
            continue
        name = Path(entry.relative_path).name
        if name not in PACKAGE_METADATA_FILES:
            continue
        observations.append(
            _observed(
                "package-metadata",
                f"package/build metadata file present: {name}",
                entry.relative_path,
            )
        )
    return observations


def collect_agent_rule_observations(root: Path) -> list[ProjectObservation]:
    observations: list[ProjectObservation] = []
    for rel in AGENT_RULE_RELATIVE_PATHS:
        path = root / rel
        if path.is_file():
            observations.append(
                _observed(
                    "agent-instruction-surface",
                    f"instruction file present: {rel}",
                    rel,
                )
            )

    cursor_rules = root / ".cursor" / "rules"
    if cursor_rules.is_dir():
        rule_files = sorted(
            p for p in cursor_rules.rglob("*") if p.is_file() and p.suffix in {".md", ".mdc"}
        )
        for rule_path in rule_files:
            rel = relative_posix(root, rule_path)
            observations.append(
                _observed(
                    "agent-instruction-surface",
                    f"cursor rule file present: {rel}",
                    rel,
                )
            )
    return observations


def collect_test_lint_ci_observations(root: Path, entries: list[RepoEntry]) -> list[ProjectObservation]:
    observations: list[ProjectObservation] = []
    test_markers = {
        "pytest.ini",
        "tox.ini",
        "conftest.py",
        ".coveragerc",
    }
    lint_type_markers = {
        "ruff.toml",
        ".ruff.toml",
        "mypy.ini",
        ".flake8",
        "pyrightconfig.json",
        "tsconfig.json",
        ".eslintrc",
        ".eslintrc.json",
        "eslint.config.js",
    }

    rel_paths = {e.relative_path for e in entries if not e.is_dir}
    for marker in sorted(test_markers):
        if marker in rel_paths or any(p.endswith(f"/{marker}") for p in rel_paths):
            observations.append(
                _observed("test-entrypoint", f"test harness marker present: {marker}", marker)
            )

    for marker in sorted(lint_type_markers):
        if marker in rel_paths:
            observations.append(
                _observed("lint-type-entrypoint", f"lint/type marker present: {marker}", marker)
            )

    workflow_dir = root.joinpath(*CI_WORKFLOW_GLOB_PARTS)
    if workflow_dir.is_dir():
        workflows = sorted(p for p in workflow_dir.iterdir() if p.suffix in {".yml", ".yaml"})
        for wf in workflows:
            rel = relative_posix(root, wf)
            observations.append(
                _observed("ci-entrypoint", f"CI workflow present: {rel}", rel)
            )

    makefile = root / "Makefile"
    if makefile.is_file():
        content = read_text_bounded(makefile)
        if content:
            for target in ("test", "lint", "typecheck", "ci"):
                if f"{target}:" in content:
                    observations.append(
                        _observed(
                            "test-entrypoint",
                            f"Makefile declares '{target}' target",
                            "Makefile",
                        )
                    )
    return observations


def collect_config_schema_observations(root: Path, entries: list[RepoEntry]) -> list[ProjectObservation]:
    observations: list[ProjectObservation] = []
    schema_suffixes = (".schema.json", ".schema.yaml", ".schema.yml")
    for entry in entries:
        if entry.is_dir:
            continue
        if entry.relative_path.endswith(schema_suffixes):
            observations.append(
                _observed(
                    "config-schema",
                    f"schema surface present: {entry.relative_path}",
                    entry.relative_path,
                )
            )
    docs_ai = root / "docs" / "ai"
    if docs_ai.is_dir():
        for doc in sorted(docs_ai.glob("*.md")):
            rel = relative_posix(root, doc)
            observations.append(
                _observed("project-docs", f"project AI doc present: {rel}", rel)
            )
    return observations


def collect_runtime_deploy_observations(root: Path, entries: list[RepoEntry]) -> list[ProjectObservation]:
    observations: list[ProjectObservation] = []
    deploy_markers = {
        "Dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yaml",
        "compose.yml",
        "Procfile",
        "fly.toml",
        "render.yaml",
        "vercel.json",
        "netlify.toml",
        "kubernetes",
        "helm",
    }
    for entry in entries:
        name = Path(entry.relative_path).name
        if name in deploy_markers or entry.relative_path.startswith("deploy/"):
            observations.append(
                _observed(
                    "runtime-deploy-hint",
                    f"deploy/runtime marker present: {entry.relative_path}",
                    entry.relative_path,
                )
            )
    return observations


def collect_integration_observations(root: Path, entries: list[RepoEntry]) -> list[ProjectObservation]:
    observations: list[ProjectObservation] = []
    integration_markers = {
        ".env.example",
        ".env.sample",
        "integrations.yaml",
        "integrations.yml",
    }
    for entry in entries:
        name = Path(entry.relative_path).name
        if name in integration_markers:
            observations.append(
                _observed(
                    "integration-config",
                    f"integration/credential declaration surface: {entry.relative_path}",
                    entry.relative_path,
                )
            )
    return observations


def collect_foundry_observations(root: Path) -> list[ProjectObservation]:
    observations: list[ProjectObservation] = []
    foundry_dir = root / FOUNDRY_DIR_NAME
    if not foundry_dir.is_dir():
        return observations
    for path in sorted(foundry_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = relative_posix(root, path)
        observations.append(
            _observed("foundry-artifact", f"foundry artifact present: {rel}", rel)
        )
        if path.name in {"project.yaml", "project.yml"}:
            content = read_text_bounded(path)
            if content:
                observations.append(
                    _declared(
                        "foundry-declaration",
                        "project.yaml present with owner-declared characteristics",
                        rel,
                    )
                )
    return observations


def collect_revision_observation(root: Path, revision: str | None) -> list[ProjectObservation]:
    if revision is None:
        return [
            ProjectObservation(
                subject="repository-revision",
                content="revision unknown: no readable git HEAD",
                provenance=Provenance(kind=ProvenanceKind.OBSERVED, source_ref="."),
            )
        ]
    return [
        _observed(
            "repository-revision",
            f"current revision: {revision}",
            ".git/HEAD",
        )
    ]
