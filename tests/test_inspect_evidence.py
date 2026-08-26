"""AF2 evidence-integrity tests — evidence must support the claim it is attached to.

Evidence that does not support its own claim is worse than absent evidence, because
everything downstream trusts it. These tests pin three properties: a quoted line is
the line that actually matched, a path the walk could not read is named rather than
silently folded into a skip count, and inferred confidence tracks signal strength.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from agent_foundry.inspect import inspect_project
from agent_foundry.inspect.conventions import strip_trailing_comment
from agent_foundry.models.common import IntakeMode, ProvenanceKind

REPO_ROOT = Path(__file__).resolve().parents[1]
BROWNFIELD = REPO_ROOT / "tests" / "fixtures" / "projects" / "brownfield-sample"


def _conventions(intake, subject: str) -> list:
    return [c for c in intake.conventions if c.subject == subject]


def _intake_mode(intake, kind: ProvenanceKind):
    return [
        f
        for f in intake.classification_findings
        if f.dimension == "intake_mode" and f.provenance.kind == kind
    ]


def _unobservable(intake) -> list:
    return [o for o in intake.observations if o.subject == "path-unobservable"]


# --- Item 1: the quoted evidence is the line that matched ---


def test_git_policy_evidence_is_the_line_that_matched(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text(
        "Always commit early and often.\nDo not commit secrets to the repo.\n",
        encoding="utf-8",
    )
    intake = inspect_project(repo)
    evidence = [c.evidence for c in _conventions(intake, "git-policy")]
    assert evidence == ["Do not commit secrets to the repo."]


def test_git_policy_records_every_constraining_line(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text(
        "Do not commit secrets.\nCommit messages are not optional.\nCommit often.\n",
        encoding="utf-8",
    )
    intake = inspect_project(repo)
    evidence = sorted(c.evidence for c in _conventions(intake, "git-policy"))
    assert evidence == ["Commit messages are not optional.", "Do not commit secrets."]


def test_test_invocation_requires_pytest_inside_the_test_recipe(tmp_path: Path) -> None:
    """An adjacency claim must be backed by adjacency, not by co-occurrence."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "Makefile").write_text(
        "# pytest is intentionally not used here\ntest:\n\tunittest discover\n",
        encoding="utf-8",
    )
    intake = inspect_project(repo)
    assert _conventions(intake, "test-invocation") == []


def test_test_invocation_evidence_quotes_the_recipe_line(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "Makefile").write_text(
        "lint:\n\truff check .\ntest:\n\tpytest -q --maxfail=1\n",
        encoding="utf-8",
    )
    intake = inspect_project(repo)
    invocation = _conventions(intake, "test-invocation")
    assert [c.evidence for c in invocation] == ["pytest -q --maxfail=1"]
    assert "near" not in invocation[0].pattern


def test_test_invocation_ignores_pytest_in_another_target(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "Makefile").write_text(
        "test:\n\tunittest discover\nbench:\n\tpytest-benchmark run\n",
        encoding="utf-8",
    )
    intake = inspect_project(repo)
    assert _conventions(intake, "test-invocation") == []


def test_ci_checkout_evidence_quotes_the_matched_workflow_line(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    workflows = repo / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        "jobs:\n  build:\n    steps:\n      - uses: actions/checkout@v4\n",
        encoding="utf-8",
    )
    intake = inspect_project(repo)
    checkout = _conventions(intake, "ci-checkout")
    assert [c.evidence for c in checkout] == ["- uses: actions/checkout@v4"]


def test_every_convention_evidence_is_a_line_of_its_source_file() -> None:
    """The general property the individual cases are instances of."""
    intake = inspect_project(BROWNFIELD)
    assert intake.conventions
    for convention in intake.conventions:
        source = BROWNFIELD / convention.source_ref
        lines = {line.strip() for line in source.read_text(encoding="utf-8").splitlines()}
        assert convention.evidence in lines, (
            f"{convention.subject} evidence {convention.evidence!r} is not a line of "
            f"{convention.source_ref}"
        )


# --- Item 1 (cont.): inert text cannot support a claim about effective behaviour ---


def _makefile_repo(tmp_path: Path, name: str, body: str) -> Path:
    repo = tmp_path / name
    repo.mkdir()
    (repo / "Makefile").write_text(body, encoding="utf-8")
    return repo


def _workflow_repo(tmp_path: Path, name: str, body: str) -> Path:
    repo = tmp_path / name
    workflows = repo / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(body, encoding="utf-8")
    return repo


def test_commented_out_pytest_recipe_line_invokes_nothing(tmp_path: Path) -> None:
    """A shell comment executes nothing, so it cannot support an invocation claim."""
    commented = _makefile_repo(
        tmp_path, "commented", "test:\n\t# pytest -q --this-is-a-shell-comment\n\ttrue\n"
    )
    live = _makefile_repo(
        tmp_path, "live", "test:\n\tpytest -q --this-is-a-shell-comment\n\ttrue\n"
    )
    assert _conventions(inspect_project(commented), "test-invocation") == []
    assert [c.evidence for c in _conventions(inspect_project(live), "test-invocation")] == [
        "pytest -q --this-is-a-shell-comment"
    ]


def test_make_silent_prefix_does_not_hide_a_comment(tmp_path: Path) -> None:
    """make strips '@' before the shell sees the line, so '@# pytest' is still a comment."""
    silent = _makefile_repo(tmp_path, "silent", "test:\n\t@# pytest -q\n")
    real = _makefile_repo(tmp_path, "real", "test:\n\t@pytest -q\n")
    assert _conventions(inspect_project(silent), "test-invocation") == []
    assert [c.evidence for c in _conventions(inspect_project(real), "test-invocation")] == [
        "@pytest -q"
    ]


def test_trailing_comment_does_not_suppress_a_real_invocation(tmp_path: Path) -> None:
    repo = _makefile_repo(tmp_path, "trailing", "test:\n\tpytest -q  # fast path\n")
    assert [c.evidence for c in _conventions(inspect_project(repo), "test-invocation")] == [
        "pytest -q  # fast path"
    ]


def test_hash_inside_a_quoted_argument_is_not_a_comment(tmp_path: Path) -> None:
    """Over-correcting the other way would drop a legitimate invocation."""
    repo = _makefile_repo(tmp_path, "quoted", 'test:\n\techo "step # 1" && pytest -q\n')
    assert [c.evidence for c in _conventions(inspect_project(repo), "test-invocation")] == [
        'echo "step # 1" && pytest -q'
    ]


def test_commented_out_checkout_step_configures_nothing(tmp_path: Path) -> None:
    commented = _workflow_repo(
        tmp_path,
        "commented",
        "jobs:\n  build:\n    steps:\n      # - uses: actions/checkout@v4\n"
        "      - run: echo no checkout\n",
    )
    live = _workflow_repo(
        tmp_path,
        "live",
        "jobs:\n  build:\n    steps:\n      - uses: actions/checkout@v4\n"
        "      - run: echo checked out\n",
    )
    assert _conventions(inspect_project(commented), "ci-checkout") == []
    assert [c.evidence for c in _conventions(inspect_project(live), "ci-checkout")] == [
        "- uses: actions/checkout@v4"
    ]


def test_checkout_named_outside_a_step_configures_nothing(tmp_path: Path) -> None:
    """Naming the action in a script or a header is not configuring a checkout."""
    repo = _workflow_repo(
        tmp_path,
        "prose",
        "# this workflow deliberately avoids actions/checkout\n"
        "jobs:\n  build:\n    steps:\n      - run: echo actions/checkout\n",
    )
    assert _conventions(inspect_project(repo), "ci-checkout") == []


def test_checkout_evidence_skips_a_commented_line_with_the_same_value(tmp_path: Path) -> None:
    """The quoted line must be the live step, not an identical commented-out one."""
    repo = _workflow_repo(
        tmp_path,
        "both",
        "jobs:\n  build:\n    steps:\n      # - uses: actions/checkout@v4\n"
        "      - uses: actions/checkout@v4\n",
    )
    checkout = _conventions(inspect_project(repo), "ci-checkout")
    assert [c.evidence for c in checkout] == ["- uses: actions/checkout@v4"]
    assert not checkout[0].evidence.startswith("#")


def test_pinned_checkout_with_a_trailing_comment_still_counts(tmp_path: Path) -> None:
    repo = _workflow_repo(
        tmp_path,
        "pinned",
        "jobs:\n  build:\n    steps:\n      - uses: actions/checkout@v4  # pinned\n",
    )
    assert [c.evidence for c in _conventions(inspect_project(repo), "ci-checkout")] == [
        "- uses: actions/checkout@v4  # pinned"
    ]


def test_unparseable_workflow_establishes_no_checkout(tmp_path: Path) -> None:
    repo = _workflow_repo(tmp_path, "broken", "jobs: [\n  - uses: actions/checkout@v4\n")
    assert _conventions(inspect_project(repo), "ci-checkout") == []


def test_execution_claims_never_rest_on_comment_text(tmp_path: Path) -> None:
    """The general property: an effective-behaviour claim needs effective text."""
    repo = tmp_path / "mixed"
    workflows = repo / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (repo / "Makefile").write_text(
        "test:\n\t# pytest -q\n\tpytest -q  # real\n", encoding="utf-8"
    )
    (workflows / "ci.yml").write_text(
        "jobs:\n  build:\n    steps:\n      # - uses: actions/checkout@v3\n"
        "      - uses: actions/checkout@v4\n",
        encoding="utf-8",
    )
    intake = inspect_project(repo)
    claims = _conventions(intake, "test-invocation") + _conventions(intake, "ci-checkout")
    assert len(claims) == 2
    for convention in claims:
        effective = strip_trailing_comment(convention.evidence)
        assert effective.strip(), f"{convention.subject} evidence is entirely a comment"
        token = "pytest" if convention.subject == "test-invocation" else "actions/checkout"
        assert token in effective


def test_mention_claims_deliberately_still_record_commented_text(tmp_path: Path) -> None:
    """Audit of the other two emitters: they claim a mention, not effective behaviour.

    An agent reading AGENTS.md sees the text inside an HTML comment, so a mention
    there is a real mention needing reconciliation. Suppressing it would lose
    evidence; asserting it as configuration would be the failure fixed above.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text(
        "<!-- Run tests with pytest. Do not commit secrets. -->\n", encoding="utf-8"
    )
    intake = inspect_project(repo)
    assert [c.pattern for c in _conventions(intake, "test-runner")] == [
        "instruction surface mentions pytest"
    ]
    assert [c.pattern for c in _conventions(intake, "git-policy")] == [
        "instruction surface line mentions a commit constraint"
    ]


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("pytest -q", "pytest -q"),
        ("# pytest -q", ""),
        ("pytest -q # fast", "pytest -q "),
        ("echo 'a # b'", "echo 'a # b'"),
        ('echo "a # b" && pytest', 'echo "a # b" && pytest'),
        ("echo a#b", "echo a#b"),
        ("- uses: actions/checkout@v4  # pinned", "- uses: actions/checkout@v4  "),
        ("      # - uses: actions/checkout@v4", "      "),
    ],
)
def test_strip_trailing_comment_rules(line: str, expected: str) -> None:
    assert strip_trailing_comment(line) == expected


# --- Item 2: unobservability is reported, and skips are separated by cause ---


def _restore_modes(*paths: Path) -> None:
    for path in paths:
        try:
            path.chmod(stat.S_IRWXU)
        except OSError:
            pass


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root bypasses permission bits, so nothing is unreadable",
)
def test_unreadable_directory_is_reported_not_silently_skipped(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    locked = repo / "locked"
    locked.mkdir(parents=True)
    (locked / "inside.txt").write_text("hidden\n", encoding="utf-8")
    locked.chmod(0o000)
    try:
        intake = inspect_project(repo)
    finally:
        _restore_modes(locked)
    reported = _unobservable(intake)
    assert [o.provenance.source_ref for o in reported] == ["locked"]
    assert "could not be observed" in reported[0].content
    assert intake.traversal_stats.entries_skipped_unreadable == 1
    assert intake.traversal_stats.entries_unobservable == 1


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root bypasses permission bits, so nothing is unreadable",
)
def test_unreadable_file_is_reported_not_silently_empty(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    secret = repo / "AGENTS.md"
    secret.write_text("Run tests with pytest.\n", encoding="utf-8")
    secret.chmod(0o000)
    try:
        intake = inspect_project(repo)
    finally:
        _restore_modes(secret)
    reported = _unobservable(intake)
    assert [o.provenance.source_ref for o in reported] == ["AGENTS.md"]
    # The file is still a visited entry; only its contents are a hole.
    assert intake.traversal_stats.entries_visited == 1
    assert intake.traversal_stats.entries_skipped == 0
    assert intake.traversal_stats.entries_unobservable == 1
    assert _conventions(intake, "test-runner") == []


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root bypasses permission bits, so nothing is unreadable",
)
def test_skip_causes_are_separated_and_sum_to_the_total(tmp_path: Path) -> None:
    """One ignored cache dir, one escaping symlink, one unreadable dir — three causes."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "leak.txt").write_text("out of root\n", encoding="utf-8")
    repo = tmp_path / "repo"
    (repo / "node_modules").mkdir(parents=True)
    (repo / "escape").symlink_to(outside)
    locked = repo / "locked"
    locked.mkdir()
    locked.chmod(0o000)
    try:
        intake = inspect_project(repo)
    finally:
        _restore_modes(locked)

    stats = intake.traversal_stats
    assert stats.entries_skipped == 3
    assert stats.entries_skipped_ignored_dir == 1
    assert stats.entries_skipped_refused == 1
    assert stats.entries_skipped_unreadable == 1
    assert (
        stats.entries_skipped_ignored_dir
        + stats.entries_skipped_refused
        + stats.entries_skipped_unreadable
        == stats.entries_skipped
    )
    assert [o.provenance.source_ref for o in _unobservable(intake)] == ["locked"]


def test_ignored_directory_is_not_reported_as_unobservable(tmp_path: Path) -> None:
    """A deliberate skip is not a hole; only causes we could not see through are."""
    repo = tmp_path / "repo"
    (repo / "node_modules").mkdir(parents=True)
    intake = inspect_project(repo)
    assert intake.traversal_stats.entries_skipped_ignored_dir == 1
    assert intake.traversal_stats.entries_unobservable == 0
    assert _unobservable(intake) == []


def test_clean_tree_reports_no_skips_of_any_cause() -> None:
    stats = inspect_project(BROWNFIELD).traversal_stats
    assert stats.entries_skipped == 0
    assert stats.entries_skipped_ignored_dir == 0
    assert stats.entries_skipped_refused == 0
    assert stats.entries_skipped_unreadable == 0
    assert stats.entries_unobservable == 0


# --- Item 3: confidence reflects signal strength ---


def test_single_weak_signal_does_not_score_as_a_corroborated_one(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    workflows = repo / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "c.yml").write_text("on: push\n", encoding="utf-8")
    intake = inspect_project(repo)
    inferred = _intake_mode(intake, ProvenanceKind.INFERRED)
    assert [f.value for f in inferred] == [IntakeMode.BROWNFIELD.value]
    assert inferred[0].provenance.confidence == 0.5


def test_more_independent_signals_raise_intake_mode_confidence(tmp_path: Path) -> None:
    weak = tmp_path / "weak"
    (weak / ".github" / "workflows").mkdir(parents=True)
    (weak / ".github" / "workflows" / "c.yml").write_text("on: push\n", encoding="utf-8")

    strong = tmp_path / "strong"
    src = strong / "src"
    src.mkdir(parents=True)
    for index in range(9):
        (src / f"mod_{index}.py").write_text("x = 1\n", encoding="utf-8")
    (strong / ".github" / "workflows").mkdir(parents=True)
    (strong / ".github" / "workflows" / "c.yml").write_text("on: push\n", encoding="utf-8")
    (strong / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")

    weak_confidence = _intake_mode(inspect_project(weak), ProvenanceKind.INFERRED)[0]
    strong_confidence = _intake_mode(inspect_project(strong), ProvenanceKind.INFERRED)[0]
    assert strong_confidence.provenance.confidence > weak_confidence.provenance.confidence


def test_inferred_intake_mode_states_the_signals_it_rests_on(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    workflows = repo / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "c.yml").write_text("on: push\n", encoding="utf-8")
    inferred = _intake_mode(inspect_project(repo), ProvenanceKind.INFERRED)[0]
    assert inferred.reason is not None
    assert "1 of 5" in inferred.reason
    assert "CI workflow definitions" in inferred.reason


def test_inferred_greenfield_states_why_it_is_greenfield(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    inferred = _intake_mode(inspect_project(repo), ProvenanceKind.INFERRED)[0]
    assert inferred.value == IntakeMode.GREENFIELD.value
    assert inferred.reason is not None
    assert "no brownfield signals" in inferred.reason
