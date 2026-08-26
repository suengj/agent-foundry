"""Shared inputs for the end-to-end tests.

Nothing here is a Foundry rule, and nothing here supplies project shape the product
cannot derive: both target projects declare their own `authority.write_scope`, so the
harness runs against the builtin registry. What remains is the owner-declared
integration a runtime would be given, and helpers the tests share.
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

from tests.e2e.pipeline import FINISHED_AT

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "projects"
SYNTHETIC = FIXTURES / "e2e-synthetic"

TRACKER_INTEGRATION_ID = "work-tracker"
# The credential is a *position*, never a value: `env:ORDERS_TRACKER_TOKEN` names
# where a secret lives. `tests/test_secret_boundary.py` owns the general proof; the
# end-to-end tests check that this holds through a full compile and render.
TRACKER_CREDENTIAL_REF = "env:ORDERS_TRACKER_TOKEN"


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


def registry_granting_write_to(role_id: str):
    """The builtin registry with an extra role allowed to write the repository.

    A project supplies its own `CapabilityRegistry`, and a project can get it wrong.
    This models the specific mistake role separation exists to catch: two roles
    authorized to write the same paths in one run, one of them a review-only role.
    """
    from agent_foundry.toolkit import default_registry

    builtin = default_registry()
    roles = [
        role.model_copy(
            update={
                "allowed_capabilities": sorted(
                    {*role.allowed_capabilities, "repository.read", "repository.write"}
                )
            }
        )
        if role.id == role_id
        else role
        for role in builtin.roles
    ]
    skills = [
        skill.model_copy(
            update={"roles": skill.roles.model_copy(update={"allowed": sorted({*skill.roles.allowed, role_id})})}
        )
        if skill.id == "bounded-change"
        else skill
        for skill in builtin.skills
    ]
    return builtin.model_copy(update={"roles": roles, "skills": skills})


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
