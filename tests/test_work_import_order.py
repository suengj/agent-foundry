"""Regression tests for package import order independence."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

_IMPORT_ORDER_CASES = [
    "from agent_foundry.work import decompose_work",
    "import agent_foundry.work",
    "import agent_foundry.models",
]


def _subprocess_env() -> dict[str, str]:
    return {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}


def _import_script(statement: str) -> str:
    return f"""
import agent_foundry
from pathlib import Path

repo_root = Path({str(REPO_ROOT)!r})
module_path = Path(agent_foundry.__file__).resolve()
assert str(repo_root) in str(module_path), module_path
{statement}
"""


@pytest.mark.parametrize("statement", _IMPORT_ORDER_CASES)
def test_package_import_order_in_subprocess(statement: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", _import_script(statement)],
        cwd=REPO_ROOT,
        env=_subprocess_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_work_decomposition_errors_importable_from_models() -> None:
    from agent_foundry.models import DependencyGraphError, WorkDecompositionError

    assert issubclass(DependencyGraphError, WorkDecompositionError)
