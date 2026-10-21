import pytest

from app.money import MoneyError, amount_at, find_amount, format_vnd, parse_amount, split_evenly


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("300k", 300_000),
        ("300K", 300_000),
        ("1tr", 1_000_000),
        ("1tr2", 1_200_000),
        ("1tr25", 1_250_000),
        ("1tr250", 1_250_000),
        ("1.5tr", 1_500_000),
        ("1,5tr", 1_500_000),
        ("2 triệu", 2_000_000),
        ("2 trieu", 2_000_000),
        ("150.000", 150_000),
        ("150,000", 150_000),
        ("150000", 150_000),
        ("1.250.000", 1_250_000),
        ("50 nghìn", 50_000),
        ("50 ngàn", 50_000),
        ("1 củ", 1_000_000),
        ("2k5", 2_500),
        ("150.000đ", 150_000),
        ("150000 vnd", 150_000),
        ("50 nghìn đồng", 50_000),
        ("1 tỷ", 1_000_000_000),
        ("1000", 1_000),
    ],
)
def test_parse_amount(text, expected):
    assert parse_amount(text) == expected


@pytest.mark.parametrize(
    "text",
    ["", "abc", "0", "0k", "-50k", "300", "1.5", "150.5", "2 tỷ", "1.5tr2", "12k3456", "k"],
)
def test_parse_amount_rejects(text):
    with pytest.raises(MoneyError):
        parse_amount(text)


def test_small_amount_suggests_k():
    with pytest.raises(MoneyError, match="300k"):
        parse_amount("300")


def test_amount_at_joins_unit_words():
    assert amount_at(["50", "nghìn", "cafe"], 0) == (50_000, 2)
    assert amount_at(["2", "triệu", "đồng", "phòng"], 0) == (2_000_000, 3)
    assert amount_at(["300k", "lẩu"], 0) == (300_000, 1)


def test_find_amount():
    assert find_amount(["Nam", "200k", "cafe"]) == (1, 1, 200_000)
    assert find_amount(["Nam", "(2)", "200k"]) == (2, 1, 200_000)
    assert find_amount(["chỉ", "có", "chữ"]) is None
    with pytest.raises(MoneyError):
        find_amount(["Nam", "300"])


@pytest.mark.parametrize(("total", "parts"), [(100_000, 3), (300_000, 3), (1_001, 7), (5, 2)])
def test_split_evenly_sums_exactly(total, parts):
    shares = split_evenly(total, parts)
    assert len(shares) == parts
    assert sum(shares) == total
    assert max(shares) - min(shares) <= 1


def test_split_evenly_remainder_goes_first():
    assert split_evenly(100_000, 3) == [33_334, 33_333, 33_333]


def test_format_vnd():
    assert format_vnd(1_200_000) == "1.200.000đ"
    assert format_vnd(0) == "0đ"
    assert format_vnd(-50_000) == "-50.000đ"
    assert format_vnd(50_000, sign=True) == "+50.000đ"
