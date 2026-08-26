"""Propose conservative classification field candidates from inspection evidence."""

from __future__ import annotations

from pathlib import Path

from agent_foundry.models.common import IntakeMode, Provenance, ProvenanceKind
from agent_foundry.models.project import ClassificationFinding, ProjectObservation
from agent_foundry.inspect.traversal import FOUNDRY_DIR_NAME, RepoEntry, read_text_bounded


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
) -> ClassificationFinding:
    return ClassificationFinding(
        dimension=dimension,
        value=value,
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
        evidence_refs=[source_ref] if source_ref != "." else [],
    )


def propose_classification_findings(
    root: Path,
    entries: list[RepoEntry],
    observations: list[ProjectObservation],
) -> list[ClassificationFinding]:
    findings: list[ClassificationFinding] = []

    declared_project = root / FOUNDRY_DIR_NAME / "project.yaml"
    if declared_project.is_file():
        findings.append(
            _finding(
                "intake_mode",
                None,
                kind=ProvenanceKind.DECLARED,
                source_ref=".foundry/project.yaml",
                evidence_refs=[".foundry/project.yaml"],
            )
        )
    else:
        code_dirs = {"src", "lib", "app", "internal", "pkg"}
        code_files = [
            e
            for e in entries
            if not e.is_dir and e.relative_path.endswith((".py", ".go", ".rs", ".ts", ".js"))
        ]
        has_code_tree = any(e.relative_path.split("/")[0] in code_dirs for e in entries if e.is_dir)
        has_ci = any(e.relative_path.startswith(".github/workflows/") for e in entries if not e.is_dir)
        has_foundry = any(e.relative_path.startswith(".foundry/") for e in entries if not e.is_dir)
        has_deploy = any(
            Path(e.relative_path).name in {"Dockerfile", "docker-compose.yml", "docker-compose.yaml"}
            for e in entries
            if not e.is_dir
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
                    confidence=0.7,
                    evidence_refs=sorted({e.relative_path for e in code_files[:5]}),
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

    for dimension in CLASSIFICATION_DIMENSIONS:
        if dimension == "intake_mode":
            continue
        if dimension == "primary_work_mode":
            if declared_project.is_file() and read_text_bounded(declared_project):
                findings.append(
                    _finding(
                        dimension,
                        None,
                        kind=ProvenanceKind.DECLARED,
                        source_ref=".foundry/project.yaml",
                        evidence_refs=[".foundry/project.yaml"],
                    )
                )
            else:
                findings.append(_unknown(dimension, reason="no declared project manifest"))
            continue
        findings.append(_unknown(dimension, reason="not observable from repository inventory alone"))

    findings.sort(key=lambda f: (f.dimension, f.value or "", tuple(f.evidence_refs)))
    return findings
