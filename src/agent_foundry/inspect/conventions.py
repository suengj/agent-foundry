"""Discover local conventions with evidence — never promote observed rules to normative."""

from __future__ import annotations

import re
from pathlib import Path

from agent_foundry.models.common import Provenance, ProvenanceKind
from agent_foundry.models.project import ConventionSpec, ProjectObservation
from agent_foundry.inspect.traversal import read_text_bounded, relative_posix


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


def discover_conventions(
    root: Path,
    observations: list[ProjectObservation],
) -> list[ConventionSpec]:
    conventions: list[ConventionSpec] = []

    agent_paths = sorted(
        {
            obs.provenance.source_ref
            for obs in observations
            if obs.subject == "agent-instruction-surface" and obs.provenance.source_ref
        }
    )
    for rel in agent_paths:
        path = root / rel
        content = read_text_bounded(path)
        if not content:
            continue
        if "pytest" in content.lower():
            conventions.append(
                _convention(
                    "test-runner",
                    "agent instructions reference pytest",
                    rel,
                    "pytest mentioned in instruction surface",
                    confidence=0.85,
                )
            )
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

    makefile = root / "Makefile"
    if makefile.is_file():
        content = read_text_bounded(makefile)
        if content and "pytest" in content:
            conventions.append(
                _convention(
                    "test-invocation",
                    "Makefile invokes pytest",
                    "Makefile",
                    "pytest referenced in Makefile",
                    confidence=0.9,
                )
            )

    workflows = root / ".github" / "workflows"
    if workflows.is_dir():
        for wf in sorted(workflows.glob("*.y*ml")):
            rel = relative_posix(root, wf)
            content = read_text_bounded(wf)
            if not content:
                continue
            if "actions/checkout" in content:
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
