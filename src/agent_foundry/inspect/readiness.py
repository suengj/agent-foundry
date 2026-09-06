"""Readiness assessment from inspection evidence — findings, not vanity scores.

**Absence is not evidence, mirroring ``profile/synth.py``.** A readiness finding
that says "no X was observed" is only honest when the walk that produced
``observations`` actually covered the whole tree. ``TraversalStats`` (when the
caller has one to give) and the ``path-unobservable`` / ``file-read-skipped``
observations the collectors already emit (available regardless of whether a
caller threads ``TraversalStats`` through — see below) both describe genuine
holes: ground the walk could not see, not ground where nothing was there. A
*deliberately skipped* directory (``.git`` and the rest of ``SKIP_DIR_NAMES``)
is different in kind — a documented, bounded exclusion, not an unknown hole —
so it never forces a finding to become unknown; it only qualifies a resolved
"none observed" claim to say explicitly that directories were skipped, exactly
as ``profile.synth._scope_none_observed`` does for profile dimensions.

**Two ways a hole reaches this module.** ``entries_unobservable`` and
``entries_skipped`` in the raw walk are richer than what an observation can
carry, and ``depth_limit_reached`` / ``entry_limit_reached`` /
``entries_skipped_refused`` have no observation representation at all — only
``TraversalStats`` carries them. So ``assess_readiness`` accepts an optional
``stats`` parameter: when a caller has a ``TraversalStats`` to give, depth/entry
limits and containment refusals are detected too; when it does not, this module
still detects the two hole kinds that already have their own observation
subjects (``path-unobservable``, ``file-read-skipped``) independently of
``stats``, because those flow through ``observations`` regardless. Passing
``stats`` only ever adds detection power; it never removes any.

``inspect.api`` does pass it, and has to: without ``stats`` the three hole kinds
that travel nowhere else are undetectable in production no matter what this
module can do, so a bounded or refused walk would report its absences as
settled. That is why the call site builds ``TraversalStats`` before assessing
readiness rather than after. The parameter stays optional for callers holding
only observations, not as a default the pipeline is content to take.

**Path hole vs. content hole.** ``depth_limit_reached`` / ``entry_limit_reached``
/ ``entries_skipped_refused`` / ``path-unobservable`` are *path* holes: ground
the walk never even saw, so it does not know what is there — not even a
filename. ``file-read-skipped`` is different in kind: the walk saw the entry,
recorded its name, and only declined to read its *content* (see
``DEFAULT_MAX_FILE_BYTES``). Every dimension finding in this module is derived
from filename/path presence — a deploy marker, an integration-config filename,
a package-metadata filename, an agent-instruction-surface path, and so on —
never from what is inside the file. So a size-skipped file cannot make any of
those findings unknown: the walk already knows the name either way. Only the
single ``inspection-completeness`` summary finding, which describes the walk
as a whole rather than any one dimension, folds the content hole in alongside
the path holes. Should a future dimension in this module ever be derived from
file *content* rather than filename presence, it would need to gate on
``_content_hole_descriptions`` (or the combined ``_hole_descriptions``)
directly, the way ``profile/synth.py``'s ``_traversal_exhaustive`` (which takes
an ``unread_file_count`` of its own, for content-derived profile dimensions)
already must.
"""

from __future__ import annotations

from pathlib import Path

from agent_foundry.models.common import ConsequenceClass, Provenance, ProvenanceKind
from agent_foundry.models.project import (
    ConventionSpec,
    ProjectObservation,
    ReadinessFinding,
    TraversalStats,
)


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


def _path_hole_descriptions(
    observations: list[ProjectObservation],
    stats: TraversalStats | None,
) -> list[str]:
    """Describe every genuine *path* hole the walk left, in fixed, deterministic order.

    A path hole is a location the walk could not see at all — a depth or entry
    limit, a containment refusal, or an unobservable path — as opposed to a
    location the walk saw and named but whose *content* it declined to read
    (``file-read-skipped``; see ``_content_hole_descriptions``). An empty list
    means the walked tree's paths were covered without a hole — never that
    nothing exists beyond it (a deliberately skipped directory is scoping, not
    a hole, and is reported separately by ``_scope_absence``).
    """
    holes: list[str] = []
    if stats is not None:
        if stats.depth_limit_reached:
            holes.append("depth limit reached")
        if stats.entry_limit_reached:
            holes.append("entry limit reached")
        if stats.entries_skipped_refused:
            holes.append(f"{stats.entries_skipped_refused} containment-refused path(s)")
    unobservable_count = sum(1 for obs in observations if obs.subject == "path-unobservable")
    if unobservable_count:
        holes.append(f"{unobservable_count} unobservable path(s)")
    return holes


def _content_hole_descriptions(*, unread_file_count: int) -> list[str]:
    """Describe the genuine *content* hole a size-skipped file leaves.

    A size-skipped file is not an unobserved path — the walk saw it, named it,
    and knows exactly where it is; only its content is unread. This can only
    ever affect a finding whose truth depends on file content. A finding
    derived purely from filename/path presence (deploy markers, integration
    markers, package-metadata filenames, agent-instruction filenames, and so
    on — every dimension this module currently derives) is unaffected: the
    walk already knows the name either way.
    """
    if unread_file_count:
        return [f"{unread_file_count} file(s) skipped for exceeding the read-size limit"]
    return []


def _hole_descriptions(
    observations: list[ProjectObservation],
    stats: TraversalStats | None,
    *,
    unread_file_count: int,
) -> list[str]:
    """All genuine holes — path holes followed by content holes — for the
    single, always-present inspection-completeness summary, which reports on
    the walk as a whole rather than on any one filename-derived dimension.
    """
    return _path_hole_descriptions(observations, stats) + _content_hole_descriptions(
        unread_file_count=unread_file_count
    )


def _traversal_exhaustive(
    observations: list[ProjectObservation],
    stats: TraversalStats | None,
) -> bool:
    """True only when the walk left no genuine *path* hole in the ground it covered.

    Every finding in this module that consults this flag is derived from
    filename/path presence, never from file content, so a content-only hole
    (a file skipped for size) must never make such a finding read as unknown —
    the walk still knows the file's name. Only a path hole — ground the walk
    could not even see — can make a filename-derived finding genuinely unknown.
    """
    return not _path_hole_descriptions(observations, stats)


def _scope_absence(message: str, stats: TraversalStats | None) -> str:
    """Qualify a resolved "none observed" claim when directories were skipped.

    Mirrors ``profile.synth._scope_none_observed``: "none observed" is only ever
    a claim about the ground the walk actually covered, and a `.git`-style skip
    (true of nearly every real repository) must not silently read as universal.
    """
    if stats is None or stats.entries_skipped_ignored_dir <= 0:
        return message
    return (
        f"{message} (outside skipped directories; "
        f"entries_skipped_ignored_dir={stats.entries_skipped_ignored_dir})"
    )


def _unknown_absence_message(topic: str, holes: list[str]) -> str:
    """Replace a would-be absence claim with an explicit "not fully observed" one."""
    detail = "; ".join(holes)
    return (
        f"{topic} not confirmed — inspection was not fully observed ({detail}); "
        "absence cannot be concluded from a partial walk"
    )


def _inspection_completeness_finding(
    observations: list[ProjectObservation],
    stats: TraversalStats | None,
    *,
    unread_file_count: int,
) -> ReadinessFinding:
    """A single, always-present finding naming the walk's own coverage.

    This is the one place a reader can see, without cross-referencing anything
    else, whether every other "not observed" finding in this report reflects a
    genuine absence or an unobserved region.
    """
    holes = _hole_descriptions(observations, stats, unread_file_count=unread_file_count)
    if not holes:
        message = _scope_absence(
            "Inspection walked the tree without leaving a genuine hole", stats
        )
        return _finding(
            "inspection-completeness",
            ConsequenceClass.LOW,
            message,
            kind=ProvenanceKind.OBSERVED,
            confidence=1.0,
        )
    detail = "; ".join(holes)
    return _finding(
        "inspection-completeness",
        ConsequenceClass.HIGH,
        (
            f"Inspection was not fully observed: {detail}. Findings elsewhere in this "
            "report that would otherwise read as confirmed absence are withheld or "
            "explicitly qualified instead."
        ),
        kind=ProvenanceKind.OBSERVED,
        confidence=0.0,
    )


def assess_readiness(
    root: Path,
    observations: list[ProjectObservation],
    conventions: list[ConventionSpec] | None = None,
    *,
    stats: TraversalStats | None = None,
) -> list[ReadinessFinding]:
    findings: list[ReadinessFinding] = []
    conventions = conventions or []
    subjects = {obs.subject for obs in observations}
    source_refs = {
        obs.provenance.source_ref
        for obs in observations
        if obs.provenance.source_ref
    }
    unread_file_count = sum(1 for obs in observations if obs.subject == "file-read-skipped")
    # Every dimension finding below is derived from filename/path presence, never
    # from file content, so it is gated on path holes only — a size-skipped file's
    # content is irrelevant to whether the walk observed its name. Only the
    # inspection-completeness summary (below) reports the content hole too.
    exhaustive = _traversal_exhaustive(observations, stats)
    holes = _path_hole_descriptions(observations, stats)

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
    elif not exhaustive:
        findings.append(
            _finding(
                "repository-legibility",
                ConsequenceClass.HIGH,
                _unknown_absence_message("Repository structure", holes),
                blocker=True,
                confidence=0.0,
            )
        )
    else:
        findings.append(
            _finding(
                "repository-legibility",
                ConsequenceClass.HIGH,
                _scope_absence("Repository structure could not be established", stats),
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
    elif not exhaustive:
        findings.append(
            _finding(
                "reproducibility",
                ConsequenceClass.MEDIUM,
                _unknown_absence_message("Package or Foundry metadata surfaces", holes),
                confidence=0.0,
            )
        )
    else:
        findings.append(
            _finding(
                "reproducibility",
                ConsequenceClass.MEDIUM,
                _scope_absence(
                    "No package metadata or Foundry declaration observed for reproducibility",
                    stats,
                ),
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
    elif not exhaustive:
        findings.append(
            _finding(
                "testability",
                ConsequenceClass.MEDIUM,
                _unknown_absence_message("Test entrypoints", holes),
                confidence=0.0,
            )
        )
    else:
        findings.append(
            _finding(
                "testability",
                ConsequenceClass.MEDIUM,
                _scope_absence("No test entrypoints observed", stats),
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
    elif not exhaustive:
        findings.append(
            _finding(
                "authority-ownership-clarity",
                ConsequenceClass.MEDIUM,
                _unknown_absence_message("Project docs or agent instruction surfaces", holes),
                confidence=0.0,
            )
        )
    else:
        findings.append(
            _finding(
                "authority-ownership-clarity",
                ConsequenceClass.MEDIUM,
                _scope_absence("No project docs or agent instruction surfaces observed", stats),
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
    elif not exhaustive:
        findings.append(
            _finding(
                "runtime-isolation",
                ConsequenceClass.MEDIUM,
                _unknown_absence_message("Deploy/runtime surfaces", holes),
                confidence=0.0,
            )
        )
    else:
        findings.append(
            _finding(
                "runtime-isolation",
                ConsequenceClass.LOW,
                _scope_absence("No deploy/runtime surfaces observed in repository inventory", stats),
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
    elif not exhaustive:
        findings.append(
            _finding(
                "credential-permission-isolation",
                ConsequenceClass.MEDIUM,
                _unknown_absence_message("Integration or credential declaration surfaces", holes),
                confidence=0.0,
            )
        )
    else:
        findings.append(
            _finding(
                "credential-permission-isolation",
                ConsequenceClass.LOW,
                _scope_absence("No integration declaration surfaces observed", stats),
                confidence=0.55,
            )
        )

    agent_surfaces = sorted(
        ref for ref in source_refs if ref and ("AGENTS" in ref or "CLAUDE" in ref or ".cursor" in ref)
    )
    mention_surfaces = sorted({conv.source_ref for conv in conventions if conv.subject == "test-runner"})
    if len(mention_surfaces) >= 2:
        findings.append(
            _finding(
                "unreconciled-subject-mentions",
                ConsequenceClass.HIGH,
                (
                    "Multiple agent instruction surfaces reference test-runner "
                    "and have not been reconciled"
                ),
                kind=ProvenanceKind.INFERRED,
                confidence=0.5,
                source_ref=mention_surfaces[0],
            )
        )
    if len(agent_surfaces) >= 2:
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
    elif not exhaustive:
        findings.append(
            _finding(
                "fragmented-agent-rule-surfaces",
                ConsequenceClass.MEDIUM,
                _unknown_absence_message("Agent instruction surfaces", holes),
                confidence=0.0,
            )
        )
    else:
        findings.append(
            _finding(
                "fragmented-agent-rule-surfaces",
                ConsequenceClass.MEDIUM,
                _scope_absence("No agent instruction surfaces observed", stats),
                confidence=0.6,
            )
        )

    findings.append(
        _inspection_completeness_finding(observations, stats, unread_file_count=unread_file_count)
    )

    findings.sort(key=lambda f: (f.dimension, f.severity.value, f.message))
    return findings
