"""Chạy bot bằng long polling (tiện khi dev, không cần URL công khai).

    python -m app.polling
"""
from __future__ import annotations

import asyncio
import logging

from app.config import Settings, configure_logging, get_settings
from app.db import init_db, make_engine, make_session_factory, prune_processed
from app.handlers import Bot
from app.zalo_client import ZaloApiError, ZaloClient

log = logging.getLogger(__name__)


async def run(settings: Settings | None = None) -> None:
    config = settings or get_settings()
    configure_logging(config.log_level)
    if not config.zalo_bot_token.get_secret_value():
        raise SystemExit("Thiếu ZALO_BOT_TOKEN: copy .env.example thành .env rồi điền token.")

    engine = make_engine(config.database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)
    prune_processed(session_factory)

    client = ZaloClient(config.zalo_bot_token.get_secret_value(), config.zalo_api_base)
    bot = Bot(client, session_factory)
    try:
        try:
            me = await client.get_me()
        except ZaloApiError as err:
            raise SystemExit(f"Không kết nối được Zalo ({err}). Kiểm tra ZALO_BOT_TOKEN và mạng.") from None
        log.info("Đã kết nối bot %s", (me or {}).get("account_name", "?"))
        # Polling và webhook không chạy cùng lúc được, nên gỡ webhook (nếu có).
        try:
            await client.delete_webhook()
        except ZaloApiError as err:
            log.debug("deleteWebhook: %s", err)

        log.info("Đang chờ tin nhắn... (Ctrl+C để dừng)")
        failures = 0
        while True:
            try:
                update = await client.get_updates(config.poll_timeout)
            except ZaloApiError as err:
                failures += 1
                delay = min(60, 2 ** min(failures, 6))
                log.warning("getUpdates lỗi: %s, thử lại sau %ss", err, delay)
                await asyncio.sleep(delay)
                continue
            failures = 0
            if update:
                await bot.handle_update(update)
    finally:
        await client.aclose()
        engine.dispose()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("Đã dừng bot.")


if __name__ == "__main__":
    main()
