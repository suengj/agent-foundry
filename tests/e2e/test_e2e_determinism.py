"""The slice must give the same answer twice, and from anywhere.

Two independent sources of accidental variation are checked, both in child processes
because neither can be changed inside a running interpreter:

* **`PYTHONHASHSEED`** — set randomly per process by default. Any ordering that
  reaches an artifact through `set` or `dict` iteration changes with it.
* **the working directory** — every path in an artifact must be repository-relative,
  so where the command was invoked from must not appear in the output.

Each child re-runs the whole path and prints one digest over every serialized
artifact, so a difference anywhere in the pipeline shows up as a different digest.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests.e2e import support

_DIGEST_SCRIPT = """
import hashlib, sys
from agent_foundry.models.io import dump_json
from tests.e2e import support
from tests.e2e.pipeline import run_pipeline

result = run_pipeline(
    sys.argv[1],
    integrations=[support.tracker_integration()],
    desired_integration_ids=[support.TRACKER_INTEGRATION_ID],
    observed_health=[support.tracker_health()],
    work_item_id=sys.argv[2] or None,
)
digest = hashlib.sha256()
for model in (
    result.intake,
    result.manifest,
    result.change_set,
    result.work_plan,
    result.project_lock,
    result.task_toolkit,
    result.bundle,
    result.evidence_bundle,
    result.receipt,
    result.reconciliation,
):
    digest.update(dump_json(model))
digest.update(result.markdown.encode("utf-8"))
print(digest.hexdigest())
"""


def _digest(
    *,
    project: Path,
    cwd: Path,
    hash_seed: str,
    work_item_id: str = "wi-dcc714550913",
) -> str:
    env = {**support.subprocess_env(), "PYTHONHASHSEED": hash_seed}
    env["PYTHONPATH"] = str(support.REPO_ROOT / "src") + ":" + str(support.REPO_ROOT)
    completed = subprocess.run(
        [sys.executable, "-B", "-c", _DIGEST_SCRIPT, str(project), work_item_id],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    resolved = subprocess.run(
        [sys.executable, "-c", "import agent_foundry; print(agent_foundry.__file__)"],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert Path(resolved).resolve().is_relative_to(support.REPO_ROOT.resolve()), (
        f"child imported agent_foundry from {resolved}, not this checkout"
    )
    return completed.stdout.strip()


@pytest.mark.parametrize("hash_seed", ["0", "1", "12345", "random"])
def test_the_slice_is_stable_across_hash_seeds(hash_seed: str) -> None:
    baseline = _digest(project=support.SYNTHETIC, cwd=support.REPO_ROOT, hash_seed="0")
    assert (
        _digest(project=support.SYNTHETIC, cwd=support.REPO_ROOT, hash_seed=hash_seed)
        == baseline
    )


def test_the_slice_is_stable_across_working_directories(tmp_path: Path) -> None:
    baseline = _digest(project=support.SYNTHETIC, cwd=support.REPO_ROOT, hash_seed="0")
    for cwd in (tmp_path, support.SYNTHETIC, Path(support.REPO_ROOT / "src")):
        assert (
            _digest(project=support.SYNTHETIC, cwd=cwd, hash_seed="7") == baseline
        ), f"running from {cwd} changed the result"


def test_an_absolute_project_path_never_reaches_an_artifact(tmp_path: Path) -> None:
    """A relative and an absolute invocation of the same project agree exactly."""
    import shutil

    copied = tmp_path / "copy-with-a-distinctive-name"
    shutil.copytree(support.SYNTHETIC, copied)

    absolute = _digest(project=copied.resolve(), cwd=support.REPO_ROOT, hash_seed="0")
    from_inside = _digest(project=Path("."), cwd=copied, hash_seed="0")
    assert absolute == from_inside


def test_repeating_the_run_in_one_process_is_stable() -> None:
    from agent_foundry.models.io import dump_json
    from tests.e2e.pipeline import run_pipeline

    def once() -> bytes:
        result = run_pipeline(
            support.SYNTHETIC,
            work_item_id="wi-dcc714550913",
        )
        return dump_json(result.bundle) + result.markdown.encode("utf-8")

    assert once() == once()
