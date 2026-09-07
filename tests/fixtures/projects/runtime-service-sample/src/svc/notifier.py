"""Synthetic external-effect surface: posts notifications to an outside webhook.

Every call here is a write the service makes outside its own process — the
external-effect boundary this fixture exists to exercise. No real endpoint is
contacted; the URL is read from configuration and never hard-coded.
"""

from __future__ import annotations

import os


def notify(event: str) -> None:
    """Send a notification about *event* to the configured webhook, if any."""
    webhook_url = os.environ.get("NOTIFICATION_WEBHOOK_URL")
    if not webhook_url:
        return
    # Illustrative only: a real implementation would POST `event` to `webhook_url`.
