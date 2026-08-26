"""The slice is reachable from the CLI, and the CLI adds no logic of its own.

The MCP-facade question in `docs/foundry/08` §3.7 is decided by this property: if the
CLI is a thin dispatch over the same Core functions a Python caller uses, a third
surface needs no separate path. Confirmed here by inspection *and* by execution --
the facade module is required to contain no rule, and the commands are required to
produce the same artifacts the Python API does.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from agent_foundry.models.io import dump_yaml
from agent_foundry.verify import VALIDATOR_IDS

from tests.e2e import support
from tests.e2e.generate_examples import EXAMPLES_DIR

# `agent-foundry validate` distinguishes rejection from a malformed request.
VALIDATE_OK = 0
VALIDATE_REJECTED = 1
VALIDATE_INPUT_ERROR = 2
VALIDATE_INCOMPLETE = 3


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-B", "-m", "agent_foundry", *args],
        cwd=support.REPO_ROOT,
        env=support.subprocess_env(),
        capture_output=True,
        text=True,
        check=False,
    )


# --- no duplicated business logic behind the CLI --------------------------------


def test_the_validate_facade_defines_no_rule_of_its_own() -> None:
    """Structural, not stylistic: the dispatch module must not decide anything.

    Every validator the subcommand can run is imported from `verify.validators`. If a
    check were written here instead, the CLI and the Python API would be able to
    disagree about whether an artifact is valid, and a future MCP facade would need a
    third copy.
    """
    source = (
        support.REPO_ROOT / "src" / "agent_foundry" / "verify" / "cli_api.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert not {name for name in defined if name.startswith("validate_") and name != "validate_artifact"}, (
        "a validator defined in the CLI facade is a second implementation"
    )
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "agent_foundry.verify.validators"
        for alias in node.names
    }
    assert imported, "the facade must reach the published validators by import"
    assert all(name in set(VALIDATOR_IDS) or name.startswith("validate_") for name in imported)


def test_the_cli_reaches_the_same_functions_the_python_api_does() -> None:
    from agent_foundry import cli

    source = (support.REPO_ROOT / "src" / "agent_foundry" / "cli.py").read_text("utf-8")
    tree = ast.parse(source)
    module_names = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    # Every stage is imported from a published package entry point, never from a
    # private implementation module.
    for package in ("inspect", "adopt", "toolkit", "compile", "render", "verify"):
        assert any(
            name == f"agent_foundry.{package}" or name.startswith(f"agent_foundry.{package}.")
            for name in module_names
        ), f"cli does not reach agent_foundry.{package}"
    assert callable(cli.main)


# --- the commands run and agree with the Python API -----------------------------


def test_inspect_and_adopt_run_over_the_synthetic_fixture() -> None:
    inspected = _run("inspect", str(support.SYNTHETIC), "--format", "json")
    assert inspected.returncode == 0, inspected.stderr
    payload = json.loads(inspected.stdout)
    assert payload["project_root"] == "."
    assert payload["observations"]

    adopted = _run("adopt", str(support.SYNTHETIC), "--format", "json")
    assert adopted.returncode == 0, adopted.stderr
    plan = json.loads(adopted.stdout)
    assert plan["manifest"]["project"]["name"] == "orders-service"
    assert plan["change_set"]["changes"]


def test_compile_render_matches_the_committed_example(tmp_path: Path) -> None:
    """The CLI's rendered contract is the same bytes the Python API produces.

    The run id and role are the example's, and the registry override the example uses
    is not expressible on the command line — so this compares the sections that do not
    depend on it, and pins the difference rather than glossing over it.
    """
    from tests.e2e.generate_examples import build_result

    result = build_result()
    work_item_path = tmp_path / "work-item.yaml"
    work_item_path.write_bytes(dump_yaml(result.work_item))
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_bytes(dump_yaml(result.manifest))

    rendered = _run(
        "compile",
        "--manifest",
        str(manifest_path),
        "--work-item",
        str(work_item_path),
        "--role-id",
        "builder",
        "--run-id",
        "RUN-EXAMPLE-001",
        "--render",
    )
    assert rendered.returncode == 0, rendered.stderr
    committed = (EXAMPLES_DIR / "execution-contract.md").read_text(encoding="utf-8")
    for line in ("# Execution Contract", "## Objective", "## Acceptance criteria"):
        assert line in rendered.stdout
        assert line in committed
    assert result.work_item.objective in rendered.stdout
    # Same registry, same declared envelope, so the CLI grants exactly what the Python
    # API did. Before AF8's review round the builtin builder role hardcoded
    # `["src/", "tests/"]` and this same command produced a bundle with no write scope
    # at all, which only a later `validate` call would have caught.
    assert "## Write scope" in rendered.stdout
    for path in result.bundle.write_scope:
        assert path in rendered.stdout


# --- agent-foundry validate ------------------------------------------------------


def _validate_args(name: str, kind: str) -> list[str]:
    args = ["validate", str(EXAMPLES_DIR / name), "--kind", kind]
    if kind in {"execution-bundle", "task-toolkit"}:
        args += ["--toolkit-lock", str(EXAMPLES_DIR / "toolkit-lock.yaml")]
    if kind == "execution-bundle":
        args += [
            "--work-item",
            str(EXAMPLES_DIR / "work-item.yaml"),
            "--manifest",
            str(EXAMPLES_DIR / "project-manifest.yaml"),
        ]
    return args


# Committed example -> the `--kind` it validates as. Only artifacts `validate` has a
# kind for appear; the mapping is checked for completeness below rather than trusted.
VALIDATABLE_EXAMPLES: dict[str, str] = {
    "work-item.yaml": "work-item",
    "task-toolkit.yaml": "task-toolkit",
    "execution-bundle.yaml": "execution-bundle",
    "evidence-bundle.yaml": "evidence-bundle",
    "execution-receipt.yaml": "execution-receipt",
}


def test_every_artifact_kind_validate_supports_has_a_committed_example() -> None:
    """The parametrized test below says "every"; this is what makes that true.

    Without it, a kind added to `validate` would simply not be exercised, and the
    coverage claim in the name of the test below would quietly narrow.
    """
    from agent_foundry.verify.cli_api import ARTIFACT_KINDS

    assert set(VALIDATABLE_EXAMPLES.values()) == set(ARTIFACT_KINDS)
    for name in VALIDATABLE_EXAMPLES:
        assert (EXAMPLES_DIR / name).is_file(), f"{name} is not committed"


@pytest.mark.parametrize(
    ("name", "kind"),
    sorted(VALIDATABLE_EXAMPLES.items()),
)
def test_validate_accepts_every_committed_example(name: str, kind: str) -> None:
    completed = _run(*_validate_args(name, kind))
    assert completed.returncode == VALIDATE_OK, completed.stdout + completed.stderr
    validation = json.loads(completed.stdout)
    assert validation["not_run"] == []
    assert validation["reports"]
    for report in validation["reports"]:
        assert report["findings"]
        assert all(
            finding["outcome"] in {"PASS", "NOT_REQUIRED"} for finding in report["findings"]
        )


def test_validate_rejects_a_broken_artifact_with_its_own_exit_code(tmp_path: Path) -> None:
    import yaml

    payload = yaml.safe_load((EXAMPLES_DIR / "execution-bundle.yaml").read_text())
    payload["write_scope"] = []
    payload["authority"]["write_scope"] = []
    broken = tmp_path / "broken-bundle.yaml"
    broken.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")

    completed = _run("validate", str(broken), "--kind", "execution-bundle")
    assert completed.returncode == VALIDATE_REJECTED
    assert "grants no write path" in completed.stdout


def test_validate_separates_a_bad_request_from_a_rejection(tmp_path: Path) -> None:
    unreadable = tmp_path / "not-a-bundle.yaml"
    unreadable.write_text("just: a mapping\n", encoding="utf-8")
    completed = _run("validate", str(unreadable), "--kind", "execution-bundle")
    assert completed.returncode == VALIDATE_INPUT_ERROR
    assert completed.stdout == ""

    missing = _run("validate", str(tmp_path / "absent.yaml"), "--kind", "execution-bundle")
    assert missing.returncode == VALIDATE_INPUT_ERROR


def test_validate_names_what_it_could_not_run_and_says_so_in_its_exit_code() -> None:
    """A missing input is a recorded state, not a smaller pass.

    Without `--toolkit-lock` and `--work-item` two validators that apply to an
    execution bundle have nothing to run against. The reports that did run all pass, so
    the naive answer is exit 0 — and that reads as a safety verdict the command did not
    give. Exit 3 says so, and `not_run` names which checks are missing and why.
    """
    complete = _run(*_validate_args("execution-bundle.yaml", "execution-bundle"))
    partial = _run(
        "validate", str(EXAMPLES_DIR / "execution-bundle.yaml"), "--kind", "execution-bundle"
    )

    assert complete.returncode == VALIDATE_OK
    assert partial.returncode == VALIDATE_INCOMPLETE

    complete_payload = json.loads(complete.stdout)
    partial_payload = json.loads(partial.stdout)
    assert complete_payload["not_run"] == []

    not_run = {item["validator_id"] for item in partial_payload["not_run"]}
    assert not_run == {"toolkit-coherence", "write-scope-containment"}
    for item in partial_payload["not_run"]:
        assert item["reason"], "a skipped validator must say what it lacked"
    # Everything that did run still passed: the exit code is about coverage, not fault.
    assert all(
        finding["outcome"] in {"PASS", "NOT_REQUIRED"}
        for report in partial_payload["reports"]
        for finding in report["findings"]
    )
    assert "[not run]" in partial.stderr


def test_the_cli_cannot_give_the_whole_slice_verdict_by_itself() -> None:
    """A documented boundary, pinned so it cannot be overstated.

    `agent-foundry validate` checks one artifact. Six of the fourteen published
    validators need inputs no single artifact carries — a review decision, observed
    integration health, the permission profile, the work plan — so the complete verdict
    is `agent_foundry.verify.validate_compiled_slice`, and the command's own
    `--help` says so.
    """
    from agent_foundry.verify.cli_api import ARTIFACT_KINDS, _APPLICABLE_BY_KIND

    reachable = {"contract-schema-compatibility"}
    for kind in ARTIFACT_KINDS:
        reachable |= set(_APPLICABLE_BY_KIND.get(kind, ()))
    assert reachable < set(VALIDATOR_IDS)

    helped = _run("validate", "--help")
    assert "validate_compiled_slice" in helped.stdout


def test_doctor_passes_for_this_repository() -> None:
    completed = _run("doctor")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "[FAIL]" not in completed.stdout
