from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings
from app.main import create_app
from tests.test_handlers import FakeMessenger, update

SECRET = "super-secret-123"


def make_client(messenger):
    settings = Settings(
        zalo_bot_token=SecretStr("123:abc"),
        webhook_secret=SecretStr(SECRET),
        database_url="sqlite://",
    )
    return TestClient(create_app(settings, messenger))


def test_webhook_rejects_wrong_secret():
    with make_client(FakeMessenger()) as client:
        response = client.post("/webhook", json=update("/help"), headers={"X-Bot-Api-Secret-Token": "nope"})
        assert response.status_code == 401
        assert client.post("/webhook", json=update("/help")).status_code == 401


def test_webhook_handles_update():
    messenger = FakeMessenger()
    with make_client(messenger) as client:
        response = client.post(
            "/webhook", json=update("/help"), headers={"X-Bot-Api-Secret-Token": SECRET}
        )
        assert response.status_code == 200
        assert client.get("/healthz").json() == {"ok": True}
    assert "Bot chia tiền nhóm" in messenger.sent[-1][1]


def test_webhook_rejects_bad_json():
    with make_client(FakeMessenger()) as client:
        response = client.post(
            "/webhook", content=b"{not json", headers={"X-Bot-Api-Secret-Token": SECRET}
        )
        assert response.status_code == 400
