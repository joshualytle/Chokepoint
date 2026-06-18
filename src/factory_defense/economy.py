"""Economy — a shared credit pool that funds turret placement.

Costs make design choices matter: every gun and module has a price, you earn
credits as you clear waves, and the editor spends from this pool when you place
or upgrade. The constraint is *peak* spend — what you have deployed at once must
fit the budget — which pushes efficient coverage over brute force.

``Bank`` is a tiny mutable value holder shared *by reference*: the ``World``
adds income to it and the ``ArsenalEditor`` spends from it, both pointing at the
same object. That sharing is the point — it's how two parts of the program agree
on one number without passing it back and forth.

In pipeline terms: finite budget is your concurrency/throughput quota. You can't
cover every event type with unlimited consumers; you size them to the load.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Bank:
    """The player's credit balance and the operations on it."""

    balance: int = 0

    def can_afford(self, cost: int) -> bool:
        return cost <= self.balance

    def spend(self, cost: int) -> bool:
        """Deduct ``cost`` if affordable. Returns False and changes nothing if not."""
        if cost > self.balance:
            return False
        self.balance -= cost
        return True

    def earn(self, amount: int) -> None:
        """Add credits (wave income, or a refund when a turret is removed)."""
        self.balance += amount
