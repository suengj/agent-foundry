"""Propose conservative classification field candidates from inspection evidence."""

from __future__ import annotations

from pathlib import Path

import yaml

from agent_foundry.models.common import IntakeMode, Provenance, ProvenanceKind
from agent_foundry.models.project import ClassificationFinding, ProjectObservation
from agent_foundry.inspect.traversal import FOUNDRY_DIR_PREFIX, RepoEntry, file_path_set, read_entry_text


# Every ProjectManifest field an owner can declare, keyed by the dotted path the
# declaration file uses. A dimension absent from this tuple cannot reach the
# manifest at all, so growing the manifest without growing this tuple silently
# drops an owner's declaration — which is what AF8 found for eleven of them.
CLASSIFICATION_DIMENSIONS: tuple[str, ...] = (
    "intake_mode",
    "project.name",
    "primary_work_mode",
    "secondary_work_modes",
    "primary_artifact",
    "state.persistence",
    "state.temporal_mode",
    "impact.external_effect",
    "impact.reversibility",
    "impact.consequence",
    "execution.autonomy",
    "execution.ambiguity",
    "execution.concurrency",
    "assurance.required",
    "access.sensitivity",
    "authority.write_scope",
)

# Where each dimension is read from inside `.foundry/project.yaml`. The path is the
# nesting the file uses; the manifest field it lands in is decided in
# `adopt.manifest`, which is the only place that promotes a finding to a value.
_DECLARED_PATHS: dict[str, tuple[str, ...]] = {
    "intake_mode": ("project", "intake_mode"),
    "project.name": ("project", "name"),
    "primary_work_mode": ("project", "work_modes", "primary"),
    "secondary_work_modes": ("project", "work_modes", "secondary"),
    "primary_artifact": ("project", "primary_artifact"),
    "state.persistence": ("state", "persistence"),
    "state.temporal_mode": ("state", "temporal_mode"),
    "impact.external_effect": ("impact", "external_effect"),
    "impact.reversibility": ("impact", "reversibility"),
    "impact.consequence": ("impact", "consequence"),
    "execution.autonomy": ("execution", "autonomy"),
    "execution.ambiguity": ("execution", "ambiguity"),
    "execution.concurrency": ("execution", "concurrency"),
    "assurance.required": ("assurance", "required"),
    "access.sensitivity": ("access", "sensitivity"),
    "authority.write_scope": ("authority", "write_scope"),
}

# Dimensions whose declared value is a list of scalars rather than one scalar.
_LIST_DIMENSIONS: frozenset[str] = frozenset(
    {"secondary_work_modes", "assurance.required", "authority.write_scope"}
)

# Declared list values are carried as one finding whose `value` is this separator
# joined — a ClassificationFinding holds a single string by contract, and AF8 is
# not the place to widen that contract.
DECLARED_LIST_SEPARATOR = ","


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


# One weak signal must not read like several. Confidence tracks how many independent
# brownfield signals were found, not merely whether any evidence ref could be listed.
_SIGNAL_CONFIDENCE_BASE = 0.4
_SIGNAL_CONFIDENCE_STEP = 0.1
_SIGNAL_CONFIDENCE_CEILING = 0.85


def _signal_strength_confidence(present: int, total: int) -> float:
    """Map "n of total signals present" onto a bounded inference confidence."""
    if present <= 0 or total <= 0:
        return 0.0
    scaled = _SIGNAL_CONFIDENCE_BASE + _SIGNAL_CONFIDENCE_STEP * present
    return round(min(_SIGNAL_CONFIDENCE_CEILING, scaled), 2)


def _unknown(dimension: str, *, reason: str, source_ref: str = ".") -> ClassificationFinding:
    return _finding(
        dimension,
        None,
        kind=ProvenanceKind.INFERRED,
        source_ref=source_ref,
        confidence=0.0,
        reason=reason,
    )


def _declaration_relpath(entries: list[RepoEntry]) -> str | None:
    """Repo-relative path of the owner declaration, or None when there is none."""
    rel_paths = file_path_set(entries)
    for candidate in (".foundry/project.yaml", ".foundry/project.yml"):
        if candidate in rel_paths:
            return candidate
    return None


def _read_declaration(
    root: Path,
    entries: list[RepoEntry],
    *,
    max_file_bytes: int,
) -> tuple[str | None, dict[str, object] | None]:
    """Return the declaration path and its parsed mapping.

    A path with no readable mapping returns `(rel, None)`: the file exists and the
    owner meant something by it, so the dimensions it should carry are reported as
    undeclared *at that path* rather than as if no declaration existed at all.
    """
    rel = _declaration_relpath(entries)
    if rel is None:
        return None, None
    entry = next(e for e in entries if e.relative_path == rel)
    content = read_entry_text(root, entry, max_bytes=max_file_bytes)
    if not content:
        return rel, None
    try:
        parsed = yaml.safe_load(content)
    except yaml.YAMLError:
        return rel, None
    if not isinstance(parsed, dict):
        return rel, None
    return rel, parsed


def _declared_at(declaration: dict[str, object], path: tuple[str, ...]) -> object | None:
    """Follow a dotted path into the declaration; None when any hop is absent."""
    node: object = declaration
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
        if node is None:
            return None
    return node


def _declared_scalar(value: object) -> str | None:
    """Render a declared scalar as the string a vocabulary lookup will see.

    Booleans and mappings are not scalars any manifest dimension accepts; they are
    reported as an unusable declaration rather than coerced into a plausible string.
    """
    if isinstance(value, (bool, dict, list)):
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, (int, float)):
        return str(value)
    return None


def _declared_list(value: object) -> str | None:
    """Render a declared list as a separator-joined string, or None when unusable."""
    if not isinstance(value, list):
        return None
    rendered: list[str] = []
    for item in value:
        scalar = _declared_scalar(item)
        if scalar is None or DECLARED_LIST_SEPARATOR in scalar:
            return None
        rendered.append(scalar)
    return DECLARED_LIST_SEPARATOR.join(rendered)


def declared_classification_findings(
    root: Path,
    entries: list[RepoEntry],
    *,
    max_file_bytes: int,
) -> tuple[str | None, list[ClassificationFinding]]:
    """Read every manifest dimension an owner declared in `.foundry/project.yaml`.

    Every dimension in `CLASSIFICATION_DIMENSIONS` gets a finding whenever a
    declaration file exists, so a dimension the owner left out is recorded as
    declared-and-absent rather than silently missing. The value is not validated
    here: an unrecognised vocabulary member is carried through as a DECLARED
    finding so that `adopt.manifest` can report it as an invalid declaration
    instead of this layer discarding it without saying so.
    """
    rel, declaration = _read_declaration(root, entries, max_file_bytes=max_file_bytes)
    if rel is None:
        return None, []

    findings: list[ClassificationFinding] = []
    for dimension in CLASSIFICATION_DIMENSIONS:
        raw = None if declaration is None else _declared_at(declaration, _DECLARED_PATHS[dimension])
        if dimension in _LIST_DIMENSIONS:
            value = None if raw is None else _declared_list(raw)
        else:
            value = None if raw is None else _declared_scalar(raw)
        reason = None
        if raw is None:
            reason = f"{dimension} not declared in {rel}"
        elif value is None:
            reason = f"{dimension} declaration in {rel} is not a usable value"
        findings.append(
            _finding(
                dimension,
                value,
                kind=ProvenanceKind.DECLARED,
                source_ref=rel,
                evidence_refs=[rel],
                reason=reason,
            )
        )
    return rel, findings


def propose_classification_findings(
    root: Path,
    entries: list[RepoEntry],
    observations: list[ProjectObservation],
    *,
    max_file_bytes: int,
) -> list[ClassificationFinding]:
    findings: list[ClassificationFinding] = []

    declared_rel, declared_findings = declared_classification_findings(
        root, entries, max_file_bytes=max_file_bytes
    )
    findings.extend(declared_findings)
    declared_dimensions = {finding.dimension for finding in declared_findings}

    if "intake_mode" not in declared_dimensions:
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
        signals: tuple[tuple[str, bool], ...] = (
            ("source tree with at least three source files", has_code_tree and len(code_files) >= 3),
            ("CI workflow definitions", has_ci),
            ("existing Foundry artifacts", has_foundry),
            ("deploy or runtime manifest", has_deploy),
            ("at least eight source files", len(code_files) >= 8),
        )
        present = [name for name, matched in signals if matched]
        if present:
            findings.append(
                _finding(
                    "intake_mode",
                    IntakeMode.BROWNFIELD.value,
                    kind=ProvenanceKind.INFERRED,
                    source_ref=".",
                    confidence=_signal_strength_confidence(len(present), len(signals)),
                    evidence_refs=sorted(set(evidence_refs)),
                    reason=(
                        f"{len(present)} of {len(signals)} brownfield signals present: "
                        + "; ".join(present)
                    ),
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
                    reason=(
                        "no brownfield signals present; checked: "
                        + "; ".join(name for name, _ in signals)
                    ),
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

    # A dimension the declaration already answered is not re-reported as unknown:
    # an owner declaration is the highest-precedence evidence there is, and two
    # findings for one dimension would put a 0.0-confidence guess beside it.
    for dimension in CLASSIFICATION_DIMENSIONS:
        if dimension in declared_dimensions:
            continue
        if dimension == "intake_mode":
            continue
        reason = (
            "no declared project manifest"
            if declared_rel is None
            else f"{dimension} not readable from {declared_rel}"
        )
        findings.append(_unknown(dimension, reason=reason))

    findings.sort(key=lambda f: (f.dimension, f.value or "", tuple(f.evidence_refs)))
    return findings
