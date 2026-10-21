"""Gọi Zalo Bot API (https://bot.zaloplatforms.com/docs).

Toàn bộ chi tiết về API nằm ở file này: nếu Zalo đổi URL hay tên trường,
chỉ cần sửa ở đây.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import DEFAULT_API_BASE

log = logging.getLogger(__name__)

MAX_TEXT_LENGTH = 2000  # giới hạn độ dài một tin nhắn của Zalo
POLLING_TIMEOUT_CODE = 408  # getUpdates hết thời gian chờ mà không có tin mới
RETRY_STATUS = {429, 500, 502, 503, 504}


class ZaloApiError(Exception):
    def __init__(self, message: str, error_code: int | None = None):
        super().__init__(message)
        self.error_code = error_code


@dataclass(frozen=True)
class IncomingMessage:
    message_id: str
    chat_id: str
    chat_type: str  # "PRIVATE" | "GROUP"
    sender_id: str
    sender_name: str
    text: str
    from_bot: bool = False

    @property
    def is_group(self) -> bool:
        return self.chat_type.upper() == "GROUP"


def _as_str(value: Any) -> str:
    return "" if value is None else str(value).strip()


def parse_update(raw: Any) -> IncomingMessage | None:
    """Đọc update từ webhook/getUpdates; trả None nếu không phải tin nhắn dùng được."""
    if not isinstance(raw, dict):
        return None
    if raw.get("ok") is True and isinstance(raw.get("result"), dict):
        raw = raw["result"]
    message = raw.get("message")
    if not isinstance(message, dict):
        return None
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    sender = message.get("from") if isinstance(message.get("from"), dict) else {}

    message_id = _as_str(message.get("message_id"))
    chat_id = _as_str(chat.get("id"))
    if not message_id or not chat_id:
        return None
    text = message.get("text")
    return IncomingMessage(
        message_id=message_id,
        chat_id=chat_id,
        chat_type=_as_str(chat.get("chat_type")) or "PRIVATE",
        sender_id=_as_str(sender.get("id")) or chat_id,
        sender_name=_as_str(sender.get("display_name") or sender.get("name")),
        text=text if isinstance(text, str) else "",
        from_bot=bool(sender.get("is_bot")),
    )


def split_text(text: str, limit: int = MAX_TEXT_LENGTH) -> list[str]:
    """Cắt tin dài thành nhiều tin, ưu tiên cắt ở chỗ xuống dòng."""
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks or [""]


class ZaloClient:
    def __init__(
        self,
        token: str,
        base_url: str = DEFAULT_API_BASE,
        *,
        http: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
        max_attempts: int = 3,
    ):
        if not token:
            raise ValueError("Thiếu ZALO_BOT_TOKEN")
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._http = http or httpx.AsyncClient(timeout=timeout)
        self._owns_http = http is None
        self._timeout = timeout
        self._max_attempts = max_attempts

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def call(
        self,
        method: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
        attempts: int | None = None,
    ) -> Any:
        # URL chứa token: không bao giờ đưa URL vào log hay thông báo lỗi.
        url = f"{self._base_url}/bot{self._token}/{method}"
        attempts = attempts or self._max_attempts
        for attempt in range(1, attempts + 1):
            try:
                response = await self._http.post(
                    url, json=payload or {}, timeout=timeout or self._timeout
                )
            except httpx.TransportError as exc:
                if attempt >= attempts:
                    raise ZaloApiError(f"{method}: lỗi mạng ({type(exc).__name__})") from None
                await asyncio.sleep(2 ** (attempt - 1))
                continue

            if response.status_code in RETRY_STATUS and attempt < attempts:
                delay = _retry_after(response) or 2 ** (attempt - 1)
                log.warning("%s: HTTP %s, thử lại sau %ss", method, response.status_code, delay)
                await asyncio.sleep(delay)
                continue

            try:
                data = response.json()
            except ValueError:
                raise ZaloApiError(
                    f"{method}: phản hồi không phải JSON (HTTP {response.status_code})",
                    response.status_code,
                ) from None
            if not isinstance(data, dict) or not data.get("ok"):
                data = data if isinstance(data, dict) else {}
                raise ZaloApiError(
                    f"{method}: {data.get('description') or 'lỗi không rõ'}",
                    data.get("error_code") or response.status_code,
                )
            return data.get("result")
        raise AssertionError("unreachable")

    async def get_me(self) -> dict:
        return await self.call("getMe")

    async def get_updates(self, timeout: int = 30) -> dict | None:
        """Long polling. Zalo trả về MỘT update mỗi lần (không phải mảng như Telegram)."""
        try:
            return await self.call(
                "getUpdates", {"timeout": str(timeout)}, timeout=timeout + 5, attempts=1
            )
        except ZaloApiError as err:
            if err.error_code == POLLING_TIMEOUT_CODE:
                return None
            raise

    async def send_message(self, chat_id: str, text: str) -> None:
        for chunk in split_text(text):
            await self.call("sendMessage", {"chat_id": chat_id, "text": chunk})

    async def send_photo(self, chat_id: str, photo_url: str, caption: str = "") -> None:
        payload = {"chat_id": chat_id, "photo": photo_url}
        if caption:
            payload["caption"] = caption[:MAX_TEXT_LENGTH]
        # Zalo tự tải ảnh từ URL trước khi trả lời nên cần chờ lâu hơn.
        await self.call("sendPhoto", payload, timeout=90)

    async def set_webhook(self, url: str, secret_token: str) -> Any:
        return await self.call("setWebhook", {"url": url, "secret_token": secret_token})

    async def delete_webhook(self) -> Any:
        return await self.call("deleteWebhook")

    async def get_webhook_info(self) -> Any:
        return await self.call("getWebhookInfo")


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return min(float(response.headers.get("retry-after", "")), 30.0)
    except ValueError:
        return None
