"""Tính cách tất toán với ít lần chuyển khoản."""
from __future__ import annotations

import heapq
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Transfer:
    debtor: int
    creditor: int
    amount: int


def settle(balances: Mapping[int, int]) -> list[Transfer]:
    """Ghép người nợ nhiều nhất với người được nhận nhiều nhất cho tới khi hết nợ.

    balances: id -> số dư (+ được nhận, - phải trả), tổng phải bằng 0.
    Mỗi lượt có ít nhất một người về 0 nên số giao dịch không quá n - 1.
    """
    if sum(balances.values()) != 0:
        raise ValueError("Tổng số dư phải bằng 0")

    # heapq là min-heap: người nợ lưu số âm, người được nhận lưu số đối.
    debtors = [(balance, key) for key, balance in balances.items() if balance < 0]
    creditors = [(-balance, key) for key, balance in balances.items() if balance > 0]
    heapq.heapify(debtors)
    heapq.heapify(creditors)

    transfers: list[Transfer] = []
    while debtors and creditors:
        debt, debtor = heapq.heappop(debtors)
        credit, creditor = heapq.heappop(creditors)
        amount = min(-debt, -credit)
        transfers.append(Transfer(debtor, creditor, amount))
        if debt + amount < 0:
            heapq.heappush(debtors, (debt + amount, debtor))
        if credit + amount < 0:
            heapq.heappush(creditors, (credit + amount, creditor))
    return transfers
