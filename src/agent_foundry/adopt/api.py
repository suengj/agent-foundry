"""Adoption planning API — prescription from intake evidence."""

from __future__ import annotations

from agent_foundry.adopt.authority import assert_change_set_respects_authority
from agent_foundry.adopt.changes import (
    build_change_set,
    proposed_autonomy_for_change,
    proposed_external_effect_for_change,
)
from agent_foundry.adopt.manifest import synthesize_manifest
from agent_foundry.models.project import AdoptionPlanResult, ProjectIntake


def plan_adoption(intake: ProjectIntake) -> AdoptionPlanResult:
    """Synthesize a ProjectManifest and adoption change set from read-only intake evidence."""
    manifest = synthesize_manifest(intake)
    change_set = build_change_set(intake, manifest)

    for change in change_set.changes:
        assert_change_set_respects_authority(
            [change],
            current_autonomy=manifest.execution.autonomy,
            proposed_autonomy=proposed_autonomy_for_change(change),
            current_external_effect=manifest.impact.external_effect,
            proposed_external_effect=proposed_external_effect_for_change(change),
        )

    return AdoptionPlanResult(manifest=manifest, change_set=change_set)
