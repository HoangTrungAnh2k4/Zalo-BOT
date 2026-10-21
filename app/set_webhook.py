"""Đăng ký / xem / gỡ webhook với Zalo.

    python -m app.set_webhook           # đăng ký WEBHOOK_URL + WEBHOOK_SECRET trong .env
    python -m app.set_webhook --info    # xem webhook hiện tại
    python -m app.set_webhook --delete  # gỡ webhook (để dùng lại polling)
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from app.config import configure_logging, get_settings
from app.zalo_client import ZaloApiError, ZaloClient


async def run(action: str) -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    client = ZaloClient(settings.zalo_bot_token.get_secret_value(), settings.zalo_api_base)
    try:
        if action == "info":
            print(await client.get_webhook_info())
        elif action == "delete":
            await client.delete_webhook()
            print("Đã gỡ webhook.")
        else:
            url = settings.webhook_url
            secret = settings.webhook_secret.get_secret_value()
            if not url.startswith("https://"):
                print("WEBHOOK_URL phải là https://...", file=sys.stderr)
                return 1
            if not 8 <= len(secret) <= 256:
                print("WEBHOOK_SECRET phải dài 8-256 ký tự.", file=sys.stderr)
                return 1
            await client.set_webhook(url, secret)
            print(f"Đã đăng ký webhook: {url}")
        return 0
    except ZaloApiError as err:
        print(f"Lỗi Zalo API: {err}", file=sys.stderr)
        return 1
    finally:
        await client.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--info", action="store_const", const="info", dest="action")
    group.add_argument("--delete", action="store_const", const="delete", dest="action")
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args.action or "set")))


if __name__ == "__main__":
    main()
