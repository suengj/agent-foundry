"""Discount rules applied on top of an order total."""

from orders import order_total


def discounted_total(unit_price_cents: int, quantity: int, percent_off: int) -> int:
    if not 0 <= percent_off <= 100:
        raise ValueError("percent_off must be between 0 and 100")
    gross = order_total(unit_price_cents, quantity)
    return gross - (gross * percent_off) // 100
