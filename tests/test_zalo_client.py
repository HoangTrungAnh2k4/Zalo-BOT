import json

import httpx
import pytest

from app.zalo_client import ZaloApiError, ZaloClient, parse_update, split_text


def make_client(handler):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return ZaloClient("123:secret-token", "https://api.test", http=http)


async def test_send_message_posts_json():
    calls = []

    def handler(request):
        calls.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": "1"}})

    client = make_client(handler)
    await client.send_message("c1", "xin chào")
    assert calls == [("/bot123:secret-token/sendMessage", {"chat_id": "c1", "text": "xin chào"})]


async def test_long_message_is_chunked():
    texts = []

    def handler(request):
        texts.append(json.loads(request.content)["text"])
        return httpx.Response(200, json={"ok": True, "result": {}})

    client = make_client(handler)
    await client.send_message("c1", "\n".join(["x" * 900] * 5))
    assert len(texts) == 3 and all(len(t) <= 2000 for t in texts)


async def test_api_error_does_not_leak_token():
    client = make_client(lambda request: httpx.Response(200, json={"ok": False, "error_code": 401, "description": "Unauthorized"}))
    with pytest.raises(ZaloApiError) as info:
        await client.get_me()
    assert info.value.error_code == 401
    assert "secret-token" not in str(info.value)


async def test_get_updates_timeout_returns_none():
    client = make_client(lambda request: httpx.Response(200, json={"ok": False, "error_code": 408}))
    assert await client.get_updates(timeout=1) is None


async def test_retries_on_429(monkeypatch):
    responses = iter([
        httpx.Response(429, headers={"retry-after": "0"}, json={"ok": False}),
        httpx.Response(200, json={"ok": True, "result": {"id": "bot"}}),
    ])

    async def no_sleep(_):
        return None

    monkeypatch.setattr("app.zalo_client.asyncio.sleep", no_sleep)
    client = make_client(lambda request: next(responses))
    assert await client.get_me() == {"id": "bot"}


def test_parse_update_fields():
    msg = parse_update({
        "event_name": "message.text.received",
        "message": {
            "message_id": "abc",
            "from": {"id": "u1", "display_name": "Nam", "is_bot": False},
            "chat": {"id": "g1", "chat_type": "GROUP"},
            "date": 1,
            "text": "/so",
        },
    })
    assert (msg.message_id, msg.chat_id, msg.sender_id, msg.sender_name, msg.text) == (
        "abc", "g1", "u1", "Nam", "/so",
    )
    assert msg.is_group


def test_parse_update_rejects_garbage():
    assert parse_update(None) is None
    assert parse_update({"message": {"text": "hi"}}) is None


def test_split_text_hard_splits_long_line():
    chunks = split_text("a" * 4500)
    assert [len(c) for c in chunks] == [2000, 2000, 500]
