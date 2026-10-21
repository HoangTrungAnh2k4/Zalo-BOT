"""Nhận tin nhắn Zalo, gọi nghiệp vụ và soạn câu trả lời."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.commands import (
    Command,
    CommandError,
    parse_chiho_args,
    parse_command,
    parse_expense_args,
    parse_payment_args,
    parse_qr_args,
    split_names,
)
from app.errors import BotError
from app.models import EXPENSE, Ledger, Member, ProcessedMessage, Transaction, User, as_utc
from app.money import format_vnd
from app.services.ledger import VN_TZ, LedgerError, LedgerService
from app.zalo_client import IncomingMessage, parse_update

log = logging.getLogger(__name__)

HELP_TEXT = """🤖 Bot chia tiền nhóm

📒 Bắt đầu
/taoso Đà Lạt 2026: tạo sổ mới
/vao ABC123: vào sổ bằng mã mời
/them Nam, Linh: thêm thành viên
/thanhvien · /chonso · /toila <tên>

💸 Ghi chi tiêu
/chi 300k lẩu: chia đều cả sổ
/chi 1tr2 phòng cho Nam, Linh
/chi 450k xăng cho tất cả trừ Hòa
/chiho Nam 200k cafe: Nam là người trả
/tra Linh 150k: bạn đã trả Linh

📊 Xem & tất toán
/so: số dư từng người
/tatoan: ai chuyển cho ai
/qr Linh: mã QR để trả Linh
/taikhoan VCB 0123456789 NGUYEN VAN A
/lichsu · /xoa <id> · /thongke

Số tiền gõ kiểu nào cũng được: 300k, 1tr2, 1.5tr, 150.000"""

GROUP_HELP_NOTE = "\n\n👥 Trong nhóm: nhắc tên bot rồi gõ lệnh, mỗi nhóm có một sổ riêng."
NOT_A_COMMAND = "Mình là bot chia tiền 💸 Gõ /help để xem cách dùng nhé."
INTERNAL_ERROR = "😵 Có lỗi xảy ra, bạn thử lại sau nhé."
MAX_HISTORY = 50


@dataclass(frozen=True)
class Reply:
    text: str
    photo_url: str | None = None


class Messenger(Protocol):
    async def send_message(self, chat_id: str, text: str) -> None: ...

    async def send_photo(self, chat_id: str, photo_url: str, caption: str = "") -> None: ...


class Bot:
    def __init__(self, messenger: Messenger, session_factory: Callable[[], Session]):
        self.messenger = messenger
        self.session_factory = session_factory

    async def handle_update(self, raw: Any) -> None:
        """Điểm vào cho cả webhook lẫn polling. Không bao giờ ném lỗi ra ngoài."""
        try:
            msg = parse_update(raw)
            if msg is None:
                log.debug("Bỏ qua update không dùng được: %r", raw)
                return
            if msg.from_bot or not msg.text.strip():
                return
            # SQLAlchemy chạy đồng bộ, đưa sang luồng khác để không chặn event loop.
            replies = await asyncio.to_thread(self.process, msg)
            await self._send(msg.chat_id, replies)
        except Exception:
            log.exception("Lỗi khi xử lý update")

    async def _send(self, chat_id: str, replies: list[Reply]) -> None:
        for reply in replies:
            if reply.photo_url:
                try:
                    await self.messenger.send_photo(chat_id, reply.photo_url, reply.text)
                    continue
                except Exception:
                    log.exception("Gửi ảnh thất bại, gửi link thay thế")
                await self.messenger.send_message(chat_id, f"{reply.text}\n{reply.photo_url}")
            else:
                await self.messenger.send_message(chat_id, reply.text)

    def process(self, msg: IncomingMessage) -> list[Reply]:
        command = parse_command(msg.text, allow_bare=not msg.is_group)
        if command is None:
            # Trong nhóm, bot chỉ trả lời khi có lệnh để khỏi làm phiền.
            return [] if msg.is_group else [Reply(NOT_A_COMMAND)]
        if not self._first_time(msg):
            return []
        with self.session_factory() as session:
            service = LedgerService(session)
            try:
                user = service.get_or_create_user(msg.sender_id, msg.sender_name)
                reply = CommandHandler(service, msg, user).run(command)
                session.commit()
                return [reply]
            except BotError as err:
                session.rollback()
                return [Reply(f"⚠️ {err}")]
            except Exception:
                session.rollback()
                log.exception("Lỗi khi xử lý lệnh %s", command.name)
                return [Reply(INTERNAL_ERROR)]

    def _first_time(self, msg: IncomingMessage) -> bool:
        """Ghi nhận message_id; trả False nếu tin này đã được xử lý trước đó."""
        key = f"{msg.chat_id}:{msg.message_id}"
        with self.session_factory() as session:
            session.add(ProcessedMessage(key=key))
            try:
                session.commit()
                return True
            except IntegrityError:
                session.rollback()
                log.info("Bỏ qua tin nhắn trùng %s", key)
                return False


class CommandHandler:
    """Xử lý một lệnh của một người dùng trong một phiên DB."""

    def __init__(self, service: LedgerService, msg: IncomingMessage, user: User):
        self.service = service
        self.msg = msg
        self.user = user
        self._ledger: Ledger | None = None

    def run(self, command: Command) -> Reply:
        handler = getattr(self, f"cmd_{command.name}", None)
        if handler is None:
            return Reply(f"🤔 Mình không hiểu lệnh /{command.raw_name}. Gõ /help để xem hướng dẫn.")
        return handler(command.args)

    @property
    def ledger(self) -> Ledger:
        if self._ledger is None:
            if self.msg.is_group:
                self._ledger = self.service.ledger_for_group(self.msg.chat_id, self.user)
            else:
                self._ledger = self.service.active_ledger(self.user)
        return self._ledger

    def me(self) -> Member:
        if self.msg.is_group:
            # Ai gõ lệnh trong nhóm thì tự động thành thành viên của sổ nhóm.
            return self.service.ensure_member(self.ledger, self.user)
        member = self.service.member_of(self.ledger, self.user)
        if member is None:
            raise LedgerError("Bạn chưa là thành viên của sổ này.")
        return member

    def _group_only_note(self) -> Reply:
        code = self.ledger.invite_code
        return Reply(
            "👥 Trong nhóm chat, bot tự dùng sổ riêng của nhóm này.\n"
            f'Muốn xem sổ nhóm trong chat riêng, nhắn riêng cho bot: "/vao {code}"'
        )

    # ----- Bắt đầu -----

    def cmd_help(self, args: str) -> Reply:
        return Reply(HELP_TEXT + (GROUP_HELP_NOTE if self.msg.is_group else ""))

    def cmd_taoso(self, args: str) -> Reply:
        if self.msg.is_group:
            return self._group_only_note()
        ledger, _ = self.service.create_ledger(self.user, args)
        code = ledger.invite_code
        return Reply(
            f'✅ Đã tạo sổ "{ledger.name}" và chọn làm sổ đang dùng.\n'
            f"🔑 Mã mời: {code}\n"
            f'Bạn bè nhắn "/vao {code}" cho bot để tham gia.\n'
            "Thêm người không dùng bot: /them Nam, Linh"
        )

    def cmd_vao(self, args: str) -> Reply:
        if self.msg.is_group:
            return self._group_only_note()
        code, _, name = args.strip().partition(" ")
        if not code:
            raise CommandError("Cách dùng: /vao <mã mời> [tên của bạn]\nVí dụ: /vao K7Q2XP")
        ledger, member, already = self.service.join_ledger(self.user, code, name.strip() or None)
        if already:
            return Reply(f'Bạn đã ở trong sổ "{ledger.name}", đã chọn làm sổ đang dùng.')
        unclaimed = [m.name for m in self.service.members(ledger) if m.user_id is None]
        text = f'✅ Đã vào sổ "{ledger.name}" với tên "{member.name}".'
        if unclaimed:
            text += (
                f"\nNếu bạn là một trong: {', '.join(unclaimed)}, "
                "gõ /toila <tên> để nhận đúng tên."
            )
        return Reply(text)

    def cmd_chonso(self, args: str) -> Reply:
        if self.msg.is_group:
            return self._group_only_note()
        if args.strip():
            ledger = self.service.switch_ledger(self.user, args)
            return Reply(f'✅ Đang dùng sổ "{ledger.name}".')
        ledgers = self.service.ledgers_of(self.user)
        if not ledgers:
            return Reply("Bạn chưa có sổ nào. Tạo sổ: /taoso <tên sổ>")
        lines = ["📚 Sổ của bạn:"]
        for index, ledger in enumerate(ledgers, start=1):
            mark = " ✅ đang dùng" if ledger.id == self.user.active_ledger_id else ""
            lines.append(f"{index}. {ledger.name} (mã {ledger.invite_code}){mark}")
        lines.append("Gửi /chonso <số thứ tự> để chuyển sổ.")
        return Reply("\n".join(lines))

    def cmd_them(self, args: str) -> Reply:
        names = split_names(args)
        if not names:
            raise CommandError("Cách dùng: /them <tên>, <tên>\nVí dụ: /them Nam, Linh, Hòa")
        self.me()
        added, skipped = self.service.add_members(self.ledger, names)
        lines = []
        if added:
            lines.append(f"✅ Đã thêm: {', '.join(added)}")
        if skipped:
            lines.append(f"Đã có sẵn: {', '.join(skipped)}")
        return Reply("\n".join(lines))

    def cmd_thanhvien(self, args: str) -> Reply:
        me = self.me()
        members = self.service.members(self.ledger)
        lines = [f'👥 Thành viên sổ "{self.ledger.name}" ({len(members)}):']
        for member in members:
            if member.id == me.id:
                tag = " (bạn)"
            elif member.user_id:
                tag = " 🔗"
            else:
                tag = ""
            lines.append(f"• {member.name}{tag}")
        lines.append("🔗 = đã liên kết Zalo · thêm người: /them <tên>")
        return Reply("\n".join(lines))

    def cmd_toila(self, args: str) -> Reply:
        if not args.strip():
            raise CommandError("Cách dùng: /toila <tên có sẵn trong sổ>\nVí dụ: /toila Nam")
        member = self.service.link_member(self.ledger, self.user, args)
        return Reply(f'✅ Bạn giờ là "{member.name}" trong sổ "{self.ledger.name}".')

    # ----- Ghi chi tiêu -----

    def cmd_chi(self, args: str) -> Reply:
        parsed = parse_expense_args(args)
        me = self.me()
        return self._record_expense(me, me, parsed)

    def cmd_chiho(self, args: str) -> Reply:
        payer_name, parsed = parse_chiho_args(args)
        me = self.me()
        payer = self.service.find_member(self.ledger, payer_name, me)
        return self._record_expense(me, payer, parsed)

    def _record_expense(self, me: Member, payer: Member, parsed) -> Reply:
        participants = self.service.resolve_participants(
            self.ledger, me, parsed.targets, parsed.excludes
        )
        tx = self.service.add_expense(
            self.ledger, payer, parsed.amount, parsed.description, participants, self.user
        )
        return Reply(
            f"✅ #{tx.id} {payer.name} trả {format_vnd(tx.amount)} cho {tx.description}\n"
            f"{share_summary(tx)}\n"
            "Xem số dư: /so"
        )

    def cmd_tra(self, args: str) -> Reply:
        name, amount = parse_payment_args(args)
        me = self.me()
        receiver = self.service.find_member(self.ledger, name, me)
        tx = self.service.add_payment(self.ledger, me, receiver, amount, self.user)
        balance = self.service.balances(self.ledger).get(me.id, 0)
        return Reply(
            f"✅ #{tx.id} Đã ghi: {me.name} trả {receiver.name} {format_vnd(amount)}.\n"
            f"Số dư của bạn: {format_vnd(balance, sign=True)}"
        )

    # ----- Xem & tất toán -----

    def cmd_so(self, args: str) -> Reply:
        self.me()
        if not self.service.has_transactions(self.ledger):
            return Reply('Sổ chưa có khoản chi nào. Thử: /chi 300k lẩu')
        names = {m.id: m.name for m in self.service.members(self.ledger)}
        balances = self.service.balances(self.ledger)
        lines = [f'📒 Số dư sổ "{self.ledger.name}":']
        for member_id, balance in sorted(balances.items(), key=lambda item: (-item[1], item[0])):
            icon = "🟢" if balance > 0 else ("🔴" if balance < 0 else "⚪")
            lines.append(f"{icon} {names[member_id]}: {format_vnd(balance, sign=True)}")
        lines.append("(+ được nhận lại, - còn phải trả) · Tất toán: /tatoan")
        return Reply("\n".join(lines))

    def cmd_tatoan(self, args: str) -> Reply:
        self.me()
        transfers = self.service.settlement(self.ledger)
        if not transfers:
            return Reply("✅ Mọi người đã hết nợ nhau.")
        names = {m.id: m.name for m in self.service.members(self.ledger)}
        lines = [f"💸 Cách trả gọn nhất ({len(transfers)} lần chuyển):"]
        for index, t in enumerate(transfers, start=1):
            lines.append(f"{index}. {names[t.debtor]} → {names[t.creditor]}: {format_vnd(t.amount)}")
        lines.append("Trả xong thì ghi lại: /tra <tên> <số tiền>")
        lines.append("Lấy mã QR chuyển khoản: /qr <tên người nhận>")
        return Reply("\n".join(lines))

    def cmd_qr(self, args: str) -> Reply:
        name, amount = parse_qr_args(args)
        me = self.me()
        creditor = self.service.find_member(self.ledger, name, me)
        amount, url = self.service.payment_qr(self.ledger, me, creditor, amount)
        return Reply(
            f"Quét mã để chuyển {format_vnd(amount)} cho {creditor.name}.\n"
            f"Chuyển xong nhớ ghi lại: /tra {creditor.name} {amount}",
            photo_url=url,
        )

    def cmd_taikhoan(self, args: str) -> Reply:
        parts = args.split(maxsplit=2)
        if len(parts) < 3:
            if self.user.bank_account:
                return Reply(
                    f"🏦 Tài khoản của bạn: {self.user.bank_id} · {self.user.bank_account} · "
                    f"{self.user.bank_holder}\nĐổi tài khoản: /taikhoan <ngân hàng> <số TK> <tên chủ TK>"
                )
            raise CommandError(
                "Cách dùng: /taikhoan <ngân hàng> <số TK> <tên chủ TK>\n"
                "Ví dụ: /taikhoan VCB 0123456789 NGUYEN VAN A"
            )
        self.service.set_bank_account(self.user, *parts)
        return Reply(
            f"✅ Đã lưu tài khoản: {self.user.bank_id} · {self.user.bank_account} · {self.user.bank_holder}\n"
            "Bạn bè có thể gõ /qr <tên bạn> để lấy mã QR chuyển cho bạn."
        )

    def cmd_lichsu(self, args: str) -> Reply:
        self.me()
        raw = args.strip() or "10"
        if not raw.isdigit() or int(raw) < 1:
            raise CommandError("Cách dùng: /lichsu [số khoản], ví dụ /lichsu 20")
        txs = self.service.history(self.ledger, min(int(raw), MAX_HISTORY))
        if not txs:
            return Reply("Sổ chưa có khoản nào.")
        lines = [f"🧾 {len(txs)} khoản gần nhất:"] + [describe(tx) for tx in txs]
        lines.append("Xóa một khoản: /xoa <id>")
        return Reply("\n".join(lines))

    def cmd_xoa(self, args: str) -> Reply:
        parts = args.split()
        tx_id = parts[0].lstrip("#") if parts else ""
        if not tx_id.isdigit():
            raise CommandError("Cách dùng: /xoa <id>, ví dụ /xoa 12 (xem id bằng /lichsu)")
        self.me()
        tx = self.service.get_transaction(self.ledger, int(tx_id))
        self.service.check_can_delete(self.ledger, self.user, tx)
        confirmed = len(parts) > 1 and parts[1].lower() in {"ok", "co", "có", "yes"}
        if not confirmed:
            return Reply(f"Bạn chắc chắn muốn xóa?\n{describe(tx)}\nGửi /xoa {tx.id} ok để xác nhận.")
        summary = describe(tx)
        self.service.delete_transaction(self.ledger, self.user, tx)
        return Reply(f"🗑️ Đã xóa {summary}")

    def cmd_thongke(self, args: str) -> Reply:
        self.me()
        stats = self.service.monthly_stats(self.ledger)
        if not stats.count:
            return Reply(f"Tháng {stats.label} chưa có khoản chi nào.")
        lines = [
            f"📊 Tháng {stats.label}: {stats.count} khoản, tổng {format_vnd(stats.total)}",
            "",
            "Ai đã trả:",
            *[f"• {name}: {format_vnd(amount)}" for name, amount in stats.paid_by],
            "",
            "Phần mỗi người:",
            *[f"• {name}: {format_vnd(amount)}" for name, amount in stats.consumed_by],
            "",
            "Khoản lớn nhất:",
            *[f"• #{tx.id} {tx.description}: {format_vnd(tx.amount)}" for tx in stats.top],
        ]
        return Reply("\n".join(lines))


def share_summary(tx: Transaction) -> str:
    amounts = [share.amount for share in tx.shares]
    each = format_vnd(amounts[0]) if len(set(amounts)) == 1 else f"~{format_vnd(min(amounts))}"
    names = ", ".join(share.member.name for share in tx.shares)
    return f"Chia {len(amounts)} người ({names}), mỗi người {each}"


def describe(tx: Transaction) -> str:
    when = as_utc(tx.created_at).astimezone(VN_TZ).strftime("%d/%m")
    if tx.kind == EXPENSE:
        return (
            f"#{tx.id} · {when} · {tx.payer.name} trả {format_vnd(tx.amount)}, "
            f"{tx.description} ({len(tx.shares)} người)"
        )
    receiver = tx.shares[0].member.name if tx.shares else "?"
    return f"#{tx.id} · {when} · {tx.payer.name} → {receiver} {format_vnd(tx.amount)} (trả nợ)"
