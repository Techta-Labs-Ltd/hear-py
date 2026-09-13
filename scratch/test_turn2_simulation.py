import sys
sys.path.insert(0, ".")
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

from src.container import ApplicationContainer
from src.middleware.resolver import ResolverInterceptor
from src.middleware.confirmation import ConfirmationMiddleware
from src.controllers.intent_dispatch import IntentDispatchGateHandler
from src.alexa.context import RequestContext
from src.models.user import User


def build_handler_input(alexa_intent_name: str, slots: dict = None, store: dict = None):
    hi = MagicMock()
    slot_dict = {}
    if slots:
        for k, v in slots.items():
            slot_dict[k] = {"name": k, "value": v}
    hi.request_envelope = {
        "version": "1.0",
        "session": {"new": False, "sessionId": "s-123", "user": {"userId": "user-123"}},
        "context": {"System": {"user": {"userId": "user-123"}}},
        "request": {
            "type": "IntentRequest",
            "intent": {"name": alexa_intent_name, "slots": slot_dict},
        }
    }
    user_store = {
        "userId": "user-123",
        "listenerId": "listener-123",
        "onboardingComplete": True,
    }
    if store:
        user_store.update(store)
    attrs = {
        "_store": user_store,
        "_request": {},
        "_session": {},
    }
    hi.attributes_manager = MagicMock()
    hi.attributes_manager.request_attributes = attrs
    hi.attributes_manager.get_request_attributes = lambda: attrs
    hi.attributes_manager.set_request_attributes = lambda a: attrs.update(a)
    
    # Response builder mock
    response_obj = MagicMock()
    builder = MagicMock()
    builder.speak = MagicMock(return_value=builder)
    builder.reprompt = MagicMock(return_value=builder)
    builder.set_should_end_session = MagicMock(return_value=builder)
    builder.add_directive = MagicMock(return_value=builder)
    builder.response = response_obj
    builder.get_response = MagicMock(return_value=response_obj)
    hi.response_builder = builder
    
    return hi


async def simulate_turn_1_and_turn_2():
    print("--- SIMULATING TURN 1: Play Pendle Voice ---")
    deps = ApplicationContainer()
    
    pendle_ambiguity_response = {
        "status": "ambiguous",
        "intent": "creator",
        "entities": [],
        "slots": {
            "residualQuery": "",
            "latest": False,
            "isRecommended": False,
            "isPublication": False,
            "sort": None,
            "publishedFrom": None,
            "publishedTo": None,
            "ambiguousReferences": [
                {
                    "phrase": "pendle voice",
                    "candidates": [
                        {"type": "creator", "id": "creator-dalesman", "name": "Pendle Voice Dalesman"},
                        {"type": "creator", "id": "creator-lancashire", "name": "Pendle Voice Lancashire Life"},
                        {"type": "creator", "id": "creator-leader", "name": "Pendle Voice Leader and Times"},
                    ]
                }
            ]
        },
        "ambiguities": [
            {
                "phrase": "pendle voice",
                "candidates": [
                    {"type": "creator", "id": "creator-dalesman", "name": "Pendle Voice Dalesman"},
                    {"type": "creator", "id": "creator-lancashire", "name": "Pendle Voice Lancashire Life"},
                    {"type": "creator", "id": "creator-leader", "name": "Pendle Voice Leader and Times"},
                ]
            }
        ],
        "searchPayload": {"query": "", "filter": {}},
        "timingMs": 25.0,
    }
    deps.resolver = MagicMock()
    deps.resolver.resolve_utterance = AsyncMock(return_value=pendle_ambiguity_response)
    
    # Turn 1: Alexa sends PlayContentIntent
    hi1 = build_handler_input("PlayContentIntent", slots={"topic": "pendle voice"})
    await ResolverInterceptor(deps=deps).process(hi1)
    ConfirmationMiddleware().process(hi1)
    gate1 = IntentDispatchGateHandler(deps=deps)
    assert gate1.can_handle(hi1) is True
    res1 = gate1.handle(hi1)
    if asyncio.iscoroutine(res1):
        res1 = await res1
        
    calls1 = hi1.response_builder.speak.call_args_list
    turn1_speech = calls1[-1][0][0]
    print("Turn 1 Spoken Speech:\n", turn1_speech)
    
    # Check store after turn 1
    store_after_turn_1 = User.snapshot(hi1)
    pending = store_after_turn_1.get("pendingAmbiguity")
    print("\nPending ambiguity after turn 1:")
    print("  present:", pending is not None)
    print("  expiresAt:", pending.get("expiresAt") if pending else None)
    print("  time now:", int(time.time()))
    print("  expires in seconds:", (pending.get("expiresAt") - int(time.time())) if pending else None)
    print("  candidates:", [c["name"] for c in pending.get("candidates", [])] if pending else None)
    
    print("\n--- SIMULATING TURN 2: User says 'second' ---")
    # Alexa sends ClarifySelectionIntent with selection='second'
    hi2 = build_handler_input(
        "ClarifySelectionIntent", 
        slots={"selection": "second"}, 
        store=store_after_turn_1
    )
    await ResolverInterceptor(deps=deps).process(hi2)
    nlp2 = RequestContext.request(hi2).get("_nlp")
    print("Turn 2 _nlp produced by ResolverInterceptor:")
    print("  status:", nlp2.get("status") if nlp2 else None)
    print("  intent:", nlp2.get("intent") if nlp2 else None)
    print("  ambiguityResolution:", nlp2.get("ambiguityResolution") if nlp2 else None)
    print("  searchPayload:", nlp2.get("searchPayload") if nlp2 else None)
    print("  slots:", nlp2.get("slots") if nlp2 else None)
    
    ConfirmationMiddleware().process(hi2)
    attrs2 = RequestContext.request(hi2)
    print("\nConfirmationMiddleware output for Turn 2:")
    print("  _pendingConfirmation:", attrs2.get("_pendingConfirmation"))
    print("  _resolverClarification:", attrs2.get("_resolverClarification"))
    
    gate2 = IntentDispatchGateHandler(deps=deps)
    print("IntentDispatchGateHandler.can_handle:", gate2.can_handle(hi2))
    
    res2 = gate2.handle(hi2)
    if asyncio.iscoroutine(res2):
        res2 = await res2
        
    calls2 = hi2.response_builder.speak.call_args_list
    if calls2:
        print("Turn 2 Spoken Speech:\n", calls2[-1][0][0])


if __name__ == "__main__":
    asyncio.run(simulate_turn_1_and_turn_2())
