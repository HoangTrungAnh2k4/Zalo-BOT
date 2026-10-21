import pytest

from app.db import init_db, make_engine, make_session_factory
from app.services.ledger import LedgerService


@pytest.fixture
def session_factory():
    engine = make_engine("sqlite://")
    init_db(engine)
    yield make_session_factory(engine)
    engine.dispose()


@pytest.fixture
def session(session_factory):
    with session_factory() as session:
        yield session


@pytest.fixture
def service(session):
    return LedgerService(session)
