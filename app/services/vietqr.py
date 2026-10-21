"""Tạo link ảnh VietQR (https://vietqr.io) để chuyển khoản đúng số tiền."""
from __future__ import annotations

import re
from urllib.parse import quote, urlencode

from app.errors import BotError
from app.text import strip_accents

QR_IMAGE_BASE = "https://img.vietqr.io/image"
QR_TEMPLATE = "compact2"
# Nhiều ngân hàng chỉ nhận nội dung chuyển khoản ngắn và không dấu.
NOTE_MAX_LENGTH = 25


class BankAccountError(BotError):
    pass


def normalize_bank_account(bank_id: str, account_no: str, holder: str) -> tuple[str, str, str]:
    bank = bank_id.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{2,20}", bank):
        raise BankAccountError(
            "Mã ngân hàng không hợp lệ. Dùng tên viết tắt (VCB, MB, TCB, ACB...) hoặc mã BIN 6 số."
        )
    account = re.sub(r"[\s.-]", "", account_no)
    if not re.fullmatch(r"[0-9A-Za-z]{4,20}", account):
        raise BankAccountError("Số tài khoản không hợp lệ.")
    name = " ".join(strip_accents(holder).upper().split())
    if not re.fullmatch(r"[A-Z ]{2,50}", name):
        raise BankAccountError("Tên chủ tài khoản chỉ gồm chữ cái, ví dụ: NGUYEN VAN A")
    return bank, account, name


def clean_transfer_note(text: str) -> str:
    note = re.sub(r"[^A-Za-z0-9 ]", " ", strip_accents(text))
    return " ".join(note.split())[:NOTE_MAX_LENGTH].strip()


def build_qr_url(bank_id: str, account_no: str, holder: str, amount: int, note: str) -> str:
    query = urlencode(
        {"amount": amount, "addInfo": clean_transfer_note(note), "accountName": holder},
        quote_via=quote,
    )
    return f"{QR_IMAGE_BASE}/{quote(bank_id)}-{quote(account_no)}-{QR_TEMPLATE}.png?{query}"
