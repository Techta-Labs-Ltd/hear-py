from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from main import LambdaApplication, NotificationLambdaApplication, OutboundLambdaApplication
from src.alexa.response import AlexaResponse
from src.alexa.runtime import AsyncSkill, AttrDict, AttributesManager, HandlerInput, ResponseBuilder
from src.database.persistence import MemoryPersistenceAdapter
from src.middleware.persistence import LoadPersistenceInterceptor, SavePersistenceInterceptor
from src.models.user import User
from src.services.events import OutboundEventService
from src.utils.deadline import RequestDeadline
from src.utils.events import EventUtils


class DurableAction:
    def can_handle(self, handler_input):
        return True

    async def handle(self, handler_input):
        User.update(handler_input, {"playCount": 1, "_requiresReliableSave": True})
        return (
            handler_input.response_builder.speak("Saved successfully")
            .add_directive({"type": "AudioPlayer.Play", "audioItem": {"stream": {"token": "new"}}})
            .response
        )


class Recovery:
    def can_handle(self, handler_input, exception):
        return True

    async def handle(self, handler_input, exception):
        return handler_input.response_builder.speak("Unable to save").response


@pytest.mark.asyncio
async def test_failed_essential_commit_replaces_success_and_discards_prepared_directives():
    adapter = SimpleNamespace(
        get_attributes=AsyncMock(return_value={}),
        save_attributes=AsyncMock(side_effect=RuntimeError("write failed")),
    )
    skill = AsyncSkill(persistence_adapter=adapter)
    skill.add_global_request_interceptor(LoadPersistenceInterceptor())
    skill.add_request_handler(DurableAction())
    skill.add_global_response_interceptor(SavePersistenceInterceptor())
    skill.add_exception_handler(Recovery())
    response = await skill.invoke({"request": {"type": "IntentRequest"}}, None)
    assert "Unable to save" in response["response"]["outputSpeech"]["ssml"]
    assert "directives" not in response["response"]
    assert adapter.save_attributes.await_count == 1


@pytest.mark.asyncio
async def test_unavailable_load_prevents_a_durable_success():
    adapter = SimpleNamespace(
        get_attributes=AsyncMock(side_effect=RuntimeError("read failed")),
        save_attributes=AsyncMock(),
    )
    skill = AsyncSkill(persistence_adapter=adapter)
    skill.add_global_request_interceptor(LoadPersistenceInterceptor())
    skill.add_request_handler(DurableAction())
    skill.add_global_response_interceptor(SavePersistenceInterceptor())
    skill.add_exception_handler(Recovery())
    response = await skill.invoke({"request": {"type": "IntentRequest"}}, None)
    assert "Unable to save" in response["response"]["outputSpeech"]["ssml"]
    adapter.save_attributes.assert_not_awaited()


@pytest.mark.asyncio
async def test_action_failure_does_not_run_commit_interceptors():
    class PartialAction(DurableAction):
        async def handle(self, handler_input):
            await super().handle(handler_input)
            raise RuntimeError("partial action")

    save = AsyncMock()
    skill = AsyncSkill()
    skill.add_request_handler(PartialAction())
    skill.add_global_response_interceptor(SimpleNamespace(process=save))
    skill.add_exception_handler(Recovery())
    await skill.invoke({"request": {"type": "IntentRequest"}}, None)
    save.assert_not_awaited()


@pytest.mark.parametrize(
    "request_type,allowed",
    [
        ("AudioPlayer.PlaybackStarted", {"AudioPlayer.Stop", "AudioPlayer.ClearQueue"}),
        ("AudioPlayer.PlaybackFinished", {"AudioPlayer.Stop", "AudioPlayer.ClearQueue"}),
        (
            "AudioPlayer.PlaybackNearlyFinished",
            {"AudioPlayer.Play", "AudioPlayer.Stop", "AudioPlayer.ClearQueue"},
        ),
        (
            "AudioPlayer.PlaybackFailed",
            {"AudioPlayer.Play", "AudioPlayer.Stop", "AudioPlayer.ClearQueue"},
        ),
        ("AudioPlayer.PlaybackStopped", set()),
        ("SessionEndedRequest", set()),
        ("System.ExceptionEncountered", set()),
    ],
)
@pytest.mark.asyncio
async def test_runtime_enforces_callback_response_contracts(request_type, allowed):
    class InvalidCallback(DurableAction):
        async def handle(self, handler_input):
            return {
                "outputSpeech": {},
                "card": {},
                "reprompt": {},
                "shouldEndSession": True,
                "directives": [
                    {"type": name}
                    for name in [
                        "AudioPlayer.Play",
                        "AudioPlayer.Stop",
                        "AudioPlayer.ClearQueue",
                        "Dialog.ElicitSlot",
                    ]
                ],
            }

    skill = AsyncSkill()
    skill.add_request_handler(InvalidCallback())
    response = await skill.invoke({"request": {"type": request_type}}, None)
    assert set(response["response"]).issubset({"directives"})
    assert {
        directive["type"] for directive in response["response"].get("directives", [])
    } == allowed
    assert "sessionAttributes" not in response


@pytest.mark.parametrize(
    "request_type",
    [
        "AudioPlayer.PlaybackNearlyFinished",
        "AudioPlayer.PlaybackStarted",
        "SessionEndedRequest",
        "System.ExceptionEncountered",
    ],
)
def test_outer_fallback_never_speaks_for_callbacks(monkeypatch, request_type):
    application = LambdaApplication()
    monkeypatch.setattr(
        application, "skill", lambda: (_ for _ in ()).throw(RuntimeError("build failed"))
    )
    response = application.handle(
        {"context": {"System": {"user": {}}}, "request": {"type": request_type}}, None
    )
    assert response == {"version": "1.0", "response": {}}


@pytest.mark.parametrize(
    "application_type", [OutboundLambdaApplication, NotificationLambdaApplication]
)
def test_worker_boundary_never_acknowledges_records_without_identifiers(application_type):
    application = application_type()
    application._dependencies = SimpleNamespace(
        events=SimpleNamespace(consume=AsyncMock(side_effect=ValueError("missing messageId"))),
        notification_delivery=SimpleNamespace(
            consume=AsyncMock(side_effect=ValueError("missing messageId"))
        ),
    )
    with pytest.raises(ValueError, match="messageId"):
        application.handle({"Records": [{"body": "{}"}]}, None)


def test_intent_last_resort_retains_spoken_recovery():
    assert AlexaResponse.last_resort_skill_response("IntentRequest")["response"]["outputSpeech"]


@pytest.mark.asyncio
async def test_successful_commit_updates_versions_and_clears_dirty_fields():
    envelope = AttrDict(
        {
            "request": {"type": "IntentRequest"},
            "context": {"System": {"user": {"userId": "listener"}}},
        }
    )
    adapter = MemoryPersistenceAdapter()
    handler_input = HandlerInput(
        envelope, AttributesManager(envelope, adapter), None, ResponseBuilder()
    )
    await LoadPersistenceInterceptor().process(handler_input)
    User.update(handler_input, {"playCount": 3, "_requiresReliableSave": True})
    interceptor = SavePersistenceInterceptor()
    await interceptor.process(handler_input)
    assert not User.is_dirty(handler_input)
    assert User.changed_fields(handler_input) == ()
    assert handler_input.attributes_manager.request_attributes["_persistenceVersions"]["CORE"] == 1
    await interceptor.process(handler_input)
    assert (await adapter.get_attributes(envelope))["_persistenceVersions"]["CORE"] == 1


@pytest.mark.asyncio
async def test_failed_commit_keeps_dirty_state_and_versions():
    envelope = AttrDict({"request": {"type": "IntentRequest"}})
    adapter = SimpleNamespace(
        get_attributes=AsyncMock(return_value={"_persistenceVersions": {"CORE": 4}}),
        save_attributes=AsyncMock(side_effect=RuntimeError("unavailable")),
    )
    handler_input = HandlerInput(
        envelope, AttributesManager(envelope, adapter), None, ResponseBuilder()
    )
    await LoadPersistenceInterceptor().process(handler_input)
    User.update(handler_input, {"playCount": 3, "_requiresReliableSave": True})
    with pytest.raises(RuntimeError, match="Essential persistence"):
        await SavePersistenceInterceptor().process(handler_input)
    assert User.is_dirty(handler_input)
    assert User.changed_fields(handler_input) == ("playCount",)
    assert handler_input.attributes_manager.request_attributes["_persistenceVersions"]["CORE"] == 4


@pytest.mark.asyncio
async def test_expired_worker_budget_leaves_all_records_retryable():
    webhook = SimpleNamespace(send=AsyncMock(return_value=True))
    body = EventUtils.envelope(
        "feedback.given", {"alexaUserId": "listener", "clientEventId": "event"}
    )
    records = [{"messageId": "one", "body": json.dumps(body)}]
    result = await OutboundEventService(webhook=webhook).consume(
        records, deadline=RequestDeadline(0)
    )
    assert result == {"batchItemFailures": [{"itemIdentifier": "one"}]}
    webhook.send.assert_not_awaited()
