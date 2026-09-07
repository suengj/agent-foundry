"""Synthetic long-running service entry point.

Declares the runtime health surface a deploy platform would poll
(`GET /healthz`) and starts the background work loop. This is illustrative
scaffolding for a fixture, not a runnable application.
"""

from __future__ import annotations


def healthz() -> dict[str, str]:
    """Health endpoint: reports whether the background loop is running."""
    return {"status": "ok"}


def run_forever() -> None:
    """Synthetic continuous work loop — never returns while the service is up."""
    while True:  # pragma: no cover - illustrative only
        pass
