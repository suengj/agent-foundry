"""Deterministic checks for the synthetic fixture (named to avoid outer collection)."""

from orders import order_total
from orders.pricing import discounted_total


def check_order_total() -> None:
    assert order_total(500, 3) == 1500


def check_discounted_total() -> None:
    assert discounted_total(500, 3, 10) == 1350
