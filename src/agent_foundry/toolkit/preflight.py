"""Integration preflight — distinct health states without secret material."""

from __future__ import annotations

from agent_foundry.models.common import IntegrationHealthState
from agent_foundry.models.integrations import IntegrationHealth, IntegrationSpec

_HEALTH_ORDER: dict[IntegrationHealthState, int] = {
    IntegrationHealthState.DESIRED: 0,
    IntegrationHealthState.AVAILABLE: 1,
    IntegrationHealthState.CONFIGURED: 2,
    IntegrationHealthState.AUTHENTICATED: 3,
    IntegrationHealthState.AUTHORIZED: 4,
    IntegrationHealthState.HEALTHY: 5,
    IntegrationHealthState.DEGRADED: 4,
    IntegrationHealthState.UNAVAILABLE: -1,
}


def health_state_rank(state: IntegrationHealthState) -> int:
    return _HEALTH_ORDER[state]


def meets_required_health(actual: IntegrationHealthState, required: IntegrationHealthState) -> bool:
    """Does an observed lifecycle state clear the bar an IntegrationSpec declared?

    Two different things meet here and must not be confused:

    - ``actual`` is what preflight could **establish about the world**. Only states from
      ``available`` upward are positive establishments. ``desired`` means nothing has been
      confirmed yet, and ``unavailable`` means confirmed unusable; neither clears any bar
      above ``desired``.
    - ``required`` is the bar the project **declared** in ``IntegrationSpec.health``.
      Declaring ``required: desired`` is the one supported way to say "this integration
      needs no health verification". It is a decision recorded in configuration, not an
      inference drawn from missing data, and it is the only path on which an unobserved
      integration resolves.
    """
    if actual == IntegrationHealthState.UNAVAILABLE:
        return False
    if required == IntegrationHealthState.HEALTHY:
        return actual in {IntegrationHealthState.HEALTHY, IntegrationHealthState.DEGRADED}
    return health_state_rank(actual) >= health_state_rank(required)


def preflight_integrations(
    integrations: list[IntegrationSpec],
    *,
    required_ids: list[str],
    observed_health: list[IntegrationHealth] = [],
) -> list[IntegrationHealth]:
    """Report integration health for required integrations — never exposes secret material."""
    observed = {item.integration_id: item for item in observed_health}
    by_id = {spec.id: spec for spec in integrations}
    results: list[IntegrationHealth] = []

    for integration_id in sorted(required_ids):
        spec = by_id.get(integration_id)
        observed_item = observed.get(integration_id)
        if spec is None:
            results.append(
                IntegrationHealth(
                    integration_id=integration_id,
                    state=IntegrationHealthState.UNAVAILABLE,
                    message="integration not declared",
                )
            )
            continue

        if observed_item is not None:
            state = observed_item.state
            message = observed_item.message
        else:
            # Nothing observed this integration. docs/foundry/04 §12: presence in
            # configuration is not equivalent to usability, so the declaration cannot
            # supply a lifecycle state it never established. The shape of `auth` says
            # something about the declaration and nothing about the world; deriving
            # `configured` from `auth is None` let an unchecked integration clear a bar
            # it was never measured against. Unobserved is `desired` either way, and the
            # auth shape only changes the diagnostic.
            state = IntegrationHealthState.DESIRED
            message = (
                "declared without auth; health not observed"
                if spec.auth is None
                else "credential reference present; health not observed"
            )

        required = spec.health.required
        if not meets_required_health(state, required):
            if state == IntegrationHealthState.DESIRED:
                message = (
                    f"required health {required.value}; nothing established beyond desired"
                    f" ({message})"
                )
            elif state == IntegrationHealthState.AUTHENTICATED and required == IntegrationHealthState.AUTHORIZED:
                message = "authenticated but not authorized for required scope"
            else:
                message = message or f"required health {required.value}; actual {state.value}"

        results.append(
            IntegrationHealth(
                integration_id=integration_id,
                state=state,
                message=message,
            )
        )

    return results


def integration_preflight_passes(health_results: list[IntegrationHealth], integrations: list[IntegrationSpec]) -> bool:
    by_id = {spec.id: spec for spec in integrations}
    for item in health_results:
        spec = by_id.get(item.integration_id)
        if spec is None:
            return False
        if not meets_required_health(item.state, spec.health.required):
            return False
    return True
