"""Order intake and pricing for the synthetic end-to-end fixture."""

__all__ = ["order_total"]


def order_total(unit_price_cents: int, quantity: int) -> int:
    """Total for one order line, in cents."""
    if quantity < 0:
        raise ValueError("quantity must not be negative")
    return unit_price_cents * quantity
