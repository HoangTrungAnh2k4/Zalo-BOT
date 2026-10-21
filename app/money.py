"""Đọc và hiển thị số tiền VND. Tiền luôn là số nguyên (đồng), không dùng float."""
from __future__ import annotations

import re
from decimal import Decimal

from app.errors import BotError
from app.text import normalize

MIN_AMOUNT = 1_000
MAX_AMOUNT = 1_000_000_000

_UNIT_VALUES = {
    "k": 1_000,
    "nghin": 1_000,
    "ngan": 1_000,
    "tr": 1_000_000,
    "trieu": 1_000_000,
    "cu": 1_000_000,
    "ty": 1_000_000_000,
}
# Thứ tự quan trọng: thử "vnd"/"dong" trước "d".
_CURRENCY_WORDS = ("vnd", "dong", "d")
# Các từ có thể đứng tách riêng sau con số: "50 nghìn", "2 triệu", "150.000 đ".
UNIT_WORDS = frozenset(_UNIT_VALUES) | frozenset(_CURRENCY_WORDS)

_UNIT_PATTERN = "|".join(sorted(_UNIT_VALUES, key=len, reverse=True))
# số + (đơn vị + phần lẻ)?  VD: "300", "300k", "1.5tr", "1tr2", "2k5"
_AMOUNT_RE = re.compile(rf"(\d+(?:[.,]\d+)*)(?:({_UNIT_PATTERN})(\d{{1,3}})?)?")

EXAMPLES = "Ví dụ đúng: 300k, 1tr2, 1.5tr, 150.000, 50 nghìn"


class MoneyError(BotError):
    pass


def parse_amount(text: str) -> int:
    """Đọc số tiền kiểu người Việt hay gõ, trả về số đồng.

    "300k" -> 300_000, "1tr2" -> 1_200_000, "1,5tr" -> 1_500_000,
    "150.000" -> 150_000, "2 triệu" -> 2_000_000, "1 củ" -> 1_000_000.
    """
    raw = normalize(text).replace(" ", "")
    for word in _CURRENCY_WORDS:
        if raw.endswith(word) and len(raw) > len(word):
            raw = raw[: -len(word)]
            break
    if raw.startswith("-"):
        raise MoneyError("Số tiền phải lớn hơn 0.")

    match = _AMOUNT_RE.fullmatch(raw)
    if not match:
        raise MoneyError(f'Không hiểu số tiền "{text.strip()}". {EXAMPLES}')
    number, unit, tail = match.groups()

    if unit is None:
        value = _plain_number(number, text)
    else:
        unit_value = _UNIT_VALUES[unit]
        value = _unit_number(number, text) * unit_value
        if tail:
            if not number.isdigit():
                raise MoneyError(f'Không hiểu số tiền "{text.strip()}". {EXAMPLES}')
            # "1tr2" = 1tr + 200 nghìn, "2k5" = 2k + 500 đồng
            value += int(tail.ljust(3, "0")) * unit_value // 1000

    if value != value.to_integral_value():
        raise MoneyError("Số tiền phải là số đồng chẵn.")
    amount = int(value)
    if amount <= 0:
        raise MoneyError("Số tiền phải lớn hơn 0.")
    if amount < MIN_AMOUNT:
        raise MoneyError(f"Số tiền {format_vnd(amount)} nhỏ quá. Có phải ý bạn là {amount}k?")
    if amount > MAX_AMOUNT:
        raise MoneyError("Số tiền vượt quá 1 tỷ, bạn kiểm tra lại giúp mình nhé.")
    return amount


def _plain_number(number: str, original: str) -> Decimal:
    if number.isdigit():
        return Decimal(number)
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", number):  # 150.000 / 1,500,000
        return Decimal(re.sub(r"[.,]", "", number))
    raise MoneyError(f'Không hiểu số tiền "{original.strip()}". {EXAMPLES}')


def _unit_number(number: str, original: str) -> Decimal:
    if number.isdigit():
        return Decimal(number)
    if re.fullmatch(r"\d+[.,]\d+", number):  # 1.5tr / 1,5tr
        return Decimal(number.replace(",", "."))
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3}){2,}", number):  # 1.500.000k (hiếm)
        return Decimal(re.sub(r"[.,]", "", number))
    raise MoneyError(f'Không hiểu số tiền "{original.strip()}". {EXAMPLES}')


def amount_at(tokens: list[str], index: int) -> tuple[int, int]:
    """Đọc số tiền bắt đầu ở tokens[index], gom thêm tối đa 2 từ chỉ đơn vị phía sau.

    Trả về (số tiền, số token đã dùng). Sai định dạng thì báo MoneyError.
    """
    end = index + 1
    while end < len(tokens) and end - index < 3 and normalize(tokens[end]) in UNIT_WORDS:
        end += 1
    return parse_amount(" ".join(tokens[index:end])), end - index


def find_amount(tokens: list[str], start: int = 0) -> tuple[int, int, int] | None:
    """Tìm số tiền đầu tiên từ vị trí start: trả về (vị trí, số token, số tiền).

    Không có token nào bắt đầu bằng chữ số thì trả về None; có nhưng đều sai
    định dạng thì báo lỗi của token đầu tiên.
    """
    first_error: MoneyError | None = None
    for index in range(start, len(tokens)):
        if not tokens[index][:1].isdigit():
            continue
        try:
            amount, used = amount_at(tokens, index)
        except MoneyError as err:
            first_error = first_error or err
            continue
        return index, used, amount
    if first_error:
        raise first_error
    return None


def split_evenly(total: int, parts: int) -> list[int]:
    """Chia đều, phần dư cộng mỗi người 1đ theo thứ tự để tổng luôn khớp."""
    base, remainder = divmod(total, parts)
    return [base + 1 if i < remainder else base for i in range(parts)]


def format_vnd(amount: int, *, sign: bool = False) -> str:
    """1200000 -> "1.200.000đ"; sign=True thêm dấu + cho số dương."""
    digits = f"{abs(amount):,}".replace(",", ".")
    prefix = "-" if amount < 0 else ("+" if sign and amount > 0 else "")
    return f"{prefix}{digits}đ"
