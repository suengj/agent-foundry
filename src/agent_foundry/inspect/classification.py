"""Propose conservative classification field candidates from inspection evidence."""

from __future__ import annotations

from pathlib import Path

import yaml

from agent_foundry.models.common import IntakeMode, Provenance, ProvenanceKind
from agent_foundry.models.project import ClassificationFinding, ProjectObservation
from agent_foundry.inspect.traversal import FOUNDRY_DIR_PREFIX, RepoEntry, file_path_set, read_entry_text


CLASSIFICATION_DIMENSIONS: tuple[str, ...] = (
    "intake_mode",
    "primary_work_mode",
    "primary_artifact",
    "state.persistence",
    "impact.external_effect",
    "execution.autonomy",
    "access.sensitivity",
)


def _finding(
    dimension: str,
    value: str | None,
    *,
    kind: ProvenanceKind,
    source_ref: str,
    confidence: float | None = None,
    evidence_refs: list[str] | None = None,
    reason: str | None = None,
) -> ClassificationFinding:
    return ClassificationFinding(
        dimension=dimension,
        value=value,
        reason=reason,
        provenance=Provenance(kind=kind, confidence=confidence, source_ref=source_ref),
        evidence_refs=sorted(evidence_refs or []),
    )


def _unknown(dimension: str, *, reason: str, source_ref: str = ".") -> ClassificationFinding:
    return _finding(
        dimension,
        None,
        kind=ProvenanceKind.INFERRED,
        source_ref=source_ref,
        confidence=0.0,
        reason=reason,
    )


def _declared_intake_mode(
    root: Path,
    entries: list[RepoEntry],
    *,
    max_file_bytes: int,
) -> ClassificationFinding | None:
    rel_paths = file_path_set(entries)
    project_yaml = ".foundry/project.yaml"
    project_yml = ".foundry/project.yml"
    rel = project_yaml if project_yaml in rel_paths else project_yml if project_yml in rel_paths else None
    if rel is None:
        return None
    entry = next(e for e in entries if e.relative_path == rel)
    content = read_entry_text(root, entry, max_bytes=max_file_bytes)
    if not content:
        return None
    try:
        parsed = yaml.safe_load(content)
    except yaml.YAMLError:
        return None
    if not isinstance(parsed, dict):
        return None
    project = parsed.get("project")
    if not isinstance(project, dict):
        return None
    intake_mode = project.get("intake_mode")
    if intake_mode is None:
        return _finding(
            "intake_mode",
            None,
            kind=ProvenanceKind.DECLARED,
            source_ref=rel,
            evidence_refs=[rel],
            reason="intake_mode not declared in project.yaml",
        )
    return _finding(
        "intake_mode",
        str(intake_mode),
        kind=ProvenanceKind.DECLARED,
        source_ref=rel,
        evidence_refs=[rel],
    )


def propose_classification_findings(
    root: Path,
    entries: list[RepoEntry],
    observations: list[ProjectObservation],
    *,
    max_file_bytes: int,
) -> list[ClassificationFinding]:
    findings: list[ClassificationFinding] = []

    declared_intake = _declared_intake_mode(root, entries, max_file_bytes=max_file_bytes)
    if declared_intake is not None:
        findings.append(declared_intake)
    else:
        code_dirs = {"src", "lib", "app", "internal", "pkg"}
        code_files = [
            e
            for e in entries
            if not e.is_dir and e.relative_path.endswith((".py", ".go", ".rs", ".ts", ".js"))
        ]
        has_code_tree = any(e.relative_path.split("/")[0] in code_dirs for e in entries if e.is_dir)
        has_ci = any(e.relative_path.startswith(".github/workflows/") for e in entries if not e.is_dir)
        has_foundry = any(e.relative_path.startswith(FOUNDRY_DIR_PREFIX) for e in entries if not e.is_dir)
        has_deploy = any(
            Path(e.relative_path).name in {"Dockerfile", "docker-compose.yml", "docker-compose.yaml"}
            for e in entries
            if not e.is_dir
        )
        evidence_refs: list[str] = []
        if has_code_tree and len(code_files) >= 3:
            evidence_refs.extend(sorted(e.relative_path for e in code_files[:5]))
        if has_ci:
            evidence_refs.extend(
                sorted(
                    e.relative_path
                    for e in entries
                    if not e.is_dir and e.relative_path.startswith(".github/workflows/")
                )[:3]
            )
        if has_foundry:
            evidence_refs.extend(
                sorted(e.relative_path for e in entries if e.relative_path.startswith(FOUNDRY_DIR_PREFIX))[:3]
            )
        if has_deploy:
            evidence_refs.extend(
                sorted(
                    e.relative_path
                    for e in entries
                    if not e.is_dir
                    and Path(e.relative_path).name
                    in {"Dockerfile", "docker-compose.yml", "docker-compose.yaml"}
                )
            )
        brownfield_signals = sum(
            [
                has_code_tree and len(code_files) >= 3,
                has_ci,
                has_foundry,
                has_deploy,
                len(code_files) >= 8,
            ]
        )
        if brownfield_signals >= 1:
            findings.append(
                _finding(
                    "intake_mode",
                    IntakeMode.BROWNFIELD.value,
                    kind=ProvenanceKind.INFERRED,
                    source_ref=".",
                    confidence=0.7 if evidence_refs else 0.5,
                    evidence_refs=sorted(set(evidence_refs)),
                )
            )
        else:
            findings.append(
                _finding(
                    "intake_mode",
                    IntakeMode.GREENFIELD.value,
                    kind=ProvenanceKind.INFERRED,
                    source_ref=".",
                    confidence=0.55,
                )
            )

    agent_surfaces = [
        obs.provenance.source_ref
        for obs in observations
        if obs.subject == "agent-instruction-surface" and obs.provenance.source_ref
    ]
    if len(agent_surfaces) >= 2:
        findings.append(
            _finding(
                "agent-rule-fragmentation",
                "multiple-instruction-surfaces",
                kind=ProvenanceKind.OBSERVED,
                source_ref=".",
                confidence=1.0,
                evidence_refs=sorted(agent_surfaces),
            )
        )

    declared_project_rel = None
    rel_paths = file_path_set(entries)
    if ".foundry/project.yaml" in rel_paths:
        declared_project_rel = ".foundry/project.yaml"
    elif ".foundry/project.yml" in rel_paths:
        declared_project_rel = ".foundry/project.yml"

    for dimension in CLASSIFICATION_DIMENSIONS:
        if dimension == "intake_mode":
            continue
        if dimension == "primary_work_mode":
            if declared_project_rel is not None:
                findings.append(
                    _finding(
                        dimension,
                        None,
                        kind=ProvenanceKind.DECLARED,
                        source_ref=declared_project_rel,
                        evidence_refs=[declared_project_rel],
                        reason="work_modes not parsed in AF2",
                    )
                )
            else:
                findings.append(_unknown(dimension, reason="no declared project manifest"))
            continue
        findings.append(_unknown(dimension, reason="not observable from repository inventory alone"))

    findings.sort(key=lambda f: (f.dimension, f.value or "", tuple(f.evidence_refs)))
    return findings
