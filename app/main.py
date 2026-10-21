"""Chạy bot ở chế độ webhook: uvicorn app.main:app"""
from __future__ import annotations

import hmac
import json
import logging
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request

from app.config import Settings, configure_logging, get_settings
from app.db import init_db, make_engine, make_session_factory, prune_processed
from app.handlers import Bot, Messenger
from app.zalo_client import ZaloClient

log = logging.getLogger(__name__)

MAX_BODY_BYTES = 1_000_000
SECRET_HEADER = "X-Bot-Api-Secret-Token"


def create_app(settings: Settings | None = None, messenger: Messenger | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        config = settings or get_settings()
        configure_logging(config.log_level)
        secret = config.webhook_secret.get_secret_value()
        if not 8 <= len(secret) <= 256:
            raise RuntimeError("WEBHOOK_SECRET phải dài 8-256 ký tự (Zalo yêu cầu)")

        engine = make_engine(config.database_url)
        init_db(engine)
        session_factory = make_session_factory(engine)
        prune_processed(session_factory)

        client = None
        if messenger is None:
            client = ZaloClient(config.zalo_bot_token.get_secret_value(), config.zalo_api_base)
        app.state.bot = Bot(messenger or client, session_factory)
        app.state.secret = secret.encode()
        log.info("Bot chia tiền đang chạy ở chế độ webhook")
        try:
            yield
        finally:
            if client is not None:
                await client.aclose()
            engine.dispose()

    app = FastAPI(title="Zalo bot chia tiền", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    @app.post("/webhook")
    async def webhook(request: Request, background: BackgroundTasks):
        token = request.headers.get(SECRET_HEADER, "").encode()
        if not hmac.compare_digest(token, request.app.state.secret):
            raise HTTPException(status_code=401, detail="invalid secret token")
        body = await request.body()
        if len(body) > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="payload too large")
        try:
            payload = json.loads(body)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid json") from None
        # Trả 200 ngay để Zalo không chờ; xử lý và trả lời ở background.
        background.add_task(request.app.state.bot.handle_update, payload)
        return {"ok": True}

    return app


app = create_app()
