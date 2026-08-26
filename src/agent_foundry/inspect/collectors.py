"""Collect typed observations from a bounded repository walk."""

from __future__ import annotations

import re
from pathlib import Path

from agent_foundry.models.common import Provenance, ProvenanceKind
from agent_foundry.models.project import ProjectObservation
from agent_foundry.inspect.traversal import (
    AGENT_RULE_RELATIVE_PATHS,
    CI_WORKFLOW_PREFIX,
    CURSOR_RULES_PREFIX,
    DOCS_AI_PREFIX,
    FOUNDRY_DIR_PREFIX,
    PACKAGE_METADATA_FILES,
    RepoEntry,
    file_entries,
    file_path_set,
    read_entry_text,
)

_MAKEFILE_TARGET_SUBJECTS: dict[str, str] = {
    "test": "test-entrypoint",
    "lint": "lint-entrypoint",
    "typecheck": "typecheck-entrypoint",
    "ci": "ci-entrypoint",
}


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


def _matching_paths(rel_paths: set[str], marker: str) -> list[str]:
    if marker in rel_paths:
        return [marker]
    suffix = f"/{marker}"
    return sorted(path for path in rel_paths if path.endswith(suffix))


def _makefile_declared_targets(content: str) -> set[str]:
    declared: set[str] = set()
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for target in _MAKEFILE_TARGET_SUBJECTS:
            if re.match(rf"^{re.escape(target)}\s*:", stripped):
                declared.add(target)
    return declared


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
    for entry in file_entries(entries):
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


def collect_agent_rule_observations(root: Path, entries: list[RepoEntry]) -> list[ProjectObservation]:
    observations: list[ProjectObservation] = []
    rel_paths = file_path_set(entries)

    for rel in AGENT_RULE_RELATIVE_PATHS:
        if rel not in rel_paths:
            continue
        observations.append(
            _observed(
                "agent-instruction-surface",
                f"instruction file present: {rel}",
                rel,
            )
        )

    for entry in file_entries(entries):
        rel = entry.relative_path
        if not rel.startswith(CURSOR_RULES_PREFIX):
            continue
        if Path(rel).suffix not in {".md", ".mdc"}:
            continue
        observations.append(
            _observed(
                "agent-instruction-surface",
                f"cursor rule file present: {rel}",
                rel,
            )
        )
    return observations


def collect_test_lint_ci_observations(
    root: Path,
    entries: list[RepoEntry],
    *,
    max_file_bytes: int,
) -> list[ProjectObservation]:
    observations: list[ProjectObservation] = []
    rel_paths = file_path_set(entries)

    test_markers = {"pytest.ini", "tox.ini", "conftest.py", ".coveragerc"}
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

    for marker in sorted(test_markers):
        for rel in _matching_paths(rel_paths, marker):
            observations.append(
                _observed("test-entrypoint", f"test harness marker present: {marker}", rel)
            )

    for marker in sorted(lint_type_markers):
        if marker not in rel_paths:
            continue
        observations.append(
            _observed("lint-type-entrypoint", f"lint/type marker present: {marker}", marker)
        )

    for entry in file_entries(entries):
        rel = entry.relative_path
        if not rel.startswith(CI_WORKFLOW_PREFIX):
            continue
        if Path(rel).suffix not in {".yml", ".yaml"}:
            continue
        observations.append(_observed("ci-entrypoint", f"CI workflow present: {rel}", rel))

    makefile_entry = next((e for e in file_entries(entries) if e.relative_path == "Makefile"), None)
    if makefile_entry is not None:
        content = read_entry_text(root, makefile_entry, max_bytes=max_file_bytes)
        if content:
            for target, subject in sorted(_MAKEFILE_TARGET_SUBJECTS.items()):
                if target in _makefile_declared_targets(content):
                    observations.append(
                        _observed(
                            subject,
                            f"Makefile declares '{target}' target",
                            "Makefile",
                        )
                    )
    return observations


def collect_config_schema_observations(root: Path, entries: list[RepoEntry]) -> list[ProjectObservation]:
    observations: list[ProjectObservation] = []
    schema_suffixes = (".schema.json", ".schema.yaml", ".schema.yml")
    for entry in file_entries(entries):
        if entry.relative_path.endswith(schema_suffixes):
            observations.append(
                _observed(
                    "config-schema",
                    f"schema surface present: {entry.relative_path}",
                    entry.relative_path,
                )
            )
        if entry.relative_path.startswith(DOCS_AI_PREFIX) and entry.relative_path.endswith(".md"):
            observations.append(
                _observed(
                    "project-docs",
                    f"project AI doc present: {entry.relative_path}",
                    entry.relative_path,
                )
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
    for entry in file_entries(entries):
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
        "env.example",
        "integrations.yaml",
        "integrations.yml",
    }
    for entry in file_entries(entries):
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


def collect_foundry_observations(
    root: Path,
    entries: list[RepoEntry],
    *,
    max_file_bytes: int,
) -> list[ProjectObservation]:
    observations: list[ProjectObservation] = []
    for entry in file_entries(entries):
        rel = entry.relative_path
        if not rel.startswith(FOUNDRY_DIR_PREFIX):
            continue
        observations.append(
            _observed("foundry-artifact", f"foundry artifact present: {rel}", rel)
        )
        if Path(rel).name in {"project.yaml", "project.yml"}:
            content = read_entry_text(root, entry, max_bytes=max_file_bytes)
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
