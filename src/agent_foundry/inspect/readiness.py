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
``DEFAULT_MAX_FILE_BYTES``).

*Most* dimension findings in this module are derived from filename/path
presence — a deploy marker, an integration-config filename, a package-metadata
filename, an agent-instruction-surface path — and for those a size-skipped file
cannot manufacture uncertainty: the walk knows the name either way. They gate on
``_traversal_exhaustive`` (path holes only).

``testability`` is **not** one of them. An earlier version of this docstring
claimed that every dimension here was filename-derived; that claim was false,
and the finding it excused was a confident false negative. ``test-entrypoint``
is emitted both by filename markers (``pytest.ini``, ``conftest.py``, ...) *and*
by a ``test:`` target parsed out of the Makefile's bytes
(``_MAKEFILE_TARGET_SUBJECTS`` in ``inspect/collectors.py``), so an unread
Makefile hides exactly the evidence whose absence would otherwise be reported at
0.7 confidence. It therefore gates on ``_content_traversal_exhaustive``,
agreeing with ``profile/synth.py``, which already classifies that same subject
as ``_SubjectDerivation.CONTENT``.

The full per-dimension audit is recorded here so the next reader does not have
to redo it, and so a wrong blanket claim cannot survive a second time:

* ``repository-legibility`` — ``repository-structure``: entry counts and
  top-level names taken off the walked entry list. NAME.
* ``reproducibility`` — ``package-metadata`` (filename match against
  ``PACKAGE_METADATA_FILES``) or ``foundry-artifact`` (a ``.foundry/`` path
  prefix). NAME. The content-derived ``foundry-declaration`` subject is
  deliberately not consulted, so no file is read to decide this.
* ``testability`` — ``test-entrypoint``. **CONTENT**: Makefile ``test:`` target.
* ``observability`` — a constant finding; it asserts no absence at all.
* ``authority-ownership-clarity`` — ``project-docs`` (``docs/ai/`` prefix, ``.md``
  suffix) and ``agent-instruction-surface`` (``AGENT_RULE_RELATIVE_PATHS`` plus
  the ``.cursor/rules`` prefix). NAME.
* ``runtime-isolation`` — ``runtime-deploy-hint``: deploy marker filenames and
  the ``deploy/`` prefix. NAME.
* ``credential-permission-isolation`` — ``integration-config``: marker
  filenames (``.env.example`` and friends). NAME.
* ``fragmented-agent-rule-surfaces`` — ``agent-instruction-surface``
  observations (``AGENT_RULE_RELATIVE_PATHS`` plus the ``.cursor/rules``
  prefix), read by **subject**. NAME. An earlier version of this row read
  "observation ``source_ref`` paths spelling ``AGENTS`` / ``CLAUDE`` /
  ``.cursor``. That a path exists is a name fact no matter which collector
  emitted the observation carrying it." Both halves were false, and the second
  is what hid the first. A ``source_ref`` is not an assertion that its path
  exists, let alone that a surface is there: a *rejected* ``nested-project``
  override decision carries the path of a directory the walk has just
  determined does **not** exist, and the substring scan republished exactly
  that path as an OBSERVED surface at confidence 1.0. It also outlived owner
  exclusions, so removing a surface left the finding still asserting it. Which
  collector emitted an observation is therefore not incidental — it is the
  whole of what the observation means, and only the subject records it.
* ``unreconciled-subject-mentions`` — ``ConventionSpec`` records, which *are*
  content-derived (``inspect/conventions.py``). This finding is emitted only
  when two or more such records exist: it makes no absence claim, so a content
  hole has nothing here to falsify. Should it ever grow an ``else`` branch, that
  branch must gate on ``_content_traversal_exhaustive``.
* ``inspection-completeness`` — reports every hole, path and content alike.

A future dimension derived from file *content* must gate on
``_content_traversal_exhaustive`` and pass ``_hole_descriptions`` (not
``_path_hole_descriptions``) to ``_unknown_absence_message``. A filename-derived
one keeps ``_traversal_exhaustive``. ``profile/synth.py``'s
``_SubjectDerivation`` makes the same distinction per call site.
"""

from __future__ import annotations

from pathlib import Path

from agent_foundry.inspect.classification import invalid_declaration_findings
from agent_foundry.models.common import ConsequenceClass, Provenance, ProvenanceKind
from agent_foundry.models.project import (
    ClassificationFinding,
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
    ever affect a finding whose truth depends on file content — in this module,
    ``testability``, whose ``test-entrypoint`` subject is also emitted from a
    Makefile ``test:`` target. A finding derived purely from filename/path
    presence (deploy markers, integration markers, package-metadata filenames,
    agent-instruction filenames) is unaffected: the walk already knows the name
    either way. The module docstring carries the per-dimension audit.
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

    This is the gate for a *name-derived* absence only. Such a finding is
    settled by the entry list, so a content-only hole (a file skipped for size)
    must never make it read as unknown — the walk still knows the file's name,
    and three oversized source files cannot change whether a ``Dockerfile``
    exists. Only a path hole — ground the walk could not even see — can make a
    filename-derived finding genuinely unknown.

    A *content-derived* absence needs more than this and must call
    ``_content_traversal_exhaustive`` instead.
    """
    return not _path_hole_descriptions(observations, stats)


def _content_traversal_exhaustive(
    observations: list[ProjectObservation],
    stats: TraversalStats | None,
    *,
    unread_file_count: int,
) -> bool:
    """True only when the walk left no genuine hole at all — path *or* content.

    This is the gate for an absence claim whose truth depends on what is inside
    a file. A file skipped for exceeding the read-size limit might hold exactly
    the thing whose absence is being reported (a Makefile ``test:`` target), so
    reporting "none observed" over it is a confident false negative, not an
    observation. Deliberately coarse, exactly as
    ``profile.synth._traversal_exhaustive`` is: any unread file anywhere forces
    every content-derived absence in this module to "not confirmed", because
    mapping each dimension to the specific files whose content could affect it
    would need updating every time a collector started reading a new file, and a
    stale mapping there fails open precisely where this module must fail closed.
    """
    return _traversal_exhaustive(observations, stats) and unread_file_count == 0


#: Imported from the collector that writes it rather than spelled again here. The
#: ``nested-project`` subject also carries override *decisions* — including rejected
#: ones, whose ``source_ref`` is a path that is not a boundary at all — and
#: supersession notes, so the subject alone cannot answer "which subtrees were
#: excluded", and this prefix is what separates a boundary record from the rest.
#: Re-typing it here would put the same string in two places and let the reader
#: drift silently away from the writer, which is exactly how a scope note goes
#: missing without any test noticing.
from agent_foundry.inspect.collectors import (  # noqa: E402  (placed with its rationale)
    NESTED_BOUNDARY_CONTENT_PREFIX,
)


def nested_boundary_refs(
    observations: list[ProjectObservation],
) -> list[str]:
    """Every nested-project boundary, sorted — owner-declared *and* manifest-detected.

    An earlier version returned only the owner-declared half, on the argument
    that a subtree carrying its own project manifest is a *different project*,
    so its files were never candidates for "this project's" claims and naming it
    in an absence message adds nothing. That asymmetry has been overturned, for
    three reasons.

    **The note is printed, and it is wrong.** ``_scope_absence`` does not stay
    silent about exclusions; it *enumerates* them. Under the old rule a
    uv/poetry-style workspace — root ``pyproject.toml`` with
    ``[tool.uv.workspace] members = ["packages/*"]``, a ``Dockerfile`` under
    ``packages/api`` — published "No deploy/runtime surfaces observed in
    repository inventory (outside skipped directories; ...)". A reader handed a
    list of the exclusions that shaped a claim reads it as *the* list, so
    enumerating one exclusion and suppressing another is worse than enumerating
    neither.

    **"Different project" is Foundry's inference, not the owner's.**
    ``traversal.nested_project_roots`` fires on any subdirectory
    ``pyproject.toml`` / ``package.json`` / ``go.mod`` / ``setup.py``. In the
    workspace case that inference is simply false: the root's own
    ``[tool.uv.workspace]`` is the owner declaring these are one project, and
    the heuristic overrides it. So the manifest-detected half is the half where
    *no human asserted anything*, which makes it the weaker claim to leave
    unscoped, not the stronger — exactly backwards from the old justification.

    **There is no principled line.** ``vendor`` and ``node_modules`` are "not
    this project" by precisely the same reasoning, and they are scoped.

    ``tests/e2e/test_e2e_project_boundary.py`` already carves out
    ``repository-structure`` from its "planting a project changes nothing"
    contract, because a new directory existing *is* a fact about the target. A
    scope note is the same class of fact: that the diagnosis no longer covers
    ground it previously covered. The test now states that.

    Boundary records are still identified by the content prefix
    ``collect_nested_project_observations`` writes, because the
    ``nested-project`` subject also carries override *decisions* (a rejected one
    names a path that is not a boundary at all — it does not exist) and
    supersession notes. Only the ``DECLARED`` provenance filter is gone. This
    couples the helper to that collector's wording; the end-to-end scoping tests
    fail loudly if it drifts rather than silently dropping the scope note.
    """
    return sorted(
        {
            obs.provenance.source_ref
            for obs in observations
            if obs.subject == "nested-project"
            and obs.content.startswith(NESTED_BOUNDARY_CONTENT_PREFIX)
            and obs.provenance.source_ref
        }
    )


def _scope_absence(
    message: str,
    stats: TraversalStats | None,
    *,
    nested_boundaries: list[str] | None = None,
) -> str:
    """Qualify a resolved "none observed" claim by the ground it does not cover.

    Mirrors ``profile.synth._scope_none_observed``: "none observed" is only ever
    a claim about the ground the walk actually covered, and a `.git`-style skip
    (true of nearly every real repository) must not silently read as universal.

    A nested-project exclusion is an exclusion of exactly the same kind and gets
    exactly the same treatment, whether the owner declared it or a manifest
    triggered it. With either kind covering a directory that holds a container
    manifest, this module would otherwise report no deploy surface at all, as a
    flat unscoped claim. That the exclusion is recoverable by cross-referencing
    another finding is precisely the cross-referencing this scoping exists to
    make unnecessary — and this function *enumerates* the exclusions it applies,
    so listing one kind and hiding the other reads as a complete list that is
    not one. See ``nested_boundary_refs`` for why the earlier asymmetry was
    wrong.
    """
    scopes: list[str] = []
    if stats is not None and stats.entries_skipped_ignored_dir > 0:
        scopes.append(
            "skipped directories; "
            f"entries_skipped_ignored_dir={stats.entries_skipped_ignored_dir}"
        )
    if nested_boundaries:
        scopes.append("nested project boundaries: " + ", ".join(nested_boundaries))
    if not scopes:
        return message
    return f"{message} (outside {' and '.join(scopes)})"


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
    path_holes = _path_hole_descriptions(observations, stats)
    content_holes = _content_hole_descriptions(unread_file_count=unread_file_count)
    holes = path_holes + content_holes
    if not holes:
        message = _scope_absence(
            "Inspection walked the tree without leaving a genuine hole",
            stats,
            nested_boundaries=nested_boundary_refs(observations),
        )
        return _finding(
            "inspection-completeness",
            ConsequenceClass.LOW,
            message,
            kind=ProvenanceKind.OBSERVED,
            confidence=1.0,
        )
    detail = "; ".join(holes)
    # The summary must not vouch for more than the report actually does. A path
    # hole withholds every absence claim here; a content-only hole withholds
    # only the content-derived ones (``testability``), because a filename-derived
    # absence is still directly observed over an unread file. Saying "findings
    # elsewhere ... are withheld" in that second case would certify something
    # false about the findings sitting next to it.
    if path_holes:
        scope = (
            "Findings elsewhere in this report that would otherwise read as "
            "confirmed absence are withheld or explicitly qualified instead."
        )
    else:
        scope = (
            "Content-derived findings elsewhere in this report that would otherwise "
            "read as confirmed absence are withheld or explicitly qualified instead; "
            "filename-derived findings still stand, because the walk recorded every "
            "name it saw."
        )
    return _finding(
        "inspection-completeness",
        ConsequenceClass.HIGH,
        f"Inspection was not fully observed: {detail}. {scope}",
        kind=ProvenanceKind.OBSERVED,
        confidence=0.0,
    )


def assess_readiness(
    root: Path,
    observations: list[ProjectObservation],
    conventions: list[ConventionSpec] | None = None,
    *,
    stats: TraversalStats | None = None,
    classification_findings: list[ClassificationFinding] | None = None,
) -> list[ReadinessFinding]:
    findings: list[ReadinessFinding] = []
    conventions = conventions or []
    # A declared value its vocabulary rejects is a fact about the repository the
    # owner can act on, so it is reported here beside every other readiness
    # finding rather than only on the adoption path. Without this, an owner's
    # typo reached nobody who merely inspected the project or read its profile:
    # the manifest refused the value correctly but only `plan_adoption` ever saw
    # the refusal, and the profile published the rejected token as RESOLVED.
    # The check makes no absence claim, so no traversal gate applies to it —
    # the declaration was read, and what it says is not in doubt.
    findings.extend(invalid_declaration_findings(classification_findings or []))
    subjects = {obs.subject for obs in observations}
    unread_file_count = sum(1 for obs in observations if obs.subject == "file-read-skipped")
    # Two gates, because this module publishes two kinds of absence claim. Most
    # dimensions below are decided by filename/path presence and are gated on
    # path holes only: a size-skipped file's content is irrelevant to whether the
    # walk observed its name, and degrading them over it would launder a hole in
    # one dimension's evidence into a hole in another's. `testability` is the
    # exception — `test-entrypoint` is also emitted from a Makefile `test:`
    # target — so it gates on the content hole as well. The module docstring
    # carries the per-dimension audit behind that split.
    exhaustive = _traversal_exhaustive(observations, stats)
    holes = _path_hole_descriptions(observations, stats)
    content_exhaustive = _content_traversal_exhaustive(
        observations, stats, unread_file_count=unread_file_count
    )
    content_holes = _hole_descriptions(observations, stats, unread_file_count=unread_file_count)
    # A resolved "none observed" claim is scoped by every exclusion that shaped
    # the evidence — deliberately skipped directories and owner/manifest nested
    # project boundaries alike.
    nested_boundaries = nested_boundary_refs(observations)

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
                _scope_absence(
                    "Repository structure could not be established",
                    stats,
                    nested_boundaries=nested_boundaries,
                ),
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
                    nested_boundaries=nested_boundaries,
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
    elif not content_exhaustive:
        # CONTENT-derived: `test-entrypoint` comes from marker filenames *and*
        # from a `test:` target parsed out of the Makefile's bytes, so an unread
        # Makefile is a genuine hole in this dimension's evidence. `content_holes`
        # (not `holes`) so the message names the read-size skip that caused it.
        findings.append(
            _finding(
                "testability",
                ConsequenceClass.MEDIUM,
                _unknown_absence_message("Test entrypoints", content_holes),
                confidence=0.0,
            )
        )
    else:
        findings.append(
            _finding(
                "testability",
                ConsequenceClass.MEDIUM,
                _scope_absence(
                    "No test entrypoints observed",
                    stats,
                    nested_boundaries=nested_boundaries,
                ),
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
                _scope_absence(
                    "No project docs or agent instruction surfaces observed",
                    stats,
                    nested_boundaries=nested_boundaries,
                ),
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
                _scope_absence(
                    "No deploy/runtime surfaces observed in repository inventory",
                    stats,
                    nested_boundaries=nested_boundaries,
                ),
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
                _scope_absence(
                    "No integration declaration surfaces observed",
                    stats,
                    nested_boundaries=nested_boundaries,
                ),
                confidence=0.55,
            )
        )

    # An instruction surface is a surface because a collector *observed one
    # there* — never because some path happens to spell `AGENTS`, `CLAUDE` or
    # `.cursor`. The subject is the only evidence that a surface exists, so it
    # is what this reads, agreeing with `profile/synth.py`'s
    # `instruction.fragmentation`. A substring scan over every observation's
    # `source_ref` counted paths that are not surfaces at all: a *rejected*
    # `nested-project` override decision carries the path of a directory the
    # walk has just determined does not exist, and republishing that as
    # "a surface was OBSERVED here" at confidence 1.0 is a false positive of
    # the same class as a false absence. It also ignored owner exclusions —
    # an owner who excludes `.cursor` still saw `.cursor/rules/note.md`
    # asserted as a live surface, because the excluded path survived in some
    # *other* observation's `source_ref`.
    agent_surfaces = sorted(
        {
            obs.provenance.source_ref
            for obs in observations
            if obs.subject == "agent-instruction-surface" and obs.provenance.source_ref
        }
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
                _scope_absence(
                    "No agent instruction surfaces observed",
                    stats,
                    nested_boundaries=nested_boundaries,
                ),
                confidence=0.6,
            )
        )

    findings.append(
        _inspection_completeness_finding(observations, stats, unread_file_count=unread_file_count)
    )

    findings.sort(key=lambda f: (f.dimension, f.severity.value, f.message))
    return findings
