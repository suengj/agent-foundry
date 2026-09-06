"""Discover local conventions with evidence — never promote observed rules to normative.

Precedence, by design: a structured declaration (a Makefile ``test`` recipe, a
``pyproject.toml [tool.pytest.ini_options]`` table, ...) and a bare textual mention of
the same subject ("run the tests with pytest") are not equal-strength evidence, and
this module never lets them look equal. A structured fact is parsed with a real
parser (``tomllib``/``configparser``/``json``) and lands as a ``test-invocation``
convention at :data:`STRUCTURED_CONFIDENCE` with ``provenance.kind == DECLARED``. A
mention lands as a ``test-runner`` convention at :data:`MENTION_CONFIDENCE` (or lower,
see :data:`DEMOTED_MENTION_CONFIDENCE`) with ``provenance.kind == INFERRED``. Whenever
at least one structured declaration exists anywhere in the repository, every mention
convention is demoted — confidence lowered and its pattern text marked superseded —
rather than dropped: readiness's cross-surface reconciliation check
(``unreconciled-subject-mentions``) still needs every mention to see when instruction
surfaces disagree, even after a structured fact is known. Suppressing the mention
would hide that disagreement instead of ranking it.
"""

from __future__ import annotations

import configparser
import json
import re
import tomllib
from pathlib import Path

from agent_foundry.models.common import Provenance, ProvenanceKind
from agent_foundry.models.project import ConventionSpec, ProjectObservation
from agent_foundry.inspect.evidence import recipe_lines_invoking, workflow_steps_using
from agent_foundry.inspect.traversal import (
    CI_WORKFLOW_PREFIX,
    RepoEntry,
    file_entries,
    read_entry_text,
)

TEST_RUNNER_SUBJECT = "test-runner"
TEST_INVOCATION_SUBJECT = "test-invocation"

MENTION_CONFIDENCE = 0.5
# Applied instead of MENTION_CONFIDENCE once a structured test-invocation
# declaration exists anywhere in the repository. Still an INFERRED mention — the
# text itself did not become more trustworthy — but ranked below every structured
# fact so a confidence-ordered consumer never treats the two as equal.
DEMOTED_MENTION_CONFIDENCE = 0.15
STRUCTURED_CONFIDENCE = 0.8

_MENTION_PATTERN = "instruction surface mentions pytest"
_MENTION_PATTERN_SUPERSEDED = (
    "instruction surface mentions pytest (a structured test-invocation declaration "
    "also exists and takes precedence)"
)

# A convention's evidence must be the text that actually produced the claim. These
# patterns are applied per line so the quoted line and the match are the same line.
_COMMIT_CONSTRAINT_PATTERN = re.compile(
    r"\bcommit\b.*\bnot\b|\bdo not commit\b", re.IGNORECASE
)
_CHECKOUT_ACTION = "actions/checkout"
_MAKEFILE_TEST_TARGET = "test"
_PYTEST_COMMAND = "pytest"


def lines_matching(content: str, pattern: re.Pattern[str]) -> list[str]:
    """Return the stripped source lines that *pattern* matches, in file order."""
    return [line.strip() for line in content.splitlines() if pattern.search(line)]


def lines_mentioning_subject(content: str, subject: str) -> list[str]:
    return lines_matching(content, re.compile(rf"\b{re.escape(subject)}\b", re.IGNORECASE))


def _mention_convention(source_ref: str, quoted_line: str, *, demoted: bool) -> ConventionSpec:
    confidence = DEMOTED_MENTION_CONFIDENCE if demoted else MENTION_CONFIDENCE
    pattern = _MENTION_PATTERN_SUPERSEDED if demoted else _MENTION_PATTERN
    return ConventionSpec(
        subject=TEST_RUNNER_SUBJECT,
        pattern=pattern,
        source_ref=source_ref,
        evidence=quoted_line,
        confidence=confidence,
        provenance=Provenance(
            kind=ProvenanceKind.INFERRED,
            confidence=confidence,
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


def _structured_convention(pattern: str, source_ref: str, evidence: str) -> ConventionSpec:
    return _convention(
        TEST_INVOCATION_SUBJECT,
        pattern,
        source_ref,
        evidence,
        confidence=STRUCTURED_CONFIDENCE,
        kind=ProvenanceKind.DECLARED,
    )


def _exact_stripped_line(content: str, target: str) -> str | None:
    """The single physical line whose stripped text is exactly *target*, if any.

    Used to recover a structured file's own source text for a fact a real parser
    (``tomllib``/``configparser``/``json``) already established structurally. If no
    line's literal text matches exactly — an unusual layout (quoted dotted keys, a
    section header split across lines) this does not attempt to normalise — nothing
    is returned rather than quoting an approximate or wrong line.
    """
    for line in content.splitlines():
        if line.strip() == target:
            return target
    return None


def _pyproject_pytest_ini_options_line(content: str) -> str | None:
    """The ``[tool.pytest.ini_options]`` header line, when that table is declared.

    Structural truth comes from ``tomllib`` alone: only once it confirms the table
    exists is the raw text consulted, purely to recover the line it lives on. A
    file ``tomllib`` cannot parse yields no convention rather than a regex guess.
    """
    try:
        data = tomllib.loads(content)
    except tomllib.TOMLDecodeError:
        return None
    tool = data.get("tool")
    if not isinstance(tool, dict):
        return None
    pytest_table = tool.get("pytest")
    if not isinstance(pytest_table, dict) or "ini_options" not in pytest_table:
        return None
    header = re.compile(r"^\[\s*tool\s*\.\s*pytest\s*\.\s*ini_options\s*\]$")
    for line in content.splitlines():
        if header.match(line.strip()):
            return line.strip()
    return None


def _ini_section_header_line(content: str, section: str) -> str | None:
    """The ``[section]`` header line, when *section* is a real section of *content*.

    Structural truth comes from ``configparser`` alone; the raw text is consulted
    only to recover the header's own line. A file that does not parse as INI, or
    that lacks the section, yields no convention.
    """
    parser = configparser.ConfigParser()
    try:
        parser.read_string(content)
    except configparser.Error:
        return None
    if section not in parser:
        return None
    return _exact_stripped_line(content, f"[{section}]")


def _package_json_pytest_script_line(content: str) -> str | None:
    """The literal ``"test"`` script line, when it structurally invokes pytest.

    ``json`` alone decides whether ``scripts.test`` exists and whether one of its
    whitespace-separated words names pytest directly or via ``python -m pytest``.
    The raw text is consulted only afterward, to recover that key's own line, and
    only a line whose value round-trips through ``json.dumps`` to the exact parsed
    string counts as that line — anything else (unusual escaping, a value split
    across lines) yields no convention rather than a guess.
    """
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    scripts = data.get("scripts")
    if not isinstance(scripts, dict):
        return None
    test_script = scripts.get("test")
    if not isinstance(test_script, str) or not test_script.strip():
        return None

    tokens = test_script.split()
    invokes_pytest = False
    for index, token in enumerate(tokens):
        name = token.rsplit("/", 1)[-1]
        if name == _PYTEST_COMMAND:
            invokes_pytest = True
            break
        if (
            re.match(r"^python(3(\.\d+)?)?$", name)
            and index + 2 < len(tokens)
            and tokens[index + 1] == "-m"
            and tokens[index + 2].rsplit("/", 1)[-1] == _PYTEST_COMMAND
        ):
            invokes_pytest = True
            break
    if not invokes_pytest:
        return None

    expected_value = json.dumps(test_script)
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith('"test"') and expected_value in stripped:
            return stripped
    return None


def _structured_test_invocation_conventions(
    entry_by_path: dict[str, RepoEntry],
    root: Path,
    *,
    max_file_bytes: int,
) -> list[ConventionSpec]:
    """Structured (non-Makefile) declarations that the project's tests run on pytest.

    Every format here is read with the parser built for it — never regex applied to
    prose — and a file that parser cannot make sense of contributes nothing, on the
    same fail-closed footing as every other detector in this module.
    """
    conventions: list[ConventionSpec] = []

    def _read(rel: str) -> str | None:
        entry = entry_by_path.get(rel)
        if entry is None:
            return None
        return read_entry_text(root, entry, max_bytes=max_file_bytes)

    pyproject = _read("pyproject.toml")
    if pyproject:
        line = _pyproject_pytest_ini_options_line(pyproject)
        if line is not None:
            conventions.append(
                _structured_convention(
                    "pyproject.toml declares [tool.pytest.ini_options]",
                    "pyproject.toml",
                    line,
                )
            )

    for rel, section, label in (
        ("pytest.ini", "pytest", "pytest.ini declares a [pytest] section"),
        ("tox.ini", "pytest", "tox.ini declares a [pytest] section"),
        ("setup.cfg", "tool:pytest", "setup.cfg declares a [tool:pytest] section"),
    ):
        content = _read(rel)
        if not content:
            continue
        line = _ini_section_header_line(content, section)
        if line is not None:
            conventions.append(_structured_convention(label, rel, line))

    package_json = _read("package.json")
    if package_json:
        line = _package_json_pytest_script_line(package_json)
        if line is not None:
            conventions.append(
                _structured_convention(
                    "package.json 'test' script invokes pytest",
                    "package.json",
                    line,
                )
            )

    return conventions


def discover_conventions(
    root: Path,
    entries: list[RepoEntry],
    observations: list[ProjectObservation],
    *,
    max_file_bytes: int,
) -> list[ConventionSpec]:
    conventions: list[ConventionSpec] = []
    entry_by_path = {entry.relative_path: entry for entry in file_entries(entries)}

    makefile_entry = entry_by_path.get("Makefile")
    if makefile_entry is not None:
        content = read_entry_text(root, makefile_entry, max_bytes=max_file_bytes)
        if content:
            for quoted_line in recipe_lines_invoking(
                content, _MAKEFILE_TEST_TARGET, _PYTEST_COMMAND
            ):
                conventions.append(
                    _structured_convention(
                        "Makefile 'test' target recipe invokes pytest",
                        "Makefile",
                        quoted_line,
                    )
                )

    conventions.extend(
        _structured_test_invocation_conventions(
            entry_by_path, root, max_file_bytes=max_file_bytes
        )
    )

    # A mention is demoted the moment any structured declaration exists anywhere in
    # the repository — precedence is a repo-wide fact about what is already known,
    # not something scoped to the one file the mention happens to live in.
    structured_pytest_declared = any(
        conv.subject == TEST_INVOCATION_SUBJECT for conv in conventions
    )

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
            conventions.append(
                _mention_convention(rel, quoted_line, demoted=structured_pytest_declared)
            )

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

    for entry in file_entries(entries):
        rel = entry.relative_path
        if not rel.startswith(CI_WORKFLOW_PREFIX):
            continue
        if Path(rel).suffix not in {".yml", ".yaml"}:
            continue
        content = read_entry_text(root, entry, max_bytes=max_file_bytes)
        if not content:
            continue
        for quoted_line in workflow_steps_using(content, _CHECKOUT_ACTION):
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
