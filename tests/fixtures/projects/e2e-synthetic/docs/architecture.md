# Orders service

Pricing rules live in `src/orders/pricing.py`; persistence is behind
`OrderRepository`. Callers never touch the store directly.
