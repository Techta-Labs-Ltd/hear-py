import pytest

from src.services import proactive_notifications


class _Response:
    status_code = 202

    def raise_for_status(self):
        return None


class _Client:
    request = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def aclose(self):
        return None

    async def post(self, url, **kwargs):
        _Client.request = {"url": url, **kwargs}
        return _Response()


@pytest.mark.asyncio
async def test_proactive_event_is_unicast_and_idempotent(monkeypatch):
    async def token(_client=None):
        return "lwa-token"

    monkeypatch.setattr(proactive_notifications, "_access_token", token)
    monkeypatch.setattr(proactive_notifications.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(proactive_notifications.settings, "ALEXA_PROACTIVE_STAGE", "development")

    delivered = await proactive_notifications.send_proactive_notification({
        "notificationId": "event-1:user-1",
        "alexaUserId": "user-1",
        "creatorName": "York Talking News",
    })

    assert delivered is True
    assert _Client.request["headers"]["Authorization"] == "Bearer lwa-token"
    body = _Client.request["json"]
    assert body["referenceId"] == "event-1~user-1"
    assert body["event"]["name"] == "AMAZON.MessageAlert.Activated"
    assert body["relevantAudience"] == {
        "type": "Unicast",
        "payload": {"user": "user-1"},
    }
