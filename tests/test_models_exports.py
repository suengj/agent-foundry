"""Public models export surface stability."""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import agent_foundry.models as models

REPO_ROOT = Path(__file__).resolve().parents[1]
INTENTIONAL_ADDITIONS = {
    "BundleProvenanceRecord",
    "CompiledAuthority",
    "SkillSummary",
}


def _main_branch_all_names() -> set[str]:
    completed = subprocess.run(
        ["git", "show", "origin/main:src/agent_foundry/models/__init__.py"],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    )
    text = completed.stdout
    all_block = text.split("__all__ = ", 1)[1]
    all_block = all_block.split("\n]", 1)[0] + "]"
    return set(ast.literal_eval(all_block))


def test_models_all_exports_resolve_and_is_stable_superset():
    """Every __all__ name resolves; main-branch exports are never dropped unintentionally."""
    for name in models.__all__:
        assert hasattr(models, name), f"missing export: {name}"
        assert getattr(models, name) is not None

    main_names = _main_branch_all_names()
    current_names = set(models.__all__)

    dropped = sorted(main_names - current_names)
    added = sorted(current_names - main_names)

    assert dropped == [], f"unexpected dropped exports: {dropped}"
    assert set(added) == INTENTIONAL_ADDITIONS, f"unexpected additions: {added}"
