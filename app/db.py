"""Kết nối database."""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from sqlalchemy import create_engine, delete, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, ProcessedMessage, utcnow

PROCESSED_RETENTION = timedelta(days=30)


def make_engine(database_url: str) -> Engine:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        return create_engine(url, pool_pre_ping=True)

    in_memory = url.database in (None, "", ":memory:")
    kwargs: dict = {"connect_args": {"check_same_thread": False, "timeout": 15}}
    if in_memory:
        # Mọi luồng dùng chung một kết nối, nếu không mỗi luồng sẽ thấy một DB rỗng khác nhau.
        kwargs["poolclass"] = StaticPool
    else:
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, **kwargs)

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        if not in_memory:
            cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def prune_processed(session_factory: sessionmaker[Session]) -> None:
    """Xóa dấu vết tin nhắn cũ để bảng chống trùng không phình mãi."""
    with session_factory() as session:
        session.execute(
            delete(ProcessedMessage).where(ProcessedMessage.created_at < utcnow() - PROCESSED_RETENTION)
        )
        session.commit()
