"""In-memory order store used by the fixture's tests."""


class OrderRepository:
    def __init__(self) -> None:
        self._orders: dict[str, int] = {}

    def put(self, order_id: str, total_cents: int) -> None:
        self._orders[order_id] = total_cents

    def get(self, order_id: str) -> int | None:
        return self._orders.get(order_id)
