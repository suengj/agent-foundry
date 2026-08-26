"""Public models export surface stability."""

from __future__ import annotations

import json
from pathlib import Path

import agent_foundry.models as models

BASELINE_PATH = Path(__file__).resolve().parent / "fixtures" / "models_public_exports.json"


def _baseline_names() -> set[str]:
    """The public export surface as last deliberately reviewed.

    This is a checked-in file rather than a `git show origin/main` lookup. A guard read
    from a moving branch tip can only pass while the change is unmerged: the moment it
    lands, "what this branch adds relative to main" is the empty set and the guard
    inverts. It also made the suite depend on remote git state. A pinned baseline makes
    dropping or adding a public name a visible, reviewable diff instead.
    """
    return set(json.loads(BASELINE_PATH.read_text()))


def test_every_declared_export_resolves():
    for name in models.__all__:
        assert hasattr(models, name), f"missing export: {name}"
        assert getattr(models, name) is not None


def test_no_public_export_is_dropped_without_updating_the_baseline():
    dropped = sorted(_baseline_names() - set(models.__all__))
    assert dropped == [], (
        f"public exports removed: {dropped}. Removing a name from "
        f"agent_foundry.models.__all__ breaks importers; if it is intended, update "
        f"{BASELINE_PATH.name} in the same change."
    )


def test_new_public_exports_are_recorded_in_the_baseline():
    added = sorted(set(models.__all__) - _baseline_names())
    assert added == [], (
        f"public exports added without review: {added}. Add them to "
        f"{BASELINE_PATH.name} so the export surface stays an explicit decision."
    )


def test_baseline_has_no_stale_or_duplicate_entries():
    raw = json.loads(BASELINE_PATH.read_text())
    assert len(raw) == len(set(raw)), "baseline contains duplicate names"
    assert raw == sorted(raw), "baseline must stay sorted for reviewable diffs"
