from __future__ import annotations

import socket
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest


def _is_loopback(address) -> bool:
    return isinstance(address, tuple) and bool(address) and address[0] in {
        "127.0.0.1",
        "::1",
    }


def _remote_connection_guard(connect, message: str):
    def guarded(socket_instance, address, *args, **kwargs):
        if _is_loopback(address):
            return connect(socket_instance, address, *args, **kwargs)
        raise AssertionError(message)

    return guarded


def pytest_configure(config):
    guard = pytest.MonkeyPatch()
    connect = socket.socket.connect
    connect_ex = socket.socket.connect_ex

    def reject_network(*args, **kwargs):
        raise AssertionError(
            "Live network access is forbidden during unit-test collection and execution"
        )

    guard.setattr(socket, "getaddrinfo", reject_network)
    guard.setattr(
        socket.socket,
        "connect",
        _remote_connection_guard(connect, "Live network access is forbidden during unit-test collection and execution"),
    )
    guard.setattr(
        socket.socket,
        "connect_ex",
        _remote_connection_guard(connect_ex, "Live network access is forbidden during unit-test collection and execution"),
    )
    config._hear_network_guard = guard


def pytest_unconfigure(config):
    guard = getattr(config, "_hear_network_guard", None)
    if guard is not None:
        guard.undo()


@pytest.fixture(autouse=True)
def prevent_live_network_calls(monkeypatch):
    attempted = []
    connect = socket.socket.connect
    connect_ex = socket.socket.connect_ex

    def reject_network(*args, **kwargs):
        attempted.append(True)
        raise AssertionError("Unit tests must inject a transport or service stub")

    monkeypatch.setattr(socket, "getaddrinfo", reject_network)
    monkeypatch.setattr(
        socket.socket,
        "connect",
        _remote_connection_guard(
            connect, "Unit tests must inject a transport or service stub"
        ),
    )
    monkeypatch.setattr(
        socket.socket,
        "connect_ex",
        _remote_connection_guard(
            connect_ex, "Unit tests must inject a transport or service stub"
        ),
    )
    yield
    assert not attempted, "Unit test attempted live network access; inject a test stub"


@pytest.fixture(autouse=True)
def offline_http_dependencies(monkeypatch):
    original = httpx.AsyncClient

    def unavailable(request):
        return httpx.Response(503, json={"error": "test_dependency_unavailable"})

    def client(*args, **kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(unavailable))
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)


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
                "user": {
                    "userId": "amzn1.ask.account.TEST",
                    "permissions": {"scopes": {}},
                },
                "device": {
                    "deviceId": "amzn1.ask.device.TEST",
                    "supportedInterfaces": {},
                },
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
    hi.attributes_manager.set_request_attributes = lambda a: setattr(
        hi.attributes_manager, "request_attributes", a
    )
    hi.attributes_manager.persistent_attributes = {}
    hi.attributes_manager.get_persistent_attributes = AsyncMock(return_value={})
    hi.attributes_manager.save_persistent_attributes = AsyncMock()
    hi.attributes_manager.set_persistent_attributes = lambda v: setattr(
        hi.attributes_manager, "persistent_attributes", v
    )
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
            "data": data
            or {
                "results": results or [],
                "total_hits": total_hits or len(results or []),
                "total_pages": 1,
                "page": 0,
            },
        }

    return _response
