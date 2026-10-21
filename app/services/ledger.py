"""Nghiệp vụ sổ chi tiêu.

Module này không biết gì về Zalo: chỉ làm việc với User/Ledger/Member trong DB,
nên test được hoàn toàn offline.
"""
from __future__ import annotations

import difflib
import secrets
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.errors import BotError
from app.models import EXPENSE, PAYMENT, Ledger, Member, Share, Transaction, User
from app.money import split_evenly
from app.services.settle import Transfer, settle
from app.services.vietqr import build_qr_url, normalize_bank_account
from app.text import EVERYONE_PHRASES, SELF_ALIASES, clean, normalize

VN_TZ = timezone(timedelta(hours=7))
INVITE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # bỏ 0/O, 1/I/L cho khỏi nhầm
INVITE_LENGTH = 6
MAX_MEMBER_NAME = 50
MAX_LEDGER_NAME = 100
MAX_DESCRIPTION = 200
GROUP_LEDGER_NAME = "Sổ nhóm"
DEFAULT_DESCRIPTION = "Chi tiêu chung"


class LedgerError(BotError):
    pass


@dataclass
class MonthlyStats:
    label: str
    total: int
    count: int
    paid_by: list[tuple[str, int]]
    consumed_by: list[tuple[str, int]]
    top: list[Transaction]


class LedgerService:
    def __init__(self, session: Session):
        self.session = session

    # ----- Người dùng -----

    def get_or_create_user(self, user_id: str, display_name: str) -> User:
        name = clean(display_name, 100) or "Bạn"
        user = self.session.get(User, user_id)
        if user is None:
            user = User(id=user_id, display_name=name)
            self.session.add(user)
            self.session.flush()
        elif display_name and user.display_name != name:
            user.display_name = name
        return user

    def set_bank_account(self, user: User, bank_id: str, account_no: str, holder: str) -> None:
        user.bank_id, user.bank_account, user.bank_holder = normalize_bank_account(
            bank_id, account_no, holder
        )

    # ----- Sổ -----

    def create_ledger(
        self, owner: User, name: str, group_chat_id: str | None = None
    ) -> tuple[Ledger, Member]:
        name = clean(name, MAX_LEDGER_NAME)
        if not name:
            raise LedgerError("Hãy đặt tên cho sổ, ví dụ: /taoso Đà Lạt 2026")
        ledger = Ledger(
            name=name,
            invite_code=self._new_invite_code(),
            owner_id=owner.id,
            group_chat_id=group_chat_id,
        )
        self.session.add(ledger)
        self.session.flush()
        member = self.ensure_member(ledger, owner)
        if group_chat_id is None:
            owner.active_ledger_id = ledger.id
        return ledger, member

    def _new_invite_code(self) -> str:
        while True:
            code = "".join(secrets.choice(INVITE_ALPHABET) for _ in range(INVITE_LENGTH))
            if self.session.scalar(select(Ledger.id).where(Ledger.invite_code == code)) is None:
                return code

    def ledger_for_group(self, chat_id: str, user: User) -> Ledger:
        """Mỗi nhóm chat Zalo có một sổ riêng, tạo tự động ở lệnh đầu tiên."""
        ledger = self.session.scalar(select(Ledger).where(Ledger.group_chat_id == chat_id))
        if ledger is None:
            ledger, _ = self.create_ledger(user, GROUP_LEDGER_NAME, group_chat_id=chat_id)
        return ledger

    def active_ledger(self, user: User) -> Ledger:
        ledger = self.session.get(Ledger, user.active_ledger_id) if user.active_ledger_id else None
        if ledger is None or self.member_of(ledger, user) is None:
            raise LedgerError(
                "Bạn chưa chọn sổ nào. Tạo sổ mới bằng /taoso <tên sổ> "
                "hoặc vào sổ của bạn bè bằng /vao <mã mời>."
            )
        return ledger

    def ledgers_of(self, user: User) -> list[Ledger]:
        return list(
            self.session.scalars(
                select(Ledger)
                .join(Member, Member.ledger_id == Ledger.id)
                .where(Member.user_id == user.id)
                .order_by(Ledger.id)
            )
        )

    def join_ledger(
        self, user: User, code: str, name: str | None = None
    ) -> tuple[Ledger, Member, bool]:
        """Vào sổ bằng mã mời. Trả về (sổ, thành viên, đã ở trong sổ từ trước?)."""
        code = code.strip().lstrip("#").upper()
        ledger = self.session.scalar(select(Ledger).where(Ledger.invite_code == code))
        if ledger is None:
            raise LedgerError(f"Không tìm thấy sổ có mã {code}. Kiểm tra lại mã mời nhé.")
        user.active_ledger_id = ledger.id
        existing = self.member_of(ledger, user)
        if existing is not None:
            return ledger, existing, True
        return ledger, self.ensure_member(ledger, user, name), False

    def switch_ledger(self, user: User, choice: str) -> Ledger:
        ledgers = self.ledgers_of(user)
        choice = choice.strip().lstrip("#")
        chosen = None
        if choice.isdigit() and 1 <= int(choice) <= len(ledgers):
            chosen = ledgers[int(choice) - 1]
        else:
            chosen = next((x for x in ledgers if x.invite_code == choice.upper()), None)
        if chosen is None:
            raise LedgerError("Không có sổ này. Gõ /chonso để xem danh sách sổ của bạn.")
        user.active_ledger_id = chosen.id
        return chosen

    # ----- Thành viên -----

    def members(self, ledger: Ledger) -> list[Member]:
        return list(
            self.session.scalars(
                select(Member).where(Member.ledger_id == ledger.id).order_by(Member.id)
            )
        )

    def member_of(self, ledger: Ledger, user: User) -> Member | None:
        return self.session.scalar(
            select(Member).where(Member.ledger_id == ledger.id, Member.user_id == user.id)
        )

    def _member_by_norm(self, ledger: Ledger, norm_name: str) -> Member | None:
        return self.session.scalar(
            select(Member).where(Member.ledger_id == ledger.id, Member.norm_name == norm_name)
        )

    def _validate_new_name(self, raw: str) -> str:
        name = clean(raw, MAX_MEMBER_NAME).lstrip("@").strip()
        if not name or not any(ch.isalpha() for ch in name):
            raise LedgerError(f'Tên "{raw.strip()}" không hợp lệ, tên cần có chữ cái.')
        if name.lower() in SELF_ALIASES or normalize(name) in EVERYONE_PHRASES:
            raise LedgerError(f'Không dùng được "{name}" làm tên thành viên.')
        return name

    def _create_member(self, ledger: Ledger, name: str, user: User | None = None) -> Member:
        member = Member(
            ledger_id=ledger.id,
            name=name,
            norm_name=normalize(name),
            user_id=user.id if user else None,
        )
        self.session.add(member)
        self.session.flush()
        return member

    def ensure_member(self, ledger: Ledger, user: User, name: str | None = None) -> Member:
        """Lấy thành viên gắn với user; chưa có thì tạo (mặc định dùng tên Zalo).

        Nếu trong sổ đã có một tên trùng mà chưa ai nhận, coi đó là user này.
        """
        member = self.member_of(ledger, user)
        if member is not None:
            return member
        wanted = self._validate_new_name(name or user.display_name)
        existing = self._member_by_norm(ledger, normalize(wanted))
        if existing is None:
            return self._create_member(ledger, wanted, user)
        if existing.user_id is None:
            existing.user_id = user.id
            return existing
        if name is not None:
            raise LedgerError(f'Tên "{wanted}" đã có người dùng, hãy chọn tên khác.')
        return self._create_member(ledger, self._unique_name(ledger, wanted), user)

    def _unique_name(self, ledger: Ledger, name: str) -> str:
        for index in range(2, 100):
            candidate = f"{name[: MAX_MEMBER_NAME - 5]} ({index})"
            if self._member_by_norm(ledger, normalize(candidate)) is None:
                return candidate
        raise LedgerError("Sổ có quá nhiều tên trùng nhau.")

    def add_members(self, ledger: Ledger, names: list[str]) -> tuple[list[str], list[str]]:
        """Thêm thành viên chỉ có tên. Trả về (đã thêm, đã có sẵn)."""
        added: list[str] = []
        skipped: list[str] = []
        for raw in names:
            name = self._validate_new_name(raw)
            existing = self._member_by_norm(ledger, normalize(name))
            if existing is not None:
                skipped.append(existing.name)
            else:
                added.append(self._create_member(ledger, name).name)
        return added, skipped

    def link_member(self, ledger: Ledger, user: User, raw_name: str) -> Member:
        """/toila: nhận một tên có sẵn trong sổ là của mình."""
        target = self.find_member(ledger, raw_name)
        if target.user_id == user.id:
            return target
        if target.user_id is not None:
            raise LedgerError(f'"{target.name}" đã được một tài khoản Zalo khác nhận rồi.')
        current = self.member_of(ledger, user)
        if current is not None:
            if self._has_history(current):
                current.user_id = None  # giữ tên cũ vì đã có lịch sử chi tiêu
            else:
                self.session.delete(current)
            self.session.flush()
        target.user_id = user.id
        return target

    def _has_history(self, member: Member) -> bool:
        return bool(
            self.session.scalar(
                select(
                    exists().where(Transaction.payer_id == member.id)
                    | exists().where(Share.member_id == member.id)
                )
            )
        )

    def find_member(self, ledger: Ledger, raw_name: str, me: Member | None = None) -> Member:
        name = clean(raw_name, MAX_MEMBER_NAME * 2).lstrip("@").strip()
        if not name:
            raise LedgerError("Thiếu tên thành viên.")
        if name.lower() in SELF_ALIASES:
            if me is None:
                raise LedgerError("Bạn chưa là thành viên của sổ này.")
            return me

        norm = normalize(name)
        members = self.members(ledger)
        for member in members:
            if member.norm_name == norm:
                return member
        # "Nam" khớp với "Nguyễn Văn Nam" nếu chỉ có một người như vậy.
        partial = [m for m in members if f" {norm} " in f" {m.norm_name} "]
        if len(partial) == 1:
            return partial[0]
        if partial:
            names = ", ".join(m.name for m in partial)
            raise LedgerError(f'"{name}" trùng với nhiều người: {names}. Hãy ghi rõ hơn.')

        by_norm = {m.norm_name: m for m in members}
        close = difflib.get_close_matches(norm, list(by_norm), n=3, cutoff=0.6)
        hint = f" Có phải ý bạn là: {', '.join(by_norm[c].name for c in close)}?" if close else ""
        raise LedgerError(f'Không có thành viên "{name}" trong sổ.{hint} Xem danh sách: /thanhvien')

    def resolve_participants(
        self,
        ledger: Ledger,
        me: Member | None,
        targets: list[str] | None,
        excludes: list[str],
    ) -> list[Member]:
        """targets=None nghĩa là tất cả thành viên hiện có của sổ."""
        chosen = self.members(ledger) if targets is None else self._resolve_names(ledger, targets, me)
        if excludes:
            removed = {m.id for m in self._resolve_names(ledger, excludes, me)}
            chosen = [m for m in chosen if m.id not in removed]
        if not chosen:
            raise LedgerError("Không còn ai để chia khoản này.")
        return chosen

    def _resolve_names(self, ledger: Ledger, names: list[str], me: Member | None) -> list[Member]:
        result: list[Member] = []
        seen: set[int] = set()
        for raw in names:
            try:
                found = [self.find_member(ledger, raw, me)]
            except LedgerError as err:
                # "cho Nam Linh" (quên dấu phẩy): thử tách theo khoảng trắng.
                parts = raw.split()
                if len(parts) < 2:
                    raise
                try:
                    found = [self.find_member(ledger, part, me) for part in parts]
                except LedgerError:
                    raise err from None
            for member in found:
                if member.id not in seen:
                    seen.add(member.id)
                    result.append(member)
        return result

    # ----- Khoản chi & trả nợ -----

    def add_expense(
        self,
        ledger: Ledger,
        payer: Member,
        amount: int,
        description: str,
        participants: list[Member],
        created_by: User,
    ) -> Transaction:
        tx = Transaction(
            ledger_id=ledger.id,
            kind=EXPENSE,
            payer_id=payer.id,
            amount=amount,
            description=clean(description, MAX_DESCRIPTION) or DEFAULT_DESCRIPTION,
            created_by=created_by.id,
        )
        tx.shares = [
            Share(member_id=member.id, amount=part)
            for member, part in zip(participants, split_evenly(amount, len(participants)), strict=True)
        ]
        self.session.add(tx)
        self.session.flush()
        self.session.refresh(tx)
        return tx

    def add_payment(
        self, ledger: Ledger, sender: Member, receiver: Member, amount: int, created_by: User
    ) -> Transaction:
        if sender.id == receiver.id:
            raise LedgerError("Không thể tự trả nợ cho chính mình.")
        tx = Transaction(
            ledger_id=ledger.id,
            kind=PAYMENT,
            payer_id=sender.id,
            amount=amount,
            description="Trả nợ",
            created_by=created_by.id,
        )
        tx.shares = [Share(member_id=receiver.id, amount=amount)]
        self.session.add(tx)
        self.session.flush()
        self.session.refresh(tx)
        return tx

    def get_transaction(self, ledger: Ledger, tx_id: int) -> Transaction:
        tx = self.session.get(Transaction, tx_id)
        if tx is None or tx.ledger_id != ledger.id:
            raise LedgerError(f"Không tìm thấy khoản #{tx_id} trong sổ này.")
        return tx

    def check_can_delete(self, ledger: Ledger, user: User, tx: Transaction) -> None:
        if user.id not in (tx.created_by, ledger.owner_id):
            raise LedgerError("Chỉ người ghi khoản này hoặc chủ sổ mới được xóa.")

    def delete_transaction(self, ledger: Ledger, user: User, tx: Transaction) -> None:
        self.check_can_delete(ledger, user, tx)
        self.session.delete(tx)
        self.session.flush()

    def history(self, ledger: Ledger, limit: int = 10) -> list[Transaction]:
        return list(
            self.session.scalars(
                select(Transaction)
                .where(Transaction.ledger_id == ledger.id)
                .order_by(Transaction.id.desc())
                .limit(limit)
            )
        )

    def has_transactions(self, ledger: Ledger) -> bool:
        return bool(
            self.session.scalar(select(exists().where(Transaction.ledger_id == ledger.id)))
        )

    # ----- Số dư & tất toán -----

    def balances(self, ledger: Ledger) -> dict[int, int]:
        """member_id -> số dư (+ được nhận lại, - còn phải trả). Tổng luôn bằng 0."""
        result = {member.id: 0 for member in self.members(ledger)}
        paid = self.session.execute(
            select(Transaction.payer_id, func.sum(Transaction.amount))
            .where(Transaction.ledger_id == ledger.id)
            .group_by(Transaction.payer_id)
        )
        for member_id, total in paid:
            result[member_id] = result.get(member_id, 0) + int(total)
        owed = self.session.execute(
            select(Share.member_id, func.sum(Share.amount))
            .join(Transaction, Share.transaction_id == Transaction.id)
            .where(Transaction.ledger_id == ledger.id)
            .group_by(Share.member_id)
        )
        for member_id, total in owed:
            result[member_id] = result.get(member_id, 0) - int(total)
        return result

    def settlement(self, ledger: Ledger) -> list[Transfer]:
        return settle(self.balances(ledger))

    def payment_qr(
        self, ledger: Ledger, me: Member, creditor: Member, amount: int | None = None
    ) -> tuple[int, str]:
        """Trả về (số tiền, link ảnh QR) để me chuyển cho creditor."""
        if creditor.id == me.id:
            raise LedgerError("Không thể tự chuyển tiền cho chính mình.")
        if amount is None:
            amount = sum(
                t.amount
                for t in self.settlement(ledger)
                if t.debtor == me.id and t.creditor == creditor.id
            )
            if amount <= 0:
                raise LedgerError(
                    f"Theo /tatoan, bạn không cần chuyển cho {creditor.name}. "
                    f"Muốn chuyển số khác thì gõ: /qr {creditor.name} <số tiền>"
                )
        owner = self.session.get(User, creditor.user_id) if creditor.user_id else None
        if owner is None or not owner.bank_account:
            raise LedgerError(
                f"{creditor.name} chưa khai báo tài khoản ngân hàng. {creditor.name} cần nhắn "
                "cho bot: /taikhoan <ngân hàng> <số TK> <tên chủ TK>"
            )
        url = build_qr_url(
            owner.bank_id, owner.bank_account, owner.bank_holder, amount,
            f"{me.name} tra {creditor.name}",
        )
        return amount, url

    # ----- Thống kê -----

    def monthly_stats(self, ledger: Ledger, now: datetime | None = None) -> MonthlyStats:
        local_now = (now or datetime.now(timezone.utc)).astimezone(VN_TZ)
        start = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = (start + timedelta(days=32)).replace(day=1)
        txs = list(
            self.session.scalars(
                select(Transaction)
                .where(
                    Transaction.ledger_id == ledger.id,
                    Transaction.kind == EXPENSE,
                    Transaction.created_at >= start.astimezone(timezone.utc),
                    Transaction.created_at < end.astimezone(timezone.utc),
                )
                .order_by(Transaction.id)
            )
        )
        paid: dict[str, int] = defaultdict(int)
        consumed: dict[str, int] = defaultdict(int)
        for tx in txs:
            paid[tx.payer.name] += tx.amount
            for share in tx.shares:
                consumed[share.member.name] += share.amount

        def ranked(data: dict[str, int]) -> list[tuple[str, int]]:
            return sorted(data.items(), key=lambda item: (-item[1], item[0]))

        return MonthlyStats(
            label=start.strftime("%m/%Y"),
            total=sum(tx.amount for tx in txs),
            count=len(txs),
            paid_by=ranked(paid),
            consumed_by=ranked(consumed),
            top=sorted(txs, key=lambda tx: (-tx.amount, tx.id))[:5],
        )
