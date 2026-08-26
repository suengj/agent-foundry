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
    # The builtin builder write scope is `src/`, `tests/`; the work item scopes
    # `Makefile`; so the CLI run, using the builtin registry, grants nothing.
    assert "## Write scope" not in rendered.stdout
    assert "## Write scope" in committed


# --- agent-foundry validate ------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("execution-bundle.yaml", "execution-bundle"),
        ("evidence-bundle.yaml", "evidence-bundle"),
        ("execution-receipt.yaml", "execution-receipt"),
        ("task-toolkit.yaml", "task-toolkit"),
    ],
)
def test_validate_accepts_every_committed_example(name: str, kind: str) -> None:
    args = ["validate", str(EXAMPLES_DIR / name), "--kind", kind]
    if kind in {"execution-bundle", "task-toolkit"}:
        args += ["--toolkit-lock", str(EXAMPLES_DIR / "toolkit-lock.yaml")]
    completed = _run(*args)
    assert completed.returncode == VALIDATE_OK, completed.stdout + completed.stderr
    reports = json.loads(completed.stdout)
    assert reports
    for report in reports:
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


def test_validate_reports_only_the_validators_it_actually_ran(tmp_path: Path) -> None:
    """A skipped validator shows as a smaller report, never as a pass it did not earn."""
    with_lock = _run(
        "validate",
        str(EXAMPLES_DIR / "execution-bundle.yaml"),
        "--kind",
        "execution-bundle",
        "--toolkit-lock",
        str(EXAMPLES_DIR / "toolkit-lock.yaml"),
    )
    without_lock = _run(
        "validate", str(EXAMPLES_DIR / "execution-bundle.yaml"), "--kind", "execution-bundle"
    )
    assert with_lock.returncode == VALIDATE_OK
    assert without_lock.returncode == VALIDATE_OK

    ran_with = {report["findings"][0]["validator_id"] for report in json.loads(with_lock.stdout)}
    ran_without = {
        report["findings"][0]["validator_id"] for report in json.loads(without_lock.stdout)
    }
    assert "toolkit-coherence" in ran_with
    assert "toolkit-coherence" not in ran_without
    assert ran_without < ran_with


def test_doctor_passes_for_this_repository() -> None:
    completed = _run("doctor")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "[FAIL]" not in completed.stdout
