"""SUE-580 — false-positive / false-negative mutation cases for convention discovery.

A false convention is worse than a missing one, so this file weighs the two halves
unevenly on purpose:

* **False positives** — text that *looks* like a structured test declaration but
  is not one (a name-drop in a code fence, an empty Makefile recipe, a
  ``package.json`` script that does not actually invoke pytest, ...). For each,
  the assertion is precise about *which* claim must be absent: several of these
  correctly still produce a weak ``test-runner`` mention (an
  ``INFERRED``/``DEMOTED_MENTION_CONFIDENCE``-or-``MENTION_CONFIDENCE`` fact) —
  the wrong claim to rule out is the *structured* ``test-invocation`` declaration
  at :data:`STRUCTURED_CONFIDENCE`/``DECLARED``, not "no convention whatsoever".

* **False negatives** — a real declaration wearing an unusual but legal shape
  (``.PHONY`` before a Makefile target, a tab-indented multi-line ``@``-prefixed
  recipe, a TOML table written with odd whitespace far from the top of the file,
  a compound ``package.json`` test script). Each must still be found, with the
  right subject, confidence, provenance kind, and ``source_ref``.

All repositories here are synthesized under ``tmp_path`` — nothing is a
committed fixture.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_foundry.inspect import inspect_project
from agent_foundry.inspect.conventions import (
    DEMOTED_MENTION_CONFIDENCE,
    MENTION_CONFIDENCE,
    STRUCTURED_CONFIDENCE,
    TEST_INVOCATION_SUBJECT,
    TEST_RUNNER_SUBJECT,
)
from agent_foundry.models.common import ProvenanceKind


def _conventions(intake, subject: str) -> list:
    return [c for c in intake.conventions if c.subject == subject]


# =================================================================================
# False positives — must NOT claim a structured test-invocation declaration
# =================================================================================


def test_pytest_inside_code_fence_is_a_mention_not_a_declaration(tmp_path: Path) -> None:
    """A code fence name-dropping pytest is prose, not a structured fact.

    AGENTS.md is a real instruction surface (scanned for mentions), so the word
    "pytest" appearing inside a fenced example is expected to still surface as a
    weak, undemoted ``test-runner`` mention — the module does no markdown/comment
    parsing, so it cannot and should not distinguish "inside a fence" from
    ordinary prose for that weaker claim. What it must never do is let a code
    example promote itself to a structured ``test-invocation`` declaration.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text(
        "Example session:\n"
        "```\n"
        "$ pytest\n"
        "collected 3 items\n"
        "```\n",
        encoding="utf-8",
    )
    intake = inspect_project(repo)

    assert _conventions(intake, TEST_INVOCATION_SUBJECT) == []
    mentions = _conventions(intake, TEST_RUNNER_SUBJECT)
    assert len(mentions) == 1
    assert mentions[0].provenance.kind is ProvenanceKind.INFERRED
    assert mentions[0].confidence == MENTION_CONFIDENCE


def test_pytest_in_changelog_entry_is_a_mention_not_a_declaration(tmp_path: Path) -> None:
    """A changelog line noting a past pytest upgrade is not a runner declaration."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text(
        "## Changelog\n"
        "- Bumped pytest from 7.x to 8.0 in CI images.\n",
        encoding="utf-8",
    )
    intake = inspect_project(repo)

    assert _conventions(intake, TEST_INVOCATION_SUBJECT) == []
    mentions = _conventions(intake, TEST_RUNNER_SUBJECT)
    assert len(mentions) == 1
    assert "pytest" in mentions[0].evidence.lower()


def test_pytest_ini_options_heading_in_markdown_is_not_a_pyproject_declaration(
    tmp_path: Path,
) -> None:
    """A markdown doc that *quotes* a ``[tool.pytest.ini_options]`` heading.

    Structured detection for this fact is scoped to an actual ``pyproject.toml``
    parsed with ``tomllib`` — a markdown document merely showing the heading (as
    documentation of the convention, say) must not be mistaken for the table
    itself. The line still contains the word "pytest", so a weaker mention is the
    correct, expected side effect — not silence.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text(
        "Our pytest configuration lives under the following heading:\n"
        "\n"
        "    [tool.pytest.ini_options]\n"
        "    testpaths = [\"tests\"]\n",
        encoding="utf-8",
    )
    intake = inspect_project(repo)

    assert _conventions(intake, TEST_INVOCATION_SUBJECT) == []
    mentions = _conventions(intake, TEST_RUNNER_SUBJECT)
    assert len(mentions) >= 1


def test_package_json_with_no_test_script_yields_nothing(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "package.json").write_text(
        '{"name": "demo", "scripts": {"build": "tsc"}}\n', encoding="utf-8"
    )
    intake = inspect_project(repo)
    assert _conventions(intake, TEST_INVOCATION_SUBJECT) == []


def test_package_json_test_script_that_deliberately_fails_is_not_pytest(
    tmp_path: Path,
) -> None:
    """``scripts.test`` exists and is non-empty, but names no test runner at all."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "package.json").write_text(
        '{\n'
        '  "name": "demo",\n'
        '  "scripts": {\n'
        '    "test": "echo \\"no tests\\" && exit 1"\n'
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    intake = inspect_project(repo)
    assert _conventions(intake, TEST_INVOCATION_SUBJECT) == []


def test_makefile_test_target_with_empty_recipe_yields_nothing(tmp_path: Path) -> None:
    """A ``test:`` target exists but its recipe invokes nothing recognizable."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "Makefile").write_text(
        "test:\n\t@echo \"see CONTRIBUTING.md for how to run tests\"\n",
        encoding="utf-8",
    )
    intake = inspect_project(repo)
    assert _conventions(intake, TEST_INVOCATION_SUBJECT) == []


def test_tox_ini_without_pytest_section_yields_nothing(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "tox.ini").write_text(
        "[tox]\nenvlist = py311\n\n[testenv]\ncommands = python -m unittest\n",
        encoding="utf-8",
    )
    intake = inspect_project(repo)
    assert _conventions(intake, TEST_INVOCATION_SUBJECT) == []


# =================================================================================
# False negatives — a real declaration in an unusual but legal shape must be found
# =================================================================================


def test_makefile_phony_before_target_and_at_prefixed_multiline_recipe_is_found(
    tmp_path: Path,
) -> None:
    """``.PHONY`` line ahead of the target, a multi-line ``@``-quieted recipe."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "Makefile").write_text(
        ".PHONY: test\n"
        "test:\n"
        "\t@echo \"running tests\"\n"
        "\t@pytest -q\n",
        encoding="utf-8",
    )
    intake = inspect_project(repo)

    found = _conventions(intake, TEST_INVOCATION_SUBJECT)
    assert len(found) == 1
    convention = found[0]
    assert convention.source_ref == "Makefile"
    assert convention.provenance.kind is ProvenanceKind.DECLARED
    assert convention.confidence == STRUCTURED_CONFIDENCE
    assert "pytest" in convention.evidence
    assert convention.evidence == '@pytest -q'


def test_pyproject_pytest_table_far_from_top_with_odd_whitespace_is_found(
    tmp_path: Path,
) -> None:
    """The table is legal TOML, just not the first table, and oddly spaced."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        "[project]\n"
        'name = "demo"\n'
        "\n"
        "[tool.other-plugin]\n"
        "setting = 1\n"
        "\n"
        "[  tool.pytest.ini_options ]\n"
        'testpaths = ["tests"]\n',
        encoding="utf-8",
    )
    intake = inspect_project(repo)

    found = _conventions(intake, TEST_INVOCATION_SUBJECT)
    assert len(found) == 1
    convention = found[0]
    assert convention.source_ref == "pyproject.toml"
    assert convention.provenance.kind is ProvenanceKind.DECLARED
    assert convention.confidence == STRUCTURED_CONFIDENCE
    assert convention.evidence == "[  tool.pytest.ini_options ]"


def test_setup_cfg_tool_pytest_section_amid_other_sections_is_found(
    tmp_path: Path,
) -> None:
    """``[tool:pytest]`` is legal anywhere in the file, interleaved with others."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "setup.cfg").write_text(
        "[metadata]\n"
        "name = demo\n"
        "\n"
        "[options]\n"
        "packages = find:\n"
        "\n"
        "[tool:pytest]\n"
        "testpaths = tests\n"
        "addopts = -q\n"
        "\n"
        "[flake8]\n"
        "max-line-length = 100\n",
        encoding="utf-8",
    )
    intake = inspect_project(repo)

    found = _conventions(intake, TEST_INVOCATION_SUBJECT)
    assert len(found) == 1
    convention = found[0]
    assert convention.source_ref == "setup.cfg"
    assert convention.provenance.kind is ProvenanceKind.DECLARED
    assert convention.evidence == "[tool:pytest]"


def test_package_json_compound_test_script_is_found(tmp_path: Path) -> None:
    """A realistic compound script (lint, then pytest) still counts as invoking it."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "package.json").write_text(
        '{\n'
        '  "name": "demo",\n'
        '  "scripts": {\n'
        '    "test": "flake8 . && pytest --maxfail=1 -q"\n'
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    intake = inspect_project(repo)

    found = _conventions(intake, TEST_INVOCATION_SUBJECT)
    assert len(found) == 1
    convention = found[0]
    assert convention.source_ref == "package.json"
    assert convention.provenance.kind is ProvenanceKind.DECLARED
    assert convention.confidence == STRUCTURED_CONFIDENCE
    assert "flake8 . && pytest --maxfail=1 -q" in convention.evidence


def test_structured_far_shaped_declaration_still_demotes_a_coexisting_mention(
    tmp_path: Path,
) -> None:
    """The two halves interact correctly: an odd-shaped structured fact still
    outranks a plain-prose mention once discovered, exactly as a conventionally
    shaped one would.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "setup.cfg").write_text(
        "[metadata]\nname = demo\n\n[tool:pytest]\ntestpaths = tests\n",
        encoding="utf-8",
    )
    (repo / "AGENTS.md").write_text("Run pytest before committing.\n", encoding="utf-8")
    intake = inspect_project(repo)

    structured = _conventions(intake, TEST_INVOCATION_SUBJECT)
    mentions = _conventions(intake, TEST_RUNNER_SUBJECT)
    assert len(structured) == 1
    assert len(mentions) == 1
    assert mentions[0].confidence == DEMOTED_MENTION_CONFIDENCE
    assert mentions[0].confidence < structured[0].confidence
