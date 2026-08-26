"""Shared inputs for the end-to-end tests.

Nothing here is a Foundry rule. It is the project-shaped configuration a consumer
supplies — the registry override and the declared integration — plus the tree
digest the read-only tests compare against.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from agent_foundry.models import (
    IntegrationHealth,
    IntegrationHealthState,
    IntegrationSpec,
)
from agent_foundry.models.base import FOUNDRY_SCHEMA_VERSION

from tests.e2e.pipeline import FINISHED_AT, registry_with_builder_write_scope

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "projects"
SYNTHETIC = FIXTURES / "e2e-synthetic"

# The synthetic project's own shape. The builtin `builder` role declares
# `write_scope=["src/", "tests/"]`; adoption work touches instruction surfaces and
# build files, so a project-appropriate registry is supplied the way a consumer would.
SYNTHETIC_WRITE_SCOPE = [
    ".foundry/",
    ".github/",
    "AGENTS.md",
    "CLAUDE.md",
    "Makefile",
    "docs/",
    "src/",
    "tests/",
]

# This repository's own shape, for the brownfield run against itself.
SELF_WRITE_SCOPE = [
    ".foundry/",
    ".github/",
    "AGENTS.md",
    "CHANGELOG.md",
    "README.md",
    "docs/",
    "pyproject.toml",
    "src/",
    "tests/",
]

TRACKER_INTEGRATION_ID = "work-tracker"
# The credential is a *position*, never a value: `env:ORDERS_TRACKER_TOKEN` names
# where a secret lives. `tests/test_secret_boundary.py` owns the general proof; the
# end-to-end tests check that this holds through a full compile and render.
TRACKER_CREDENTIAL_REF = "env:ORDERS_TRACKER_TOKEN"


def synthetic_registry():
    return registry_with_builder_write_scope(SYNTHETIC_WRITE_SCOPE)


def self_registry():
    return registry_with_builder_write_scope(SELF_WRITE_SCOPE)


def tracker_integration() -> IntegrationSpec:
    return IntegrationSpec.model_validate(
        {
            "schema_version": FOUNDRY_SCHEMA_VERSION,
            "id": TRACKER_INTEGRATION_ID,
            "kind": "integration",
            "transport": "api",
            "version": "1.0.0",
            "capabilities": ["work.read"],
            "permissions": {"write_requires": "explicit-authority"},
            "auth": {"method": "token", "credential_ref": TRACKER_CREDENTIAL_REF},
            "health": {"required": "authorized"},
        }
    )


def tracker_health(
    state: IntegrationHealthState = IntegrationHealthState.AUTHORIZED,
) -> IntegrationHealth:
    return IntegrationHealth(
        integration_id=TRACKER_INTEGRATION_ID,
        state=state,
        checked_at=FINISHED_AT,
    )


def tree_snapshot(root: Path) -> dict[str, tuple[str, int, int]]:
    """Content, mode and mtime for every path under *root*.

    mtime is included deliberately: an inspector that touched every file it read
    would leave content and mode identical, and a snapshot without mtime would pass
    the very test that exists to catch it.
    """
    snapshot: dict[str, tuple[str, int, int]] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        stat = path.lstat()
        if path.is_dir() and not path.is_symlink():
            snapshot[rel] = ("<dir>", stat.st_mode, stat.st_mtime_ns)
        else:
            digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "<other>"
            snapshot[rel] = (digest, stat.st_mode, stat.st_mtime_ns)
    return snapshot


def subprocess_env() -> dict[str, str]:
    """Pin a child process to THIS checkout, never to whatever the venv points at."""
    return {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}
