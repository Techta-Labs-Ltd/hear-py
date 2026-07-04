from __future__ import annotations
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


@pytest.fixture
def mock_handler_input():
    hi = MagicMock()
    hi.request_envelope = {
        "version": "1.0",
        "session": {
            "new": True,
            "sessionId": "amzn1.echo-api.session.test",
            "user": {"userId": "amzn1.ask.account.TEST"},
            "application": {"applicationId": "amzn1.ask.skill.test"},
        },
        "context": {
            "System": {
                "application": {"applicationId": "amzn1.ask.skill.test"},
                "user": {"userId": "amzn1.ask.account.TEST", "permissions": {"scopes": {}}},
                "device": {"deviceId": "amzn1.ask.device.TEST", "supportedInterfaces": {}},
                "apiEndpoint": "https://api.amazonalexa.com",
                "apiAccessToken": "test-token",
            },
            "AudioPlayer": {"playerActivity": "IDLE"},
        },
        "request": {
            "type": "LaunchRequest",
            "requestId": "amzn1.echo-api.request.test",
            "timestamp": "2024-01-01T00:00:00Z",
            "locale": "en-GB",
        },
    }

    attrs = {"_store": None, "_dirty": False}
    hi.attributes_manager = MagicMock()
    hi.attributes_manager.request_attributes = attrs
    hi.attributes_manager.get_request_attributes = lambda: attrs
    hi.attributes_manager.set_request_attributes = lambda a: setattr(hi.attributes_manager, "request_attributes", a)
    hi.attributes_manager.persistent_attributes = {}
    hi.attributes_manager.get_persistent_attributes = AsyncMock(return_value={})
    hi.attributes_manager.save_persistent_attributes = AsyncMock()
    hi.attributes_manager.set_persistent_attributes = lambda v: setattr(hi.attributes_manager, "persistent_attributes", v)
    hi.response_builder = MagicMock()
    return hi


@pytest.fixture
def mock_intent_request(mock_handler_input):
    mock_handler_input.request_envelope["request"] = {
        "type": "IntentRequest",
        "requestId": "amzn1.echo-api.request.intent-test",
        "timestamp": "2024-01-01T00:00:00Z",
        "locale": "en-GB",
        "intent": {"name": "PlayContentIntent", "slots": {}},
    }
    return mock_handler_input


@pytest.fixture
def mock_api_response():
    def _response(data=None, results=None, total_hits=0, status=200):
        return {
            "status": status,
            "data": data or {
                "results": results or [],
                "total_hits": total_hits or len(results or []),
                "total_pages": 1,
                "page": 0,
            },
        }
    return _response
