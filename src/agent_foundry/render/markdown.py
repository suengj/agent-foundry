"""Concise Markdown projection from ExecutionBundle — never canonical state."""

from __future__ import annotations

from agent_foundry.models.execution import ExecutionBundle
from agent_foundry.secrets import raise_on_embedded_secrets


# How many selection records the rendered summary shows. The bundle is canonical;
# this is a projection, and a projection that grew without bound would stop being a
# concise agent-facing contract.
_PROVENANCE_SUMMARY_LIMIT = 10

# How many withheld write bounds the rendered contract names before summarizing.
_SCOPE_SUMMARY_LIMIT = 6


def _bullet_lines(items: list[str]) -> list[str]:
    return [f"- {item}" for item in sorted(items)]


def render_execution_bundle_markdown(bundle: ExecutionBundle) -> str:
    """Render concise agent-facing Markdown wholly from the bundle."""
    raise_on_embedded_secrets(bundle.model_dump(mode="json"))

    lines: list[str] = [
        f"# Execution Contract — {bundle.work_item_id}",
        "",
        "## Identity",
        f"- project: {bundle.project_name or 'unknown'}",
        f"- run: {bundle.run_id}",
        f"- role: {bundle.role_id}",
    ]

    if bundle.authority is not None:
        lines.extend(
            [
                f"- authority: {bundle.authority.external_effect.value}",
            ]
        )

    lines.extend(["", "## Objective", bundle.objective, ""])

    if bundle.scope:
        lines.append("## Scope")
        lines.extend(_bullet_lines(bundle.scope))
        lines.append("")

    if bundle.out_of_scope:
        lines.append("## Out of scope")
        lines.extend(_bullet_lines(bundle.out_of_scope))
        lines.append("")

    if bundle.acceptance_criteria:
        lines.append("## Acceptance criteria")
        lines.extend(_bullet_lines(bundle.acceptance_criteria))
        lines.append("")

    if bundle.allowed_capabilities:
        lines.append("## Allowed capabilities")
        lines.extend(_bullet_lines(bundle.allowed_capabilities))
        lines.append("")

    if bundle.write_scope:
        lines.append("## Write scope")
        lines.extend(_bullet_lines(bundle.write_scope))
        lines.append("")

    if bundle.authority is not None and bundle.authority.forbidden_scopes:
        forbidden = sorted(bundle.authority.forbidden_scopes)
        lines.append("## Forbidden scopes")
        lines.extend(_bullet_lines(forbidden[:_SCOPE_SUMMARY_LIMIT]))
        # Forbidden scopes grow with the project's declared envelope, not with the
        # work, so an unbounded list makes the contract's size a property of the
        # project rather than of the task. The grant above is the authority; this
        # section names bounds that were withheld, and says when it stopped listing.
        omitted = len(forbidden) - _SCOPE_SUMMARY_LIMIT
        if omitted > 0:
            lines.append(
                f"- ... and {omitted} further withheld bound(s). Only the write scope "
                "above is granted; every path outside it is denied whether or not it "
                "is listed here."
            )
        lines.append("")

    if bundle.skill_summaries:
        lines.append("## Skills (metadata only)")
        for summary in sorted(bundle.skill_summaries, key=lambda item: item.skill_id):
            lines.append(f"- `{summary.skill_id}`: {summary.description}")
            lines.append(f"  - relevance: {summary.relevance}")
        lines.append("")

    if bundle.required_evidence:
        lines.append("## Required evidence")
        lines.extend(_bullet_lines(bundle.required_evidence))
        lines.append("")

    if bundle.validator_ids:
        lines.append("## Validators")
        lines.extend(_bullet_lines(bundle.validator_ids))
        lines.append("")

    if bundle.integration_ids:
        lines.append("## Integrations")
        lines.extend(_bullet_lines(bundle.integration_ids))
        lines.append("")

    budget_parts: list[str] = []
    if bundle.budget_profile_id:
        budget_parts.append(f"profile={bundle.budget_profile_id}")
    if bundle.max_retry_budget is not None:
        budget_parts.append(f"max_retries={bundle.max_retry_budget}")
    if bundle.max_parallel_runs is not None:
        budget_parts.append(f"max_parallel={bundle.max_parallel_runs}")
    if budget_parts:
        lines.append("## Budget")
        lines.extend(_bullet_lines(budget_parts))
        lines.append("")

    if bundle.stop_conditions:
        lines.append("## Stop conditions")
        lines.extend(_bullet_lines(bundle.stop_conditions))
        lines.append("")

    if bundle.escalation_conditions:
        lines.append("## Escalation conditions")
        lines.extend(_bullet_lines(bundle.escalation_conditions))
        lines.append("")

    if bundle.interaction_outputs:
        lines.append("## Required outputs")
        lines.extend(_bullet_lines(bundle.interaction_outputs))
        lines.append("")

    context_items = sorted(
        {
            *bundle.context_refs,
            *bundle.selected_conventions,
            *bundle.selected_observations,
        }
    )
    if context_items:
        lines.append("## Selected context (refs only)")
        lines.extend(_bullet_lines(context_items))
        lines.append("")

    selected_provenance = [
        record
        for record in sorted(
            bundle.provenance,
            key=lambda item: (item.component_kind, item.component_id, item.selected),
        )
        if record.selected
    ]
    if selected_provenance:
        lines.append("## Selection provenance (summary)")
        for record in selected_provenance[:_PROVENANCE_SUMMARY_LIMIT]:
            lines.append(
                f"- {record.component_kind}/{record.component_id}: {record.rationale}"
            )
        # A summary that stops without saying so reads as the complete list. The
        # bundle is the canonical record; this says how much of it is shown and where
        # the rest is, rather than quietly dropping it.
        omitted = len(selected_provenance) - _PROVENANCE_SUMMARY_LIMIT
        if omitted > 0:
            lines.append(
                f"- ... and {omitted} further selection record(s); the ExecutionBundle "
                "`provenance` field carries all of them"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
