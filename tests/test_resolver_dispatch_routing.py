from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.alexa.runtime import AttrDict, AttributesManager, HandlerInput, ResponseBuilder
from src.container import ApplicationContainer
from src.controllers.intent_dispatch import IntentDispatchGateHandler
from src.middleware.resolver import ResolverInterceptor
from src.models.dialog import DialogStateManager
from src.models.intent_dispatch import IntentDispatcher
from src.models.resolver_runner import ResolverWorkflowRunner
from src.models.user import User


@pytest.fixture
def base_envelope():
    return AttrDict(
        {
            "version": "1.0",
            "context": {"System": {"user": {"userId": "test-alexa-user-123"}}},
            "request": {
                "type": "IntentRequest",
                "locale": "en-GB",
                "intent": {
                    "name": "PlayContentIntent",
                    "slots": {"topic": {"name": "topic", "value": "play pendle voice"}},
                },
            },
        }
    )


@pytest.fixture
def mock_handler_input(base_envelope):
    attributes = AttributesManager(base_envelope)
    attributes.request_attributes = {
        "_store": {
            "onboardingComplete": True,
            "listenerId": "test-listener-456",
        },
        "_dirty": False,
    }
    return HandlerInput(base_envelope, attributes, None, ResponseBuilder())


def test_ambiguity_response_activates_dialog_and_injects_dynamic_entities(mock_handler_input):
    candidates = [
        {"id": "feed-1", "name": "Pendle Voice News", "entityType": "publication"},
        {"id": "feed-2", "name": "Pendle Voice Magazine", "entityType": "publication"},
    ]
    nlp_data = {
        "status": "ambiguous",
        "intent": "search",
        "ambiguities": [{"phrase": "pendle voice", "candidates": candidates}],
        "slots": {},
    }
    mock_handler_input.attributes_manager.request_attributes["_nlp"] = nlp_data

    container = ApplicationContainer()
    dispatcher = IntentDispatcher(deps=container)
    assert dispatcher.can_dispatch(mock_handler_input) is True

    gate = IntentDispatchGateHandler(deps=container)
    assert gate.can_handle(mock_handler_input) is True

    response = gate.handle(mock_handler_input)
    assert "outputSpeech" in response
    speech = response["outputSpeech"]["ssml"]
    assert "Pendle Voice" in speech
    assert "News" in speech
    assert "Magazine" in speech

    store = User.snapshot(mock_handler_input)
    assert store.get("pendingAmbiguity") is not None
    assert store["pendingAmbiguity"]["phrase"] == "pendle voice"
    assert len(store["pendingAmbiguity"]["candidates"]) == 2

    active_dialog = DialogStateManager.get_active(mock_handler_input)
    assert active_dialog is not None
    assert active_dialog.get("type") == "ambiguity"

    directives = response.get("directives") or []
    assert len(directives) == 1
    assert directives[0]["type"] == "Dialog.UpdateDynamicEntities"


@pytest.mark.asyncio
async def test_location_intent_dispatches_to_availability_local(mock_handler_input):
    nlp_data = {
        "status": "resolved",
        "intent": "location",
        "slots": {"city": "Leeds"},
    }
    mock_handler_input.attributes_manager.request_attributes["_nlp"] = nlp_data

    container = ApplicationContainer()
    container.availability = AsyncMock()
    container.availability.begin_local = AsyncMock(return_value={"outputSpeech": "local"})

    dispatcher = IntentDispatcher(deps=container)
    assert dispatcher.can_dispatch(mock_handler_input) is True

    result = dispatcher.dispatch(mock_handler_input)
    response = await result
    assert response == {"outputSpeech": "local"}
    container.availability.begin_local.assert_called_once_with(mock_handler_input, nlp_data)


def test_availability_preemption_on_new_search_query(mock_handler_input):
    DialogStateManager.activate(
        mock_handler_input,
        "availability",
        context={
            "kind": "source",
            "candidates": [{"id": "item-1", "name": "York News"}],
        },
    )
    active = DialogStateManager.get_active(mock_handler_input)
    assert active is not None
    assert active.get("type") == "availability"

    context = ResolverWorkflowRunner._request(mock_handler_input)
    assert context is not None
    assert context["alexa_intent"] == "PlayContentIntent"

    cleared = DialogStateManager.get_active(mock_handler_input)
    assert cleared is None


def test_availability_dialog_retains_ordinal_selection(base_envelope):
    base_envelope.request.intent.name = "PlayContentIntent"
    base_envelope.request.intent.slots = {"topic": {"name": "topic", "value": "the first one"}}
    attributes = AttributesManager(base_envelope)
    attributes.request_attributes = {
        "_store": {"onboardingComplete": True},
        "_dirty": False,
    }
    handler_input = HandlerInput(base_envelope, attributes, None, ResponseBuilder())
    DialogStateManager.activate(
        handler_input,
        "availability",
        context={
            "kind": "source",
            "candidates": [{"id": "item-1", "name": "York News"}],
        },
    )

    context = ResolverWorkflowRunner._request(handler_input)
    assert context is None

    active = DialogStateManager.get_active(handler_input)
    assert active is not None
    assert active.get("type") == "availability"


def test_resolver_workflow_runner_carries_alexa_user_id_and_listener_id():
    runner = ResolverWorkflowRunner(
        alexa_user_id="custom-alexa-user",
        listener_id="custom-listener-id",
    )
    assert runner._alexa_user_id == "custom-alexa-user"
    assert runner._listener_id == "custom-listener-id"


@pytest.mark.asyncio
async def test_resolver_interceptor_injects_user_and_listener_id(mock_handler_input, monkeypatch):
    captured = {}

    def capture_init(self, *, alexa_user_id=None, listener_id=None, deps=None):
        captured["alexa_user_id"] = alexa_user_id
        captured["listener_id"] = listener_id
        self._alexa_user_id = alexa_user_id
        self._listener_id = listener_id
        self._deps = deps

    monkeypatch.setattr(ResolverWorkflowRunner, "__init__", capture_init)
    monkeypatch.setattr(ResolverWorkflowRunner, "apply", AsyncMock())

    interceptor = ResolverInterceptor(deps=ApplicationContainer())
    await interceptor.process(mock_handler_input)

    assert captured["alexa_user_id"] == "test-alexa-user-123"
    assert captured["listener_id"] == "test-listener-456"
