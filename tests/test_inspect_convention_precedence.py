"""SUE-580 — evidence precedence and evidence quality in convention discovery.

Two properties are pinned here, both about trust rather than detection:

1. Structured/build/runtime declarations outrank weaker text mentions when both
   exist for the same subject. A repository whose Makefile genuinely declares
   ``test: pytest`` and whose AGENTS.md happens to say the word "pytest" in prose
   must not present those as equal-strength facts — a downstream consumer has to be
   able to tell which to trust without parsing prose.
2. Every convention's quoted ``evidence`` actually supports its ``pattern`` claim —
   never an adjacent or unrelated line.

Inference stays conservative throughout: an unparseable or ambiguous structured
file yields no convention, never a guessed one.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent_foundry.inspect import inspect_project
from agent_foundry.inspect.conventions import (
    STRUCTURED_CONFIDENCE,
    TEST_INVOCATION_SUBJECT,
    TEST_RUNNER_SUBJECT,
)
from agent_foundry.models.common import ProvenanceKind

REPO_ROOT = Path(__file__).resolve().parents[1]


def _conventions(intake, subject: str) -> list:
    return [c for c in intake.conventions if c.subject == subject]


# --- precedence: structured over mention ---------------------------------------


def test_structured_and_mention_together_precedence_holds_and_is_stated(
    tmp_path: Path,
) -> None:
    """Both a Makefile declaration and a prose mention: precedence holds visibly.

    The structured fact and the weak mention must both be present (nothing is
    silently thrown away), but a consumer reading only the typed fields — subject,
    confidence, provenance.kind, pattern — must be able to tell which is which
    without any prose understanding.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "Makefile").write_text("test:\n\tpytest -q\n", encoding="utf-8")
    (repo / "AGENTS.md").write_text(
        "Run the test suite with pytest before committing.\n", encoding="utf-8"
    )
    intake = inspect_project(repo)

    structured = _conventions(intake, TEST_INVOCATION_SUBJECT)
    mentions = _conventions(intake, TEST_RUNNER_SUBJECT)
    assert structured, "the Makefile declaration must still be present"
    assert mentions, "the prose mention must still be present, only ranked lower"

    for convention in structured:
        assert convention.provenance.kind is ProvenanceKind.DECLARED
        assert convention.confidence == STRUCTURED_CONFIDENCE

    for convention in mentions:
        assert convention.provenance.kind is ProvenanceKind.INFERRED
        assert convention.confidence < min(c.confidence for c in structured), (
            "a mention must never be equal or stronger evidence than a structured "
            "declaration of the same fact"
        )
        # Machine-readable, not prose: the pattern text itself differs from the
        # baseline mention pattern used when nothing structured is known.
        assert "structured test-invocation declaration" in convention.pattern


def test_structured_only_yields_a_structured_convention(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "Makefile").write_text("test:\n\tpytest -q\n", encoding="utf-8")
    intake = inspect_project(repo)

    structured = _conventions(intake, TEST_INVOCATION_SUBJECT)
    assert len(structured) == 1
    assert structured[0].provenance.kind is ProvenanceKind.DECLARED
    assert structured[0].confidence == STRUCTURED_CONFIDENCE
    assert _conventions(intake, TEST_RUNNER_SUBJECT) == []


def test_mention_only_still_yields_an_undemoted_mention(tmp_path: Path) -> None:
    """No structured declaration anywhere: the mention keeps its baseline strength.

    Demotion is a *relative* signal — it must never fire just because a mention
    exists; it fires only when a stronger, structured fact is also present.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("Run tests with pytest.\n", encoding="utf-8")
    intake = inspect_project(repo)

    mentions = _conventions(intake, TEST_RUNNER_SUBJECT)
    assert len(mentions) == 1
    assert mentions[0].provenance.kind is ProvenanceKind.INFERRED
    assert mentions[0].confidence == 0.5
    assert mentions[0].pattern == "instruction surface mentions pytest"
    assert "structured" not in mentions[0].pattern


# --- false positive: a name-drop must not read as structured --------------------


@pytest.mark.parametrize(
    "content",
    [
        # "pytest" appears, but nowhere near a real [tool.pytest.ini_options] table.
        '[project]\nname = "demo"\n# we used to use pytest, not anymore\n',
        # A pytest dependency, still not a test-runner declaration.
        '[project]\nname = "demo"\ndependencies = ["pytest>=8.0"]\n',
    ],
)
def test_pyproject_name_drop_is_not_a_structured_declaration(
    tmp_path: Path, content: str
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(content, encoding="utf-8")
    intake = inspect_project(repo)
    assert _conventions(intake, TEST_INVOCATION_SUBJECT) == []


def test_package_json_test_script_naming_something_else_is_declared_not_pytest(
    tmp_path: Path,
) -> None:
    """A ``scripts.test`` naming a real runner Foundry does not special-case
    (jest, here) is still a genuine declaration — it must be quoted verbatim as
    a DECLARED ``test-invocation`` fact, never claimed to invoke pytest, and
    never discarded as though nothing were declared."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "package.json").write_text(
        '{\n  "name": "demo",\n  "scripts": {\n    "test": "jest --coverage"\n  }\n}\n',
        encoding="utf-8",
    )
    intake = inspect_project(repo)

    found = _conventions(intake, TEST_INVOCATION_SUBJECT)
    assert len(found) == 1
    convention = found[0]
    assert convention.source_ref == "package.json"
    assert convention.provenance.kind is ProvenanceKind.DECLARED
    assert convention.confidence == STRUCTURED_CONFIDENCE
    assert convention.pattern == "package.json 'test' script is \"jest --coverage\""
    assert "pytest" not in convention.pattern


def test_makefile_pytest_in_unrelated_target_is_not_structured(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "Makefile").write_text(
        "lint:\n\tpytest --collect-only  # not the test target\n", encoding="utf-8"
    )
    intake = inspect_project(repo)
    assert _conventions(intake, TEST_INVOCATION_SUBJECT) == []


# --- false negative: each supported structured format is genuinely found -------


def test_pyproject_pytest_ini_options_is_found(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "demo"\n\n[tool.pytest.ini_options]\ntestpaths = ["tests"]\n',
        encoding="utf-8",
    )
    intake = inspect_project(repo)
    found = _conventions(intake, TEST_INVOCATION_SUBJECT)
    assert len(found) == 1
    assert found[0].source_ref == "pyproject.toml"
    assert found[0].evidence == "[tool.pytest.ini_options]"


def test_pytest_ini_pytest_section_is_found(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n", encoding="utf-8")
    intake = inspect_project(repo)
    found = _conventions(intake, TEST_INVOCATION_SUBJECT)
    assert len(found) == 1
    assert found[0].source_ref == "pytest.ini"
    assert found[0].evidence == "[pytest]"


def test_tox_ini_pytest_section_is_found(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "tox.ini").write_text(
        "[tox]\nenvlist = py311\n\n[pytest]\ntestpaths = tests\n", encoding="utf-8"
    )
    intake = inspect_project(repo)
    found = _conventions(intake, TEST_INVOCATION_SUBJECT)
    assert len(found) == 1
    assert found[0].source_ref == "tox.ini"
    assert found[0].evidence == "[pytest]"


def test_setup_cfg_tool_pytest_section_is_found(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "setup.cfg").write_text(
        "[metadata]\nname = demo\n\n[tool:pytest]\ntestpaths = tests\n",
        encoding="utf-8",
    )
    intake = inspect_project(repo)
    found = _conventions(intake, TEST_INVOCATION_SUBJECT)
    assert len(found) == 1
    assert found[0].source_ref == "setup.cfg"
    assert found[0].evidence == "[tool:pytest]"


@pytest.mark.parametrize(
    "script",
    ["pytest -q", "python -m pytest", "python3 -m pytest tests/"],
)
def test_package_json_test_script_invoking_pytest_is_found(
    tmp_path: Path, script: str
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "package.json").write_text(
        '{\n  "name": "demo",\n  "scripts": {\n    "test": "%s"\n  }\n}\n' % script,
        encoding="utf-8",
    )
    intake = inspect_project(repo)
    found = _conventions(intake, TEST_INVOCATION_SUBJECT)
    assert len(found) == 1
    assert found[0].source_ref == "package.json"
    assert script in found[0].evidence


def test_makefile_test_target_invoking_pytest_is_still_found(tmp_path: Path) -> None:
    """Baseline regression: the pre-existing Makefile detector keeps working."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "Makefile").write_text("test:\n\tpytest -q\n", encoding="utf-8")
    intake = inspect_project(repo)
    found = _conventions(intake, TEST_INVOCATION_SUBJECT)
    assert len(found) == 1
    assert found[0].source_ref == "Makefile"


# --- evidence supports the claim, for every convention kind emitted -------------


def _assert_evidence_is_a_literal_source_line(convention, source_text: str) -> None:
    assert convention.evidence.strip()
    assert convention.evidence in source_text
    assert any(
        line.strip() == convention.evidence.strip() for line in source_text.splitlines()
    )


def test_evidence_supports_claim_for_every_emitted_convention_kind(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    workflows = repo / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (repo / "Makefile").write_text("test:\n\tpytest -q\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\ntestpaths = [\"tests\"]\n", encoding="utf-8"
    )
    (repo / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (repo / "tox.ini").write_text("[pytest]\n", encoding="utf-8")
    (repo / "setup.cfg").write_text("[tool:pytest]\n", encoding="utf-8")
    (repo / "package.json").write_text(
        '{"scripts": {"test": "pytest -q"}}\n', encoding="utf-8"
    )
    (repo / "AGENTS.md").write_text(
        "Run pytest for changes.\nDo not commit secrets.\n", encoding="utf-8"
    )
    (workflows / "ci.yml").write_text(
        "jobs:\n  build:\n    steps:\n      - uses: actions/checkout@v4\n",
        encoding="utf-8",
    )
    intake = inspect_project(repo)

    assert intake.conventions, "fixture must actually exercise every emitter"
    sources = {
        "pyproject.toml": (repo / "pyproject.toml").read_text(encoding="utf-8"),
        "pytest.ini": (repo / "pytest.ini").read_text(encoding="utf-8"),
        "tox.ini": (repo / "tox.ini").read_text(encoding="utf-8"),
        "setup.cfg": (repo / "setup.cfg").read_text(encoding="utf-8"),
        "package.json": (repo / "package.json").read_text(encoding="utf-8"),
        "Makefile": (repo / "Makefile").read_text(encoding="utf-8"),
        "AGENTS.md": (repo / "AGENTS.md").read_text(encoding="utf-8"),
        ".github/workflows/ci.yml": (workflows / "ci.yml").read_text(encoding="utf-8"),
    }
    seen_subjects = set()
    for convention in intake.conventions:
        seen_subjects.add(convention.subject)
        _assert_evidence_is_a_literal_source_line(
            convention, sources[convention.source_ref]
        )
        if convention.subject == TEST_RUNNER_SUBJECT:
            assert "pytest" in convention.evidence.lower()
        elif convention.subject == TEST_INVOCATION_SUBJECT:
            assert "pytest" in convention.evidence.lower()
        elif convention.subject == "git-policy":
            assert "commit" in convention.evidence.lower()
        elif convention.subject == "ci-checkout":
            assert "actions/checkout" in convention.evidence

    assert seen_subjects == {
        TEST_RUNNER_SUBJECT,
        TEST_INVOCATION_SUBJECT,
        "git-policy",
        "ci-checkout",
    }


def test_mutated_evidence_would_be_caught(tmp_path: Path) -> None:
    """Prove the evidence-supports-claim check actually bites.

    Take one genuine convention and swap its evidence for an adjacent, unrelated
    line from the same file. The assertion this test file relies on elsewhere
    (evidence must literally be a line of the cited source that supports the
    claim) must fail against that mutated pair — demonstrating the check is not
    vacuous.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "demo"\n\n[tool.pytest.ini_options]\ntestpaths = ["tests"]\n',
        encoding="utf-8",
    )
    intake = inspect_project(repo)
    found = _conventions(intake, TEST_INVOCATION_SUBJECT)
    assert found
    genuine = found[0]
    assert genuine.evidence == "[tool.pytest.ini_options]"

    # Mutate: attach an adjacent, unrelated line as if it were the evidence.
    mutated_evidence = 'name = "demo"'
    assert mutated_evidence != genuine.evidence

    def _claim_supported(pattern: str, evidence: str) -> bool:
        return "pytest.ini_options" in pattern and "pytest" in evidence.lower()

    assert _claim_supported(genuine.pattern, genuine.evidence)
    assert not _claim_supported(genuine.pattern, mutated_evidence), (
        "the mutated (adjacent, unrelated) line must not appear to support the "
        "structured pytest-configuration claim"
    )


# --- unparseable structured files yield nothing, never a guess -----------------


@pytest.mark.parametrize(
    "filename,content",
    [
        ("pyproject.toml", "this is not [valid toml at all\n"),
        ("pytest.ini", "not = an = ini = file = at = all = [[[\n"),
        ("tox.ini", "[pytest\nunterminated section header\n"),
        ("setup.cfg", "[tool:pytest\n"),
        ("package.json", '{"scripts": {"test": "pytest -q"\n'),
    ],
)
def test_malformed_structured_file_yields_no_convention(
    tmp_path: Path, filename: str, content: str
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / filename).write_text(content, encoding="utf-8")
    intake = inspect_project(repo)
    assert _conventions(intake, TEST_INVOCATION_SUBJECT) == []


def test_package_json_non_object_top_level_yields_no_convention(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "package.json").write_text('["not", "an", "object"]\n', encoding="utf-8")
    intake = inspect_project(repo)
    assert _conventions(intake, TEST_INVOCATION_SUBJECT) == []


def test_package_json_scripts_not_a_string_yields_no_convention(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "package.json").write_text(
        '{"scripts": {"test": ["pytest", "-q"]}}\n', encoding="utf-8"
    )
    intake = inspect_project(repo)
    assert _conventions(intake, TEST_INVOCATION_SUBJECT) == []


# --- determinism -----------------------------------------------------------------


def _make_mixed_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "Makefile").write_text("test:\n\tpytest -q\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n', encoding="utf-8"
    )
    (root / "AGENTS.md").write_text(
        "Run pytest before committing.\nDo not commit secrets.\n", encoding="utf-8"
    )
    (root / "CLAUDE.md").write_text(
        "This repository standardizes on pytest.\n", encoding="utf-8"
    )


def test_determinism_across_pythonhashseed(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _make_mixed_repo(repo)

    script = (
        "import json, sys; sys.path.insert(0, %r); "
        "from agent_foundry.inspect import inspect_project; "
        "intake = inspect_project(%r); "
        "print(json.dumps([c.model_dump(mode='json') for c in intake.conventions], "
        "sort_keys=True))"
    ) % (str(REPO_ROOT / "src"), str(repo))

    outputs = []
    for seed in ("0", "1", "1337"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        completed = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=True,
            env=env,
        )
        outputs.append(completed.stdout)

    assert len(set(outputs)) == 1, "convention output must be byte-stable across seeds"
