from __future__ import annotations

from pathlib import Path

import pytest

from src.alexa.runtime import AttrDict, AttributesManager, HandlerInput, ResponseBuilder
from src.models.user import User
from src.services.listener_repository import Listener


def _handler_input() -> HandlerInput:
    envelope = AttrDict({"request": {"type": "LaunchRequest"}})
    attributes = AttributesManager(envelope)
    attributes.request_attributes = {
        "_store": {"userName": None, "playCount": 4},
        "_dirty": False,
    }
    return HandlerInput(envelope, attributes, None, ResponseBuilder())


def test_listener_identity_model_has_no_request_or_state_gateway_dependency():
    source = (Path(__file__).parents[1] / "src/models/listener.py").read_text(
        encoding="utf-8"
    )
    assert "src.alexa" not in source
    assert "handler_input" not in source
    assert "src.models.user" not in source


def test_listener_repository_owns_profile_updates():
    handler_input = _handler_input()
    repository = Listener(User())
    result = repository.apply_profile(
        handler_input,
        {"fullName": "Ada Lovelace", "userName": "Ada Lovelace", "listenerProfileResolvedAt": 123},
    )
    assert result["fullName"] == "Ada Lovelace"
    assert result["userName"] == "Ada Lovelace"
    assert result["playCount"] == 4
    assert handler_input.attributes_manager.request_attributes["_dirty"] is True


def test_listener_repository_rejects_unowned_state():
    repository = Listener(User())
    with pytest.raises(ValueError, match="playCount"):
        repository.apply_profile(_handler_input(), {"playCount": 5})
