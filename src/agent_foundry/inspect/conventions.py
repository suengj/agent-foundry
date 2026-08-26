"""Discover local conventions with evidence — never promote observed rules to normative."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from agent_foundry.models.common import Provenance, ProvenanceKind
from agent_foundry.models.project import ConventionSpec, ProjectObservation
from agent_foundry.inspect.collectors import makefile_recipe_lines
from agent_foundry.inspect.traversal import (
    CI_WORKFLOW_PREFIX,
    RepoEntry,
    file_entries,
    read_entry_text,
)

TEST_RUNNER_SUBJECT = "test-runner"
MENTION_CONFIDENCE = 0.5
_MENTION_PATTERN = "instruction surface mentions pytest"

# A convention's evidence must be the text that actually produced the claim. These
# patterns are applied per line so the quoted line and the match are the same line.
_COMMIT_CONSTRAINT_PATTERN = re.compile(
    r"\bcommit\b.*\bnot\b|\bdo not commit\b", re.IGNORECASE
)
_CHECKOUT_ACTION = "actions/checkout"
_MAKEFILE_TEST_TARGET = "test"

# make consumes these recipe-line prefixes before handing the rest to the shell, so
# "@# pytest" reaches the shell as "# pytest" — a comment, not an invocation.
_MAKE_RECIPE_PREFIXES = "@-+"


def lines_matching(content: str, pattern: re.Pattern[str]) -> list[str]:
    """Return the stripped source lines that *pattern* matches, in file order."""
    return [line.strip() for line in content.splitlines() if pattern.search(line)]


def strip_trailing_comment(line: str) -> str:
    """Return the part of *line* that is not a trailing comment.

    POSIX shell and YAML agree on the rule: ``#`` opens a comment only outside
    quotes and only at the start of a word. A ``#`` inside a quoted string
    (``echo "a # b"``) is data, so treating it as a comment would drop a
    legitimate line — the opposite failure from the one this guards against.
    """
    quote: str | None = None
    index = 0
    while index < len(line):
        char = line[index]
        if quote == "'":
            if char == "'":
                quote = None
        elif quote == '"':
            if char == "\\":
                index += 1
            elif char == '"':
                quote = None
        elif char == "\\":
            index += 1
        elif char in "'\"":
            quote = char
        elif char == "#" and (index == 0 or line[index - 1].isspace()):
            return line[:index]
        index += 1
    return line


def executable_recipe_text(recipe_line: str) -> str:
    """The part of a Makefile recipe line the shell would actually execute."""
    return strip_trailing_comment(
        recipe_line.lstrip("\t").lstrip(_MAKE_RECIPE_PREFIXES)
    ).strip()


def workflow_checkout_uses(content: str) -> list[str]:
    """``uses`` values of workflow steps that actually configure a checkout.

    Read structurally rather than by line match: ``actions/checkout`` appearing in
    a comment, in a ``run:`` script, or anywhere outside ``jobs.*.steps[*].uses``
    does not configure a checkout, and a convention claiming otherwise would be a
    false factual claim. An unparseable workflow establishes nothing.
    """
    try:
        parsed = yaml.safe_load(content)
    except yaml.YAMLError:
        return []
    if not isinstance(parsed, dict):
        return []
    jobs = parsed.get("jobs")
    if not isinstance(jobs, dict):
        return []
    checkout_uses: list[str] = []
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps")
        if not isinstance(steps, list):
            continue
        for step in steps:
            if not isinstance(step, dict):
                continue
            uses = step.get("uses")
            if isinstance(uses, str) and uses.split("@", 1)[0].strip() == _CHECKOUT_ACTION:
                checkout_uses.append(uses)
    return checkout_uses


def evidence_lines_for_values(content: str, values: list[str]) -> list[str]:
    """Quote one distinct, non-comment source line per value in *values*."""
    candidates = list(enumerate(content.splitlines()))
    consumed: set[int] = set()
    quoted: list[str] = []
    for value in values:
        for index, line in candidates:
            if index in consumed or value not in strip_trailing_comment(line):
                continue
            consumed.add(index)
            quoted.append(line.strip())
            break
    return quoted


def lines_mentioning_subject(content: str, subject: str) -> list[str]:
    return lines_matching(content, re.compile(rf"\b{re.escape(subject)}\b", re.IGNORECASE))


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

        for quoted_line in lines_matching(content, _COMMIT_CONSTRAINT_PATTERN):
            conventions.append(
                _convention(
                    "git-policy",
                    "instruction surface line mentions a commit constraint",
                    rel,
                    quoted_line,
                    confidence=0.5,
                )
            )

    makefile_entry = entry_by_path.get("Makefile")
    if makefile_entry is not None:
        content = read_entry_text(root, makefile_entry, max_bytes=max_file_bytes)
        if content:
            for recipe_line in makefile_recipe_lines(content, _MAKEFILE_TEST_TARGET):
                # A commented-out recipe line executes nothing, so it cannot support
                # a claim that the target invokes pytest.
                if "pytest" not in executable_recipe_text(recipe_line):
                    continue
                conventions.append(
                    _convention(
                        "test-invocation",
                        "Makefile 'test' target recipe invokes pytest",
                        "Makefile",
                        recipe_line.strip(),
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
        if not content:
            continue
        checkout_uses = workflow_checkout_uses(content)
        for quoted_line in evidence_lines_for_values(content, checkout_uses):
            conventions.append(
                _convention(
                    "ci-checkout",
                    "CI workflow configures a checkout step",
                    rel,
                    quoted_line,
                    confidence=0.5,
                )
            )

    conventions.sort(key=lambda c: (c.subject, c.source_ref, c.pattern))
    return conventions
