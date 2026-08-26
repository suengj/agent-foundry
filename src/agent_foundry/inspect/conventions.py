"""Discover local conventions with evidence — never promote observed rules to normative."""

from __future__ import annotations

import re
from pathlib import Path

from agent_foundry.models.common import Provenance, ProvenanceKind
from agent_foundry.models.project import ConventionSpec, ProjectObservation
from agent_foundry.inspect.collectors import _makefile_declared_targets
from agent_foundry.inspect.traversal import (
    CI_WORKFLOW_PREFIX,
    RepoEntry,
    file_entries,
    read_entry_text,
)


def _convention(
    subject: str,
    pattern: str,
    source_ref: str,
    evidence: str,
    *,
    confidence: float,
    kind: ProvenanceKind = ProvenanceKind.OBSERVED,
) -> ConventionSpec:
    return ConventionSpec(
        subject=subject,
        pattern=pattern,
        source_ref=source_ref,
        evidence=evidence,
        confidence=confidence,
        provenance=Provenance(kind=kind, confidence=confidence, source_ref=source_ref),
    )


def _pytest_line_stance(line: str) -> str | None:
    if not re.search(r"\bpytest\b", line, re.IGNORECASE):
        return None
    if re.search(r"\bnot\s+pytest\b|,\s*not\s+pytest\b", line, re.IGNORECASE):
        return "reject"
    return "prescribe"


def _pytest_stance(content: str) -> str | None:
    stances: set[str] = set()
    for line in content.splitlines():
        stance = _pytest_line_stance(line)
        if stance is not None:
            stances.add(stance)
    if not stances:
        return None
    if "reject" in stances:
        return "reject"
    return "prescribe"


def discover_conventions(
    root: Path,
    entries: list[RepoEntry],
    observations: list[ProjectObservation],
    *,
    max_file_bytes: int,
) -> list[ConventionSpec]:
    conventions: list[ConventionSpec] = []
    entry_by_path = {entry.relative_path: entry for entry in file_entries(entries)}

    agent_paths = sorted(
        {
            obs.provenance.source_ref
            for obs in observations
            if obs.subject == "agent-instruction-surface" and obs.provenance.source_ref
        }
    )
    prescribe_refs: list[str] = []
    reject_refs: list[str] = []
    for rel in agent_paths:
        entry = entry_by_path.get(rel)
        if entry is None:
            continue
        content = read_entry_text(root, entry, max_bytes=max_file_bytes)
        if not content:
            continue
        stance = _pytest_stance(content)
        if stance == "prescribe":
            prescribe_refs.append(rel)
            conventions.append(
                _convention(
                    "test-runner",
                    "agent instructions reference pytest",
                    rel,
                    "pytest mentioned without negation in instruction surface",
                    confidence=0.85,
                )
            )
        elif stance == "reject":
            reject_refs.append(rel)

        if re.search(r"\bcommit\b.*\bnot\b|\bdo not commit\b", content, re.IGNORECASE):
            conventions.append(
                _convention(
                    "git-policy",
                    "agent instructions constrain commit behavior",
                    rel,
                    "commit guard language present in instruction surface",
                    confidence=0.8,
                )
            )

    if prescribe_refs and reject_refs:
        conventions.append(
            _convention(
                "test-runner-disagreement",
                "agent instruction surfaces disagree on pytest vs alternatives",
                prescribe_refs[0],
                (
                    "pytest prescribed in "
                    + ", ".join(prescribe_refs)
                    + "; rejected in "
                    + ", ".join(reject_refs)
                ),
                confidence=0.9,
            )
        )

    makefile_entry = entry_by_path.get("Makefile")
    if makefile_entry is not None:
        content = read_entry_text(root, makefile_entry, max_bytes=max_file_bytes)
        if content and "pytest" in content and "test" in _makefile_declared_targets(content):
            conventions.append(
                _convention(
                    "test-invocation",
                    "Makefile invokes pytest",
                    "Makefile",
                    "pytest referenced in Makefile test target",
                    confidence=0.9,
                )
            )

    for entry in file_entries(entries):
        rel = entry.relative_path
        if not rel.startswith(CI_WORKFLOW_PREFIX):
            continue
        if Path(rel).suffix not in {".yml", ".yaml"}:
            continue
        content = read_entry_text(root, entry, max_bytes=max_file_bytes)
        if content and "actions/checkout" in content:
            conventions.append(
                _convention(
                    "ci-checkout",
                    "CI workflow uses checkout action pattern",
                    rel,
                    "actions/checkout step observed",
                    confidence=0.95,
                )
            )

    conventions.sort(key=lambda c: (c.subject, c.source_ref, c.pattern))
    return conventions
