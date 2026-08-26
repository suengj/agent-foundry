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
        elif spec.auth is None:
            state = IntegrationHealthState.CONFIGURED
            message = "no auth required; configured by declaration"
        else:
            state = IntegrationHealthState.DESIRED
            message = "credential reference present; authentication not verified"

        required = spec.health.required
        if not meets_required_health(state, required):
            if state == IntegrationHealthState.DESIRED:
                message = f"required health {required.value}; currently desired only"
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
