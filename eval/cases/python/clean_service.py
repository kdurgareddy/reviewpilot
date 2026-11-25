"""Order service: clean code that should produce no findings."""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class Order:
    id: int
    total_cents: int
    status: str = "pending"


class OrderService:
    def __init__(self, repo, payments):
        self.repo = repo
        self.payments = payments

    def place(self, customer_id: int, items: list[dict]) -> Order:
        if not items:
            raise ValueError("an order needs at least one item")
        total = sum(i["price_cents"] * i["qty"] for i in items)
        order = self.repo.create(customer_id=customer_id, total_cents=total)
        log.info("order %s placed for customer %s", order.id, customer_id)
        return order

    def orders_for(self, customer_ids: list[int]) -> list[Order]:
        return self.repo.fetch_many(customer_ids)

    def cancel(self, order: Order) -> Order:
        if order.status is None or order.status == "shipped":
            raise ValueError("shipped orders cannot be cancelled")
        order.status = "cancelled"
        return order

    def export(self, path: str, orders: list[Order]) -> None:
        with open(path, "w") as f:
            f.write("\n".join(f"{o.id},{o.total_cents},{o.status}" for o in orders))
