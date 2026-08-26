"""Readiness assessment from inspection evidence — findings, not vanity scores."""

from __future__ import annotations

from pathlib import Path

from agent_foundry.models.common import ConsequenceClass, Provenance, ProvenanceKind
from agent_foundry.models.project import ConventionSpec, ProjectObservation, ReadinessFinding


def _finding(
    dimension: str,
    severity: ConsequenceClass,
    message: str,
    *,
    blocker: bool = False,
    kind: ProvenanceKind = ProvenanceKind.INFERRED,
    confidence: float | None = None,
    source_ref: str = ".",
) -> ReadinessFinding:
    return ReadinessFinding(
        dimension=dimension,
        severity=severity,
        message=message,
        blocker=blocker,
        provenance=Provenance(kind=kind, confidence=confidence, source_ref=source_ref),
    )


def assess_readiness(
    root: Path,
    observations: list[ProjectObservation],
    conventions: list[ConventionSpec] | None = None,
) -> list[ReadinessFinding]:
    findings: list[ReadinessFinding] = []
    conventions = conventions or []
    subjects = {obs.subject for obs in observations}
    source_refs = {
        obs.provenance.source_ref
        for obs in observations
        if obs.provenance.source_ref
    }

    if "repository-structure" in subjects:
        findings.append(
            _finding(
                "repository-legibility",
                ConsequenceClass.LOW,
                "Repository structure is legible within traversal bounds",
                kind=ProvenanceKind.OBSERVED,
                confidence=0.9,
            )
        )
    else:
        findings.append(
            _finding(
                "repository-legibility",
                ConsequenceClass.HIGH,
                "Repository structure could not be established",
                blocker=True,
                confidence=0.5,
            )
        )

    has_metadata = any(obs.subject == "package-metadata" for obs in observations)
    has_foundry = any(obs.subject == "foundry-artifact" for obs in observations)
    if has_metadata or has_foundry:
        findings.append(
            _finding(
                "reproducibility",
                ConsequenceClass.LOW,
                "Package or Foundry metadata surfaces support reproducible setup",
                kind=ProvenanceKind.INFERRED,
                confidence=0.75,
            )
        )
    else:
        findings.append(
            _finding(
                "reproducibility",
                ConsequenceClass.MEDIUM,
                "No package metadata or Foundry declaration observed for reproducibility",
                confidence=0.6,
            )
        )

    has_tests = any(obs.subject == "test-entrypoint" for obs in observations)
    if has_tests:
        findings.append(
            _finding(
                "testability",
                ConsequenceClass.LOW,
                "Deterministic test entrypoints are observable",
                kind=ProvenanceKind.OBSERVED,
                confidence=0.9,
            )
        )
    else:
        findings.append(
            _finding(
                "testability",
                ConsequenceClass.MEDIUM,
                "No test entrypoints observed",
                confidence=0.7,
            )
        )

    findings.append(
        _finding(
            "observability",
            ConsequenceClass.MEDIUM,
            "Runtime observability cannot be confirmed from repository inventory alone",
            confidence=0.0,
        )
    )

    has_docs = any(obs.subject == "project-docs" for obs in observations)
    has_agents = any(obs.subject == "agent-instruction-surface" for obs in observations)
    if has_docs or has_agents:
        findings.append(
            _finding(
                "authority-ownership-clarity",
                ConsequenceClass.LOW,
                "Project docs or agent instruction surfaces provide ownership hints",
                kind=ProvenanceKind.OBSERVED,
                confidence=0.8,
            )
        )
    else:
        findings.append(
            _finding(
                "authority-ownership-clarity",
                ConsequenceClass.MEDIUM,
                "No project docs or agent instruction surfaces observed",
                confidence=0.65,
            )
        )

    deploy_hints = [obs for obs in observations if obs.subject == "runtime-deploy-hint"]
    if deploy_hints:
        findings.append(
            _finding(
                "runtime-isolation",
                ConsequenceClass.MEDIUM,
                "Deploy/runtime surfaces observed; isolation requirements need explicit review",
                kind=ProvenanceKind.INFERRED,
                confidence=0.6,
            )
        )
    else:
        findings.append(
            _finding(
                "runtime-isolation",
                ConsequenceClass.LOW,
                "No deploy/runtime surfaces observed in repository inventory",
                confidence=0.5,
            )
        )

    integration_surfaces = [obs for obs in observations if obs.subject == "integration-config"]
    if integration_surfaces:
        findings.append(
            _finding(
                "credential-permission-isolation",
                ConsequenceClass.MEDIUM,
                "Integration or credential declaration surfaces present; verify SecretRef usage",
                kind=ProvenanceKind.OBSERVED,
                confidence=0.85,
            )
        )
    else:
        findings.append(
            _finding(
                "credential-permission-isolation",
                ConsequenceClass.LOW,
                "No integration declaration surfaces observed",
                confidence=0.55,
            )
        )

    agent_surfaces = sorted(
        ref for ref in source_refs if ref and ("AGENTS" in ref or "CLAUDE" in ref or ".cursor" in ref)
    )
    test_runner_conflicts = [c for c in conventions if c.subject == "test-runner-disagreement"]
    if test_runner_conflicts:
        findings.append(
            _finding(
                "fragmented-agent-rule-surfaces",
                ConsequenceClass.HIGH,
                (
                    "Agent instruction surfaces disagree on test-runner conventions; "
                    "observed conflict must not be treated as normative without consolidation"
                ),
                kind=ProvenanceKind.OBSERVED,
                confidence=1.0,
                source_ref=test_runner_conflicts[0].source_ref,
            )
        )
    elif len(agent_surfaces) >= 2:
        findings.append(
            _finding(
                "fragmented-agent-rule-surfaces",
                ConsequenceClass.HIGH,
                (
                    "Multiple agent instruction surfaces observed; "
                    "observed behavior must not be treated as normative without consolidation"
                ),
                kind=ProvenanceKind.OBSERVED,
                confidence=1.0,
                source_ref=agent_surfaces[0],
            )
        )
    elif len(agent_surfaces) == 1:
        findings.append(
            _finding(
                "fragmented-agent-rule-surfaces",
                ConsequenceClass.LOW,
                "Single agent instruction surface observed",
                kind=ProvenanceKind.OBSERVED,
                confidence=0.9,
                source_ref=agent_surfaces[0],
            )
        )
    else:
        findings.append(
            _finding(
                "fragmented-agent-rule-surfaces",
                ConsequenceClass.MEDIUM,
                "No agent instruction surfaces observed",
                confidence=0.6,
            )
        )

    findings.sort(key=lambda f: (f.dimension, f.severity.value, f.message))
    return findings
