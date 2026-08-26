"""Discover local conventions with evidence — never promote observed rules to normative."""

from __future__ import annotations

import re
from pathlib import Path

from agent_foundry.models.common import Provenance, ProvenanceKind
from agent_foundry.models.project import ConventionSpec, ProjectObservation
from agent_foundry.inspect.collectors import makefile_declared_targets
from agent_foundry.inspect.traversal import (
    CI_WORKFLOW_PREFIX,
    RepoEntry,
    file_entries,
    read_entry_text,
)

TEST_RUNNER_SUBJECT = "test-runner"
MENTION_CONFIDENCE = 0.5
_MENTION_PATTERN = "instruction surface mentions pytest"


def lines_mentioning_subject(content: str, subject: str) -> list[str]:
    pattern = re.compile(rf"\b{re.escape(subject)}\b", re.IGNORECASE)
    quoted: list[str] = []
    for line in content.splitlines():
        if pattern.search(line):
            quoted.append(line.strip())
    return quoted


def _mention_convention(source_ref: str, quoted_line: str) -> ConventionSpec:
    return ConventionSpec(
        subject=TEST_RUNNER_SUBJECT,
        pattern=_MENTION_PATTERN,
        source_ref=source_ref,
        evidence=quoted_line,
        confidence=MENTION_CONFIDENCE,
        provenance=Provenance(
            kind=ProvenanceKind.INFERRED,
            confidence=MENTION_CONFIDENCE,
            source_ref=source_ref,
        ),
    )


def _convention(
    subject: str,
    pattern: str,
    source_ref: str,
    evidence: str,
    *,
    confidence: float,
    kind: ProvenanceKind = ProvenanceKind.INFERRED,
) -> ConventionSpec:
    return ConventionSpec(
        subject=subject,
        pattern=pattern,
        source_ref=source_ref,
        evidence=evidence,
        confidence=confidence,
        provenance=Provenance(kind=kind, confidence=confidence, source_ref=source_ref),
    )


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
    for rel in agent_paths:
        entry = entry_by_path.get(rel)
        if entry is None:
            continue
        content = read_entry_text(root, entry, max_bytes=max_file_bytes)
        if not content:
            continue
        for quoted_line in lines_mentioning_subject(content, "pytest"):
            conventions.append(_mention_convention(rel, quoted_line))

        if re.search(r"\bcommit\b.*\bnot\b|\bdo not commit\b", content, re.IGNORECASE):
            conventions.append(
                _convention(
                    "git-policy",
                    "instruction surface mentions commit constraints",
                    rel,
                    next(
                        (
                            line.strip()
                            for line in content.splitlines()
                            if re.search(r"\bcommit\b", line, re.IGNORECASE)
                        ),
                        "commit guard language present",
                    ),
                    confidence=0.5,
                )
            )

    makefile_entry = entry_by_path.get("Makefile")
    if makefile_entry is not None:
        content = read_entry_text(root, makefile_entry, max_bytes=max_file_bytes)
        if content and "pytest" in content and "test" in makefile_declared_targets(content):
            conventions.append(
                _convention(
                    "test-invocation",
                    "Makefile mentions pytest near a test target",
                    "Makefile",
                    "pytest referenced in Makefile",
                    confidence=0.5,
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
                    "CI workflow mentions checkout action pattern",
                    rel,
                    "actions/checkout step present",
                    confidence=0.5,
                )
            )

    conventions.sort(key=lambda c: (c.subject, c.source_ref, c.pattern))
    return conventions
