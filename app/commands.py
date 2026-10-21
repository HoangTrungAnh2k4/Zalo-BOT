"""Tách lệnh và tham số từ tin nhắn người dùng."""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.errors import BotError
from app.money import MoneyError, amount_at, find_amount
from app.text import EVERYONE_PHRASES, nfc, normalize

# Gõ có dấu hay không đều được: "/chọnsổ" -> "chonso".
COMMAND_ALIASES = {
    "start": "help",
    "help": "help",
    "huongdan": "help",
    "trogiup": "help",
    "taoso": "taoso",
    "vao": "vao",
    "thamgia": "vao",
    "chonso": "chonso",
    "doiso": "chonso",
    "them": "them",
    "thanhvien": "thanhvien",
    "tv": "thanhvien",
    "toila": "toila",
    "chi": "chi",
    "chiho": "chiho",
    "tra": "tra",
    "so": "so",
    "sodu": "so",
    "tatoan": "tatoan",
    "lichsu": "lichsu",
    "xoa": "xoa",
    "taikhoan": "taikhoan",
    "qr": "qr",
    "thongke": "thongke",
}

USAGE_CHI = (
    "Cách ghi: /chi <số tiền> <nội dung> [cho <tên>, <tên>]\n"
    "Ví dụ:\n"
    "• /chi 300k lẩu\n"
    "• /chi 1tr2 tiền phòng cho Nam, Linh\n"
    "• /chi 450k xăng cho tất cả trừ Hòa"
)
USAGE_CHIHO = "Cách ghi: /chiho <người trả> <số tiền> <nội dung> [cho ...]\nVí dụ: /chiho Nam 200k cafe"
USAGE_TRA = "Cách ghi: /tra <tên> <số tiền>\nVí dụ: /tra Linh 150k"

# Lệnh có thể nằm sau phần @mention bot trong nhóm: "@Bot Chia Tiền /chi 300k lẩu".
_SLASH_COMMAND = re.compile(r"(?:^|\s)/(\S+)")
_NAME_SEPARATORS = re.compile(r"\s*(?:,|;|&|\+|\bvà\b|\bva\b)\s*", re.IGNORECASE)


class CommandError(BotError):
    pass


@dataclass(frozen=True)
class Command:
    name: str  # tên chuẩn trong COMMAND_ALIASES, hoặc "unknown"
    args: str
    raw_name: str


@dataclass(frozen=True)
class ExpenseArgs:
    amount: int
    description: str
    targets: list[str] | None  # None = tất cả thành viên
    excludes: list[str]


def parse_command(text: str, allow_bare: bool = False) -> Command | None:
    """Tìm lệnh trong tin nhắn. allow_bare cho phép gõ không cần "/" (chat riêng)."""
    text = nfc(text).strip()
    match = _SLASH_COMMAND.search(text)
    if match:
        word, args = match.group(1), text[match.end():].strip()
    elif allow_bare and text:
        word, _, args = text.partition(" ")
        if normalize(word) not in COMMAND_ALIASES:
            return None
        args = args.strip()
    else:
        return None
    name = COMMAND_ALIASES.get(normalize(word), "unknown")
    return Command(name=name, args=args, raw_name=word)


def split_names(text: str) -> list[str]:
    """ "Nam, Linh và Hòa" -> ["Nam", "Linh", "Hòa"]"""
    return [part.strip() for part in _NAME_SEPARATORS.split(text) if part.strip()]


def parse_expense_args(args: str) -> ExpenseArgs:
    tokens = args.split()
    if not tokens:
        raise CommandError(USAGE_CHI)
    try:
        amount, used = amount_at(tokens, 0)
    except MoneyError as err:
        raise CommandError(f"{err}\n\n{USAGE_CHI}") from None
    return _expense_from(amount, tokens[used:])


def parse_chiho_args(args: str) -> tuple[str, ExpenseArgs]:
    """/chiho <người trả> <số tiền> ...: tên người trả có thể có nhiều chữ."""
    tokens = args.split()
    try:
        found = find_amount(tokens, start=1)
    except MoneyError as err:
        raise CommandError(f"{err}\n\n{USAGE_CHIHO}") from None
    if found is None:
        raise CommandError(USAGE_CHIHO)
    index, used, amount = found
    return " ".join(tokens[:index]), _expense_from(amount, tokens[index + used:])


def parse_payment_args(args: str) -> tuple[str, int]:
    """ "/tra Linh 150k" hoặc "/tra 150k cho Linh" -> ("Linh", 150000)"""
    tokens = args.split()
    try:
        found = find_amount(tokens)
    except MoneyError as err:
        raise CommandError(f"{err}\n\n{USAGE_TRA}") from None
    if found is None:
        raise CommandError(USAGE_TRA)
    name = _name_around(tokens, found)
    if not name:
        raise CommandError(USAGE_TRA)
    return name, found[2]


def parse_qr_args(args: str) -> tuple[str, int | None]:
    """ "/qr Linh" hoặc "/qr Linh 50k" -> (tên, số tiền hoặc None)"""
    tokens = args.split()
    found = find_amount(tokens)
    if found is None:
        name, amount = " ".join(tokens), None
    else:
        name, amount = _name_around(tokens, found), found[2]
    if not name:
        raise CommandError("Cách dùng: /qr <tên người nhận> [số tiền]\nVí dụ: /qr Linh")
    return name, amount


def _name_around(tokens: list[str], found: tuple[int, int, int]) -> str:
    index, used, _ = found
    rest = tokens[:index] + tokens[index + used:]
    if rest and rest[0].lower() == "cho":
        rest = rest[1:]
    return " ".join(rest)


def _expense_from(amount: int, tokens: list[str]) -> ExpenseArgs:
    # Lấy chữ "cho" cuối cùng làm ranh giới: "/chi 200k quà cho mẹ cho Nam, Linh".
    split_at = None
    for index in range(len(tokens) - 2, -1, -1):
        if tokens[index].lower() == "cho":
            split_at = index
            break
    if split_at is None:
        return ExpenseArgs(amount, " ".join(tokens), None, [])
    targets, excludes = _parse_targets(tokens[split_at + 1:])
    return ExpenseArgs(amount, " ".join(tokens[:split_at]), targets, excludes)


def _parse_targets(tokens: list[str]) -> tuple[list[str] | None, list[str]]:
    """ "tất cả trừ Hòa" -> (None, ["Hòa"]); "Nam, Linh" -> (["Nam", "Linh"], [])"""
    norms = [normalize(token) for token in tokens]
    include, exclude = tokens, []
    if "tru" in norms:
        cut = norms.index("tru")
        exclude = tokens[cut + 1:]
        include = tokens[: cut - 1] if cut > 0 and norms[cut - 1] == "ngoai" else tokens[:cut]
        if not exclude:
            raise CommandError('Thiếu tên sau chữ "trừ". Ví dụ: /chi 450k xăng cho tất cả trừ Hòa')
    include_text = " ".join(include)
    targets = None if not include or normalize(include_text) in EVERYONE_PHRASES else split_names(include_text)
    return targets, split_names(" ".join(exclude))
