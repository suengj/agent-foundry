"""Discover local conventions with evidence — never promote observed rules to normative.

Precedence, by design: a structured declaration (a Makefile ``test`` recipe, a
``pyproject.toml [tool.pytest.ini_options]`` table, ...) and a bare textual mention of
the same subject ("run the tests with pytest") are not equal-strength evidence, and
this module never lets them look equal. A structured fact is parsed with a real
parser (``tomllib``/``configparser``/``json``) and lands as a ``test-invocation``
convention at :data:`STRUCTURED_CONFIDENCE` with ``provenance.kind == DECLARED``. A
mention lands as a ``test-runner`` convention at :data:`MENTION_CONFIDENCE` (or lower,
see :data:`DEMOTED_MENTION_CONFIDENCE`) with ``provenance.kind == INFERRED``.

Demotion is subject-scoped, not repo-scoped. A mention is lowered only when a
structured declaration exists that concerns *the same runner the mention names* —
a ``package.json`` whose ``scripts.test`` is ``"jest"`` is a real declaration, but
it says nothing about pytest and so must not lower the confidence of a pytest
mention. Confidence has to be earned, and lost, on evidence about that subject.

A demoted mention is lowered, never dropped: readiness's cross-surface
reconciliation check (``unreconciled-subject-mentions``) still needs every mention
to see when instruction surfaces disagree, even after a structured fact is known.
Suppressing the mention would hide that disagreement instead of ranking it.

The demotion is carried by ``confidence`` alone. ``pattern`` states what was found
in the project and nothing else: it is one of the fields relevance-matched against a
work item's text downstream (``compile/context.py``), so any Foundry commentary
written into it becomes tokens a work item can match on, manufacturing relevance out
of Foundry's own words rather than the project's.
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

# A convention's evidence must be the text that actually produced the claim. These
# patterns are applied per line so the quoted line and the match are the same line.
_COMMIT_CONSTRAINT_PATTERN = re.compile(
    r"\bcommit\b.*\bnot\b|\bdo not commit\b", re.IGNORECASE
)
# The literal ``"test"`` key of a JSON object, with its colon — anywhere on the line,
# so a minified single-line document is still quotable. The colon is required so a
# longer key such as ``"testMatch"`` cannot be mistaken for it.
_TEST_KEY_PATTERN = re.compile(r'"test"\s*:')
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
    # The pattern is identical either way: it reports what the project's text says,
    # and demotion is not something the project's text says. Only the confidence
    # (and, through it, every confidence-ordered consumer) moves.
    return ConventionSpec(
        subject=TEST_RUNNER_SUBJECT,
        pattern=_MENTION_PATTERN,
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


def _package_json_test_script(content: str) -> tuple[str, str] | None:
    """The declared ``scripts.test`` command and its literal source line, if any.

    ``json`` alone decides whether ``scripts.test`` exists and what its value is.
    The raw text is consulted only afterward, to recover that key's own line: the
    line must carry the literal ``"test"`` key followed by its colon *and* the value
    round-tripped through ``json.dumps`` to the exact parsed string. Anything else
    (unusual escaping, a value split across lines) yields nothing rather than a guess.

    The key need not begin the line. A minified ``package.json`` — the common shape
    for a generated file — puts the whole document on one physical line, and that
    line is the verbatim source text carrying the declaration, so it is quotable
    evidence like any other. Requiring the key to *start* the line silently dropped
    a real ``DECLARED`` fact for every such file. The cost is that the quoted line is
    then the whole document; it is not truncated, because a shortened quote would no
    longer be the source text it claims to be.

    This does not judge *which* runner the command invokes, or whether it is a
    real test suite versus a stub — a ``scripts.test`` entry is a declared fact
    the owner wrote, full stop. Callers decide what (if anything) further to
    claim about its content; this function's only job is recovering the
    verbatim declaration and the line that proves it.
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

    expected_value = json.dumps(test_script)
    for line in content.splitlines():
        stripped = line.strip()
        if _TEST_KEY_PATTERN.search(stripped) and expected_value in stripped:
            return test_script, stripped
    return None


def _script_invokes_pytest(test_script: str) -> bool:
    """Whether one of *test_script*'s whitespace-separated words names pytest
    directly, or via ``python -m pytest`` (any ``python``/``python3``/``python3.x``
    spelling). Purely structural token matching — no shell parsing, no guessing
    about commands this does not recognize."""
    tokens = test_script.split()
    for index, token in enumerate(tokens):
        name = token.rsplit("/", 1)[-1]
        if name == _PYTEST_COMMAND:
            return True
        if (
            re.match(r"^python(3(\.\d+)?)?$", name)
            and index + 2 < len(tokens)
            and tokens[index + 1] == "-m"
            and tokens[index + 2].rsplit("/", 1)[-1] == _PYTEST_COMMAND
        ):
            return True
    return False


def _structured_test_invocation_conventions(
    entry_by_path: dict[str, RepoEntry],
    root: Path,
    *,
    max_file_bytes: int,
) -> tuple[list[ConventionSpec], bool]:
    """Structured (non-Makefile) ``test-invocation`` declarations, and whether any
    of them actually names pytest.

    Every format here is read with the parser built for it — never regex applied to
    prose — and a file that parser cannot make sense of contributes nothing, on the
    same fail-closed footing as every other detector in this module.

    The second element is the only thing entitled to demote a pytest *mention*.
    Not every ``test-invocation`` declaration concerns pytest: a ``package.json``
    ``scripts.test`` of ``"jest"`` is a genuine declaration this returns, and it is
    evidence about jest, so it is reported as ``False`` here.
    """
    conventions: list[ConventionSpec] = []
    names_pytest = False

    def _read(rel: str) -> str | None:
        entry = entry_by_path.get(rel)
        if entry is None:
            return None
        return read_entry_text(root, entry, max_bytes=max_file_bytes)

    pyproject = _read("pyproject.toml")
    if pyproject:
        line = _pyproject_pytest_ini_options_line(pyproject)
        if line is not None:
            names_pytest = True
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
            names_pytest = True
            conventions.append(_structured_convention(label, rel, line))

    package_json = _read("package.json")
    if package_json:
        found = _package_json_test_script(package_json)
        if found is not None:
            test_script, line = found
            if _script_invokes_pytest(test_script):
                names_pytest = True
                pattern = "package.json 'test' script invokes pytest"
            else:
                # The declaration is real and directly parsed, but naming which
                # runner (if any) it invokes would be an inference this module
                # does not make. Quote the command verbatim instead of either
                # discarding it (a false "no test entrypoint" negative) or
                # guessing a runner (a false positive).
                pattern = f"package.json 'test' script is {json.dumps(test_script)}"
            conventions.append(
                _structured_convention(pattern, "package.json", line)
            )

    return conventions, names_pytest


def discover_conventions(
    root: Path,
    entries: list[RepoEntry],
    observations: list[ProjectObservation],
    *,
    max_file_bytes: int,
) -> list[ConventionSpec]:
    conventions: list[ConventionSpec] = []
    entry_by_path = {entry.relative_path: entry for entry in file_entries(entries)}
    # Set only by a declaration that names pytest itself. See the demotion comment
    # below: this is what a pytest mention is ranked against, and nothing else.
    pytest_declared = False

    makefile_entry = entry_by_path.get("Makefile")
    if makefile_entry is not None:
        content = read_entry_text(root, makefile_entry, max_bytes=max_file_bytes)
        if content:
            for quoted_line in recipe_lines_invoking(
                content, _MAKEFILE_TEST_TARGET, _PYTEST_COMMAND
            ):
                pytest_declared = True
                conventions.append(
                    _structured_convention(
                        "Makefile 'test' target recipe invokes pytest",
                        "Makefile",
                        quoted_line,
                    )
                )

    structured, structured_names_pytest = _structured_test_invocation_conventions(
        entry_by_path, root, max_file_bytes=max_file_bytes
    )
    conventions.extend(structured)
    # A pytest mention is demoted the moment a structured declaration *about pytest*
    # exists anywhere in the repository — precedence is a repo-wide fact about what
    # is already known, not something scoped to the one file the mention happens to
    # live in. It is not, however, subject-blind: testing merely for the presence of
    # some `test-invocation` convention would let a `package.json` declaring
    # `"test": "jest"` lower the confidence of the only pytest evidence in the
    # repository, which is a claim about pytest earned from evidence about jest.
    pytest_declared = pytest_declared or structured_names_pytest

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
                _mention_convention(rel, quoted_line, demoted=pytest_declared)
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
