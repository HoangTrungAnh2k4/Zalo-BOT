import random

import pytest

from app.services.settle import Transfer, settle


def apply(balances, transfers):
    result = dict(balances)
    for t in transfers:
        assert t.amount > 0
        result[t.debtor] += t.amount
        result[t.creditor] -= t.amount
    return result


def check(balances):
    transfers = settle(balances)
    assert all(v == 0 for v in apply(balances, transfers).values())
    nonzero = sum(1 for v in balances.values() if v)
    assert len(transfers) <= max(nonzero - 1, 0)
    return transfers


def test_two_people():
    assert check({1: 100_000, 2: -100_000}) == [Transfer(2, 1, 100_000)]


def test_three_people():
    transfers = check({1: 200_000, 2: -100_000, 3: -100_000})
    assert sorted(transfers, key=lambda t: t.debtor) == [
        Transfer(2, 1, 100_000),
        Transfer(3, 1, 100_000),
    ]


def test_five_people():
    check({1: 500_000, 2: -150_000, 3: -150_000, 4: 100_000, 5: -300_000})


def test_everyone_even():
    assert settle({1: 0, 2: 0}) == []


def test_rejects_unbalanced():
    with pytest.raises(ValueError):
        settle({1: 100, 2: -50})


def test_random_balances():
    rng = random.Random(42)
    for _ in range(300):
        size = rng.randint(2, 12)
        values = [rng.randint(-2_000_000, 2_000_000) for _ in range(size - 1)]
        values.append(-sum(values))
        check(dict(enumerate(values)))
