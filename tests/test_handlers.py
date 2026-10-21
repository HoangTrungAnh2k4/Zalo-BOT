import itertools
import re

import pytest

from app.handlers import Bot


class FakeMessenger:
    def __init__(self):
        self.sent = []  # (chat_id, text, photo_url)

    async def send_message(self, chat_id, text):
        self.sent.append((chat_id, text, None))

    async def send_photo(self, chat_id, photo_url, caption=""):
        self.sent.append((chat_id, caption, photo_url))


_ids = itertools.count(1)


def update(text, user="u1", name="Nam", chat=None, group=False, message_id=None):
    return {
        "event_name": "message.text.received",
        "message": {
            "message_id": message_id or f"m{next(_ids)}",
            "from": {"id": user, "display_name": name, "is_bot": False},
            "chat": {"id": chat or user, "chat_type": "GROUP" if group else "PRIVATE"},
            "date": 1_760_000_000_000,
            "text": text,
        },
    }


@pytest.fixture
def messenger():
    return FakeMessenger()


@pytest.fixture
def bot(messenger, session_factory):
    return Bot(messenger, session_factory)


async def say(bot, messenger, text, **kwargs):
    before = len(messenger.sent)
    await bot.handle_update(update(text, **kwargs))
    return messenger.sent[before:]


async def last_text(bot, messenger, text, **kwargs):
    sent = await say(bot, messenger, text, **kwargs)
    assert sent, f"bot không trả lời: {text}"
    return sent[-1][1]


async def test_full_private_flow(bot, messenger):
    reply = await last_text(bot, messenger, "/taoso Đà Lạt")
    code = re.search(r"Mã mời: (\w+)", reply).group(1)

    assert "Đã thêm: Linh, Hòa" in await last_text(bot, messenger, "/them Linh, Hòa")

    reply = await last_text(bot, messenger, f"/vao {code}", user="u2", name="Linh Trần")
    assert 'tên "Linh Trần"' in reply and "/toila" in reply
    assert '"Linh"' in await last_text(bot, messenger, "/toila linh", user="u2", name="Linh Trần")

    reply = await last_text(bot, messenger, "/chi 300k lẩu")
    assert "Nam trả 300.000đ cho lẩu" in reply
    assert "Chia 3 người (Nam, Linh, Hòa), mỗi người 100.000đ" in reply

    reply = await last_text(bot, messenger, "/tra Nam 100k", user="u2", name="Linh Trần")
    assert "Linh trả Nam 100.000đ" in reply and "Số dư của bạn: 0đ" in reply

    reply = await last_text(bot, messenger, "/so")
    assert "🟢 Nam: +100.000đ" in reply and "🔴 Hòa: -100.000đ" in reply

    reply = await last_text(bot, messenger, "/tatoan")
    assert "1. Hòa → Nam: 100.000đ" in reply

    assert "Đã lưu tài khoản" in await last_text(
        bot, messenger, "/taikhoan VCB 0123456789 Nguyễn Văn Nam"
    )
    sent = await say(bot, messenger, "/qr Nam 50k", user="u2", name="Linh Trần")
    _, caption, photo = sent[-1]
    assert photo.startswith("https://img.vietqr.io/image/VCB-0123456789-compact2.png?amount=50000")
    assert "/tra Nam 50000" in caption

    reply = await last_text(bot, messenger, "/lichsu")
    assert "#1" in reply and "#2" in reply

    assert "/xoa 2 ok" in await last_text(bot, messenger, "/xoa 2")
    assert "Đã xóa #2" in await last_text(bot, messenger, "/xoa 2 ok")
    assert "Linh: -100.000đ" in await last_text(bot, messenger, "/so")

    assert "Tháng" in await last_text(bot, messenger, "/thongke")


async def test_errors_are_explained(bot, messenger):
    assert "chưa chọn sổ" in await last_text(bot, messenger, "/chi 300k lẩu")
    await say(bot, messenger, "/taoso Nhà trọ")
    assert "Ví dụ" in await last_text(bot, messenger, "/chi lẩu")
    assert "Có phải ý bạn là 300k" in await last_text(bot, messenger, "/chi 300 lẩu")
    assert "Không có thành viên" in await last_text(bot, messenger, "/chi 300k lẩu cho Tú")
    assert "không hiểu lệnh" in await last_text(bot, messenger, "/abc")


async def test_bare_commands_in_private(bot, messenger):
    await say(bot, messenger, "taoso Nhà trọ")
    assert "300.000đ" in await last_text(bot, messenger, "chi 300k điện")
    assert "/help" in await last_text(bot, messenger, "xin chào")


async def test_duplicate_message_is_ignored(bot, messenger):
    await say(bot, messenger, "/taoso Test")
    first = await say(bot, messenger, "/chi 100k cafe", message_id="dup")
    again = await say(bot, messenger, "/chi 100k cafe", message_id="dup")
    assert first and not again


async def test_group_chat(bot, messenger):
    group = {"chat": "g1", "group": True}
    reply = await last_text(bot, messenger, "@Bot Chia Tiền /chi 90k trà sữa", **group)
    assert "Nam trả 90.000đ" in reply and "Chia 1 người" in reply

    await say(bot, messenger, "@Bot /them Linh", user="u2", name="Linh", **group)
    reply = await last_text(bot, messenger, "@Bot /chiho Linh 60k bánh", user="u2", name="Linh", **group)
    assert "Linh trả 60.000đ" in reply and "Chia 2 người" in reply

    assert "sổ riêng" in await last_text(bot, messenger, "@Bot /taoso Khác", **group)
    # Trong nhóm, tin không phải lệnh thì bot im lặng.
    assert await say(bot, messenger, "@Bot cảm ơn nha", **group) == []


async def test_ignores_bot_and_non_text(bot, messenger):
    raw = update("/help")
    raw["message"]["from"]["is_bot"] = True
    await bot.handle_update(raw)
    await bot.handle_update({"event_name": "message.sticker.received", "message": {"sticker": "x"}})
    await bot.handle_update("rác")
    assert messenger.sent == []


async def test_unwraps_ok_result_envelope(bot, messenger):
    await bot.handle_update({"ok": True, "result": update("/help")})
    assert "Bot chia tiền nhóm" in messenger.sent[-1][1]


async def test_photo_failure_falls_back_to_link(session_factory):
    class NoPhoto(FakeMessenger):
        async def send_photo(self, chat_id, photo_url, caption=""):
            raise RuntimeError("boom")

    messenger = NoPhoto()
    bot = Bot(messenger, session_factory)
    await say(bot, messenger, "/taoso Test")
    await say(bot, messenger, "/them Linh")
    await say(bot, messenger, "/vao " + _code(messenger), user="u2", name="Linh")
    await say(bot, messenger, "/taikhoan MB 999999 Le Thi Linh", user="u2", name="Linh")
    sent = await say(bot, messenger, "/qr Linh 20k")
    assert sent[-1][2] is None and "img.vietqr.io" in sent[-1][1]


def _code(messenger):
    for _, text, _ in messenger.sent:
        if match := re.search(r"Mã mời: (\w+)", text or ""):
            return match.group(1)
    raise AssertionError("không thấy mã mời")
