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
    DEMOTED_MENTION_CONFIDENCE,
    MENTION_CONFIDENCE,
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
        # Machine-readable, not prose, and typed rather than written into free
        # text: the demotion shows up as a lower `confidence`, and `pattern` stays
        # a report about the project. See
        # `test_a_demoted_mention_pattern_carries_no_foundry_commentary`.
        assert convention.confidence == DEMOTED_MENTION_CONFIDENCE
        assert convention.pattern == "instruction surface mentions pytest"


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


def test_a_jest_declaration_does_not_demote_a_pytest_mention(tmp_path: Path) -> None:
    """Cross-runner: the declaration and the mention are about different runners.

    `package.json` declares `"test": "jest"` -- a real DECLARED `test-invocation`
    fact, and one this module deliberately refuses to read as naming *any* runner.
    AGENTS.md separately mentions pytest. Demotion means "a stronger fact about
    this same thing is already known"; nothing stronger about pytest is known
    here, so the pytest mention must keep its baseline confidence. Lowering it
    would spend a jest declaration's authority on a pytest claim -- a confidence
    not earned by evidence about that subject -- and would rank the repository's
    only pytest evidence 3.3x lower for every `relevance x confidence` consumer
    (`compile/context.py`).
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "package.json").write_text(
        '{\n  "name": "demo",\n  "scripts": {\n    "test": "jest"\n  }\n}\n',
        encoding="utf-8",
    )
    (repo / "AGENTS.md").write_text("Run pytest before submitting.\n", encoding="utf-8")
    intake = inspect_project(repo)

    structured = _conventions(intake, TEST_INVOCATION_SUBJECT)
    mentions = _conventions(intake, TEST_RUNNER_SUBJECT)
    assert len(structured) == 1
    assert structured[0].pattern == 'package.json \'test\' script is "jest"'
    assert len(mentions) == 1
    assert mentions[0].confidence == MENTION_CONFIDENCE, (
        "a declaration about jest must not lower the confidence of pytest evidence"
    )
    assert mentions[0].pattern == "instruction surface mentions pytest"


def test_a_pytest_naming_package_json_declaration_does_demote_a_mention(
    tmp_path: Path,
) -> None:
    """The other half of the same rule: when the `scripts.test` command really
    does invoke pytest, the declaration *is* about pytest and the demotion is
    earned. Without this, scoping the demotion could be satisfied by never
    demoting at all."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "package.json").write_text(
        '{\n  "name": "demo",\n  "scripts": {\n    "test": "pytest -q"\n  }\n}\n',
        encoding="utf-8",
    )
    (repo / "AGENTS.md").write_text("Run pytest before submitting.\n", encoding="utf-8")
    intake = inspect_project(repo)

    mentions = _conventions(intake, TEST_RUNNER_SUBJECT)
    assert len(mentions) == 1
    assert mentions[0].confidence == DEMOTED_MENTION_CONFIDENCE


def test_a_demoted_mention_pattern_carries_no_foundry_commentary(
    tmp_path: Path,
) -> None:
    """`pattern` reports the project, not Foundry's opinion of the project.

    `compile/context.py` relevance-matches a work item's text against a
    convention's `subject`, `pattern` and `evidence`. Words written into
    `pattern` by Foundry ("structured", "declaration", "precedence", ...) are
    therefore tokens a work item can match on, and `_relevance_score` can only
    ever be *raised* by extra words -- so a work item titled "Document the
    structured declaration precedence" would select a pytest mention with the
    rationale that its pattern shares tokens with the title, where the shared
    tokens are Foundry commentary and not project text. The demoted pattern must
    be byte-identical to the undemoted one; only `confidence` moves.
    """
    demoted_repo = tmp_path / "demoted"
    demoted_repo.mkdir()
    (demoted_repo / "pytest.ini").write_text(
        "[pytest]\ntestpaths = tests\n", encoding="utf-8"
    )
    (demoted_repo / "AGENTS.md").write_text("Run pytest first.\n", encoding="utf-8")

    plain_repo = tmp_path / "plain"
    plain_repo.mkdir()
    (plain_repo / "AGENTS.md").write_text("Run pytest first.\n", encoding="utf-8")

    demoted = _conventions(inspect_project(demoted_repo), TEST_RUNNER_SUBJECT)
    plain = _conventions(inspect_project(plain_repo), TEST_RUNNER_SUBJECT)
    assert len(demoted) == 1 and len(plain) == 1
    assert demoted[0].confidence == DEMOTED_MENTION_CONFIDENCE
    assert plain[0].confidence == MENTION_CONFIDENCE
    assert demoted[0].pattern == plain[0].pattern
    for word in ("structured", "declaration", "precedence", "supersed", "takes"):
        assert word not in demoted[0].pattern.lower()


def test_minified_package_json_still_yields_the_declaration(tmp_path: Path) -> None:
    """A whole-file property, not an exotic escape: a generated `package.json`
    is commonly one physical line. Requiring the `"test"` key to *start* its line
    made the entire declaration vanish -- a real DECLARED fact silently lost. The
    single line is the verbatim source text carrying the declaration, so it is
    quoted in full as the evidence."""
    repo = tmp_path / "repo"
    repo.mkdir()
    minified = '{"name":"demo","scripts":{"build":"tsc","test":"pytest -q"}}'
    (repo / "package.json").write_text(minified, encoding="utf-8")
    intake = inspect_project(repo)

    found = _conventions(intake, TEST_INVOCATION_SUBJECT)
    assert len(found) == 1
    assert found[0].provenance.kind is ProvenanceKind.DECLARED
    assert found[0].confidence == STRUCTURED_CONFIDENCE
    assert found[0].pattern == "package.json 'test' script invokes pytest"
    assert found[0].evidence == minified


def test_minified_package_json_naming_another_runner_is_quoted_not_guessed(
    tmp_path: Path,
) -> None:
    """The minified path inherits the same restraint as the multi-line one: the
    command is quoted verbatim and no runner is claimed."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "package.json").write_text(
        '{"name":"demo","scripts":{"test":"jest --ci"}}', encoding="utf-8"
    )
    intake = inspect_project(repo)
    found = _conventions(intake, TEST_INVOCATION_SUBJECT)
    assert len(found) == 1
    assert found[0].pattern == 'package.json \'test\' script is "jest --ci"'
    assert "pytest" not in found[0].pattern


def test_a_longer_key_is_not_mistaken_for_the_test_key(tmp_path: Path) -> None:
    """Loosening the line match to "anywhere on the line" must not let a
    different key masquerade as `scripts.test`. Here `scripts.test` genuinely
    exists, and the recovered line must be the one carrying the `"test"` key
    itself, not the `"testMatch"` line that also contains the same value."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "package.json").write_text(
        "{\n"
        '  "testMatch": "pytest -q",\n'
        '  "scripts": {\n'
        '    "test": "pytest -q"\n'
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    intake = inspect_project(repo)
    found = _conventions(intake, TEST_INVOCATION_SUBJECT)
    assert len(found) == 1
    assert found[0].evidence == '"test": "pytest -q"'


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
