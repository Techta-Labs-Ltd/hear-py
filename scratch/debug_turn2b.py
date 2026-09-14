import sys
sys.path.insert(0, "c:/Users/USER/Downloads/hear-py")

from src.alexa.runtime import AttrDict, AttributesManager, HandlerInput, ResponseBuilder
from src.container import ApplicationContainer
from src.constants.state import StateSchema
from src.models.resolver_runner import ResolverWorkflowRunner
from unittest.mock import AsyncMock

async def debug_turn2b():
    pending = {
        "phrase": "Pendle Voice",
        "candidates": [
            {"id": "p1", "name": "Dalesman", "entityType": "publication"},
            {"id": "p2", "name": "Lancashire Life", "entityType": "publication"},
            {"id": "p3", "name": "Leader and Times", "entityType": "publication"},
        ],
        "expiresAt": 9999999999,
    }

    envelope = AttrDict({
        "version": "1.0",
        "session": {
            "sessionId": "SessionId.test-session-ambiguity",
            "application": {"applicationId": "amzn1.ask.skill.test"},
            "attributes": {},
            "user": {"userId": "test-user"},
            "new": False,
        },
        "context": {
            "System": {
                "application": {"applicationId": "amzn1.ask.skill.test"},
                "user": {"userId": "test-user"},
                "device": {"supportedInterfaces": {"AudioPlayer": {}}},
            },
            "AudioPlayer": {"playerActivity": "IDLE"},
        },
        "request": {
            "type": "IntentRequest",
            "requestId": "Edna.test-request-2b",
            "timestamp": "2026-09-14T00:00:00Z",
            "locale": "en-GB",
            "intent": {
                "name": "OpenDiscoveryIntent",
                "confirmationStatus": "NONE",
                "slots": {
                    "searchQuery": {
                        "name": "searchQuery",
                        "value": "second",
                        "confirmationStatus": "NONE",
                    }
                },
            },
        },
    })

    attributes = AttributesManager(envelope)
    attributes.request_attributes = {
        "_store": {
            **StateSchema.DEFAULT_STORE,
            "onboardingComplete": True,
            "pendingAmbiguity": pending,
        },
        "_dirty": False,
    }
    handler_input = HandlerInput(envelope, attributes, None, ResponseBuilder())

    mock_resolver = AsyncMock()
    mock_container = ApplicationContainer(resolver=mock_resolver)
    runner = ResolverWorkflowRunner(deps=mock_container)

    await runner.apply(handler_input)
    nlp = handler_input.attributes_manager.request_attributes.get("_nlp")
    print("_nlp:", nlp)
    
    from src.middleware.confirmation import ConfirmationMiddleware, SearchConfirmationGateHandler
    ConfirmationMiddleware().process(handler_input)
    attrs = handler_input.attributes_manager.request_attributes
    print("_pendingConfirmation:", attrs.get("_pendingConfirmation"))
    print("_resolverClarification:", attrs.get("_resolverClarification"))
    print("SearchConfirmationGate can_handle:", SearchConfirmationGateHandler().can_handle(handler_input))

if __name__ == "__main__":
    import asyncio
    asyncio.run(debug_turn2b())
