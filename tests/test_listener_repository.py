from __future__ import annotations

import pytest

from src.alexa.runtime import AttrDict, AttributesManager, HandlerInput, ResponseBuilder
from src.models.listener import Listener
from src.models.user import User


def _handler_input() -> HandlerInput:
    envelope = AttrDict({"request": {"type": "LaunchRequest"}})
    attributes = AttributesManager(envelope)
    attributes.request_attributes = {
        "_store": {"userName": None, "playCount": 4},
        "_dirty": False,
    }
    return HandlerInput(envelope, attributes, None, ResponseBuilder())


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
