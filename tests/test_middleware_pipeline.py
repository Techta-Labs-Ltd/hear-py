from __future__ import annotations

import pytest

from src.alexa.context import RequestContext
from src.alexa.runtime import AsyncSkill
from src.registry import RouteRegistry


def test_pipeline_declarations_preserve_behavioral_order():
    assert [item.__name__ for item in RouteRegistry.REQUEST_INTERCEPTORS] == [
        "LambdaDeadlineInterceptor",
        "IdentityInterceptor",
        "LoadPersistenceInterceptor",
        "DirectIntentPhraseInterceptor",
        "DialogValidationInterceptor",
        "ResolverInterceptor",
        "ConfirmationMiddleware",
    ]
    assert [item.__name__ for item in RouteRegistry.GATE_HANDLERS] == [
        "CanFulfillIntentHandler",
        "DialogValidationGateHandler",
        "AvailabilityDialogHandler",
        "FeedbackSkipGateHandler",
        "FeedbackGateHandler",
        "OnboardingGateHandler",
        "TownCaptureHandler",
        "SearchConfirmationGateHandler",
        "IntentDispatchGateHandler",
    ]
    assert [item.__name__ for item in RouteRegistry.RESPONSE_INTERCEPTORS] == [
        "SavePersistenceInterceptor"
    ]
    controllers = [item.__name__ for item in RouteRegistry.REQUEST_CONTROLLERS]
    assert controllers.index("BrowseNavigationHandler") < controllers.index("NextIntentHandler")
    assert controllers.index("BrowseNavigationHandler") < controllers.index("PreviousIntentHandler")


def test_runtime_rejects_mixed_interceptor_contracts():
    class SynchronousInterceptor:
        def process(self, _handler_input):
            return None

    skill = AsyncSkill()
    with pytest.raises(TypeError, match="must be async"):
        skill.add_global_request_interceptor(SynchronousInterceptor())
    with pytest.raises(TypeError, match="must be async"):
        skill.add_global_response_interceptor(SynchronousInterceptor())


@pytest.mark.asyncio
async def test_runtime_preserves_interceptor_dispatch_and_response_order():
    events = []

    class FirstInterceptor:
        async def process(self, handler_input):
            events.append("request:first")

    class SecondInterceptor:
        async def process(self, handler_input):
            events.append("request:second")

    class FirstHandler:
        def can_handle(self, handler_input):
            events.append("handler:first:match")
            return False

        def handle(self, handler_input):
            raise AssertionError

    class SecondHandler:
        def can_handle(self, handler_input):
            events.append("handler:second:match")
            return True

        async def handle(self, handler_input):
            events.append("handler:second:handle")
            return {"shouldEndSession": True}

    class FinalInterceptor:
        async def process(self, handler_input):
            events.append("response:final")

    skill = AsyncSkill()
    skill.add_global_request_interceptor(FirstInterceptor())
    skill.add_global_request_interceptor(SecondInterceptor())
    skill.add_request_handler(FirstHandler())
    skill.add_request_handler(SecondHandler())
    skill.add_global_response_interceptor(FinalInterceptor())
    response = await skill.invoke({"request": {"type": "LaunchRequest"}}, None)
    assert response["response"] == {"shouldEndSession": True}
    assert events == [
        "request:first",
        "request:second",
        "handler:first:match",
        "handler:second:match",
        "handler:second:handle",
        "response:final",
    ]


@pytest.mark.asyncio
async def test_runtime_binds_one_transient_request_context_without_state_copy():
    seen = []

    class Handler:
        def can_handle(self, _handler_input):
            return True

        def handle(self, handler_input):
            context = RequestContext.bind(handler_input)
            seen.extend([context, handler_input.request_context, context.request_attributes])
            context.request_attributes["marker"] = "request-only"
            return {"shouldEndSession": True}

    skill = AsyncSkill()
    skill.add_request_handler(Handler())
    await skill.invoke({"request": {"type": "LaunchRequest", "requestId": "request-1"}}, None)

    assert seen[0] is seen[1]
    assert seen[0].request_id == "request-1"
    assert seen[2]["marker"] == "request-only"


@pytest.mark.asyncio
async def test_runtime_skips_commit_interceptors_after_exception_handling():
    events = []

    class FailingInterceptor:
        async def process(self, handler_input):
            events.append("request")
            raise RuntimeError("failure")

    class ExceptionHandler:
        def can_handle(self, handler_input, exception):
            events.append("exception:match")
            return True

        def handle(self, handler_input, exception):
            events.append("exception:handle")
            return {"shouldEndSession": False}

    class ResponseInterceptor:
        async def process(self, handler_input):
            events.append("response")

    skill = AsyncSkill()
    skill.add_global_request_interceptor(FailingInterceptor())
    skill.add_exception_handler(ExceptionHandler())
    skill.add_global_response_interceptor(ResponseInterceptor())
    response = await skill.invoke({"request": {"type": "LaunchRequest"}}, None)
    assert response["response"] == {"shouldEndSession": False}
    assert events == ["request", "exception:match", "exception:handle"]
