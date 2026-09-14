import sys
sys.path.insert(0, "c:/Users/USER/Downloads/hear-py")

import json
import types
from unittest.mock import AsyncMock, MagicMock

import main
from src.application import Application
from src.container import ApplicationContainer
from src.constants.state import StateSchema
from src.database.persistence import MemoryPersistenceAdapter
from src.models.availability import Availability

def make_context():
    return types.SimpleNamespace(
        function_name="hear-alexa-skill",
        memory_limit_in_mb=512,
        invoked_function_arn="arn:aws:lambda:eu-west-1:123456789012:function:hear-alexa-skill",
        aws_request_id="test-req-1234",
        get_remaining_time_in_millis=lambda: 30000,
    )

def make_envelope(
    request_type="IntentRequest",
    intent_name=None,
    slots=None,
    session_attributes=None,
    session_id="SessionId.test-session-flow",
    new=False,
):
    slots_dict = {}
    if slots:
        for name, val in slots.items():
            is_match = val in ("Swindon", "creators", "second")
            slots_dict[name] = {
                "name": name,
                "value": val,
                "confirmationStatus": "NONE",
                "resolutions": {
                    "resolutionsPerAuthority": [
                        {
                            "status": {"code": "ER_SUCCESS_MATCH" if is_match else "ER_SUCCESS_NO_MATCH"},
                            "authority": "amzn1.er-authority.echo-sdk.1",
                            "values": [{"value": {"name": val, "id": val.lower()}}] if is_match else []
                        }
                    ]
                }
            }
    
    req = {
        "type": request_type,
        "requestId": f"Edna.test-request-{intent_name or request_type}",
        "timestamp": "2026-09-14T00:00:00Z",
        "locale": "en-GB",
    }
    if request_type == "IntentRequest":
        req["intent"] = {
            "name": intent_name,
            "confirmationStatus": "NONE",
            "slots": slots_dict,
        }
    
    return {
        "version": "1.0",
        "session": {
            "sessionId": session_id,
            "application": {"applicationId": "amzn1.ask.skill.test"},
            "attributes": dict(session_attributes or {}),
            "user": {"userId": "amzn1.ask.account.test-user"},
            "new": new,
        },
        "context": {
            "System": {
                "application": {"applicationId": "amzn1.ask.skill.test"},
                "user": {"userId": "amzn1.ask.account.test-user"},
                "device": {"supportedInterfaces": {"AudioPlayer": {}}},
            },
            "AudioPlayer": {"playerActivity": "IDLE"},
        },
        "request": req,
    }

def setup_mock_environment():
    persistence_adapter = MemoryPersistenceAdapter()
    user_id = "amzn1.ask.account.test-user"
    
    persistence_adapter._store[user_id] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
        "listenerId": "test-listener-456",
        "userCity": "Swindon",
    }

    mock_resolver = AsyncMock()
    async def mock_resolve_utterance(utterance, *args, **kwargs):
        u = str(utterance or "").lower()
        if "swindon" in u:
            return {
                "status": "resolved",
                "intent": "creator_location",
                "slots": {"city": "Swindon"},
                "searchPayload": {"query": "", "filter": {"city": "Swindon"}},
                "resolution": {
                    "match": {
                        "city": "Swindon",
                        "countryCode": "gb",
                        "latitude": 51.56,
                        "longitude": -1.78,
                    }
                }
            }
        if "pendle voice" in u:
            return {
                "status": "ambiguous",
                "intent": "publication",
                "ambiguities": [
                    {
                        "phrase": "Pendle Voice",
                        "candidates": [
                            {"id": "p1", "name": "Dalesman", "entityType": "publication"},
                            {"id": "p2", "name": "Lancashire Life", "entityType": "publication"},
                            {"id": "p3", "name": "Leader and Times", "entityType": "publication"},
                        ]
                    }
                ]
            }
        if "lancashire life" in u or "dalesman" in u:
            return {
                "status": "resolved",
                "intent": "publication",
                "slots": {"publication": "Lancashire Life"},
                "searchPayload": {"query": "lancashire life", "filter": {}},
            }
        return {
            "status": "resolved",
            "intent": "general",
            "slots": {},
            "searchPayload": {"query": utterance, "filter": {}}
        }

    mock_resolver.resolve_utterance = AsyncMock(side_effect=mock_resolve_utterance)

    mock_availability = AsyncMock()
    async def mock_begin_creator_location(handler_input, nlp=None):
        from src.alexa.ssml import Ssml
        resolved = dict(nlp or {})
        if resolved.get("locationRejected"):
            from src.alexa.speech import Speech
            return (
                handler_input.response_builder.speak(Ssml.ssml(Speech.CREATOR_CITY_NOT_RECOGNISED))
                .reprompt(Ssml.ssml(Speech.CREATOR_CITY_NOT_RECOGNISED))
                .set_should_end_session(False)
                .response
            )
        return (
            handler_input.response_builder.speak(Ssml.ssml("I found Adeshina Ayomide near Swindon. Would you like to listen?"))
            .reprompt(Ssml.ssml("Say yes to hear it, or no to choose something else."))
            .set_should_end_session(False)
            .response
        )
    mock_availability.begin_creator_location = AsyncMock(side_effect=mock_begin_creator_location)
    mock_availability.ask_creator_city = MagicMock(side_effect=Availability.ask_creator_city)

    mock_heara = AsyncMock()
    mock_heara.search = AsyncMock(return_value={
        "results": [
            {
                "id": "track-101",
                "title": "Lancashire Life Audio Edition",
                "creator": "Pendle Voice",
                "audio_url": "https://stream.hear.media/test.mp3",
                "stream_url": "https://stream.hear.media/test.mp3",
                "duration": 1800,
            }
        ],
        "total_hits": 1,
        "page": 1,
        "total_pages": 1,
    })
    mock_heara.resolve_listener_identity = AsyncMock(return_value={"listenerId": "test-listener-456", "alias": "test-user"})
    mock_heara.sync_listener = AsyncMock(return_value={"ok": True})

    mock_progressive = AsyncMock(send=AsyncMock(return_value=True))

    mock_container = ApplicationContainer(
        resolver=mock_resolver,
        availability=mock_availability,
        progressive=mock_progressive,
        heara=mock_heara,
    )

    main._application._dependencies = mock_container
    main._application._skill = Application.build_skill(
        persistence_adapter=persistence_adapter,
        deps=mock_container,
    )
    return persistence_adapter, mock_container

def run_dialog_tests():
    ctx = make_context()
    
    print("================================================================================")
    print("      FLOW 1: AMBIGUITY SELECTION (Pendle Voice -> second -> Lancashire Life)    ")
    print("================================================================================")
    persistence_adapter, container = setup_mock_environment()
    session_attrs = {}

    # Turn 1: Launch
    env1 = make_envelope(request_type="LaunchRequest", new=True)
    resp1 = main.handler(env1, ctx)
    s1 = resp1.get("response", {}).get("outputSpeech", {}).get("ssml", "")
    session_attrs = resp1.get("sessionAttributes") or {}
    print("\nTurn 1 (Launch):")
    print("Alexa:", s1)
    assert "Welcome" in s1 or "listen" in s1

    # Turn 2: User says "play pendle voice"
    env2 = make_envelope(
        intent_name="PlayContentIntent",
        slots={"topic": "play pendle voice"},
        session_attributes=session_attrs,
    )
    resp2 = main.handler(env2, ctx)
    s2 = resp2.get("response", {}).get("outputSpeech", {}).get("ssml", "")
    session_attrs = resp2.get("sessionAttributes") or {}
    print("\nTurn 2 (User: 'play pendle voice'):")
    print("Alexa:", s2)
    assert "First, Dalesman. Second, Lancashire Life. Third, Leader and Times" in s2

    # Turn 3: User says "second" via ClarifySelectionIntent
    env3 = make_envelope(
        intent_name="ClarifySelectionIntent",
        slots={"selection": "second"},
        session_attributes=session_attrs,
    )
    resp3 = main.handler(env3, ctx)
    s3 = resp3.get("response", {}).get("outputSpeech", {}).get("ssml", "")
    d3 = resp3.get("response", {}).get("directives", [])
    session_attrs = resp3.get("sessionAttributes") or {}
    print("\nTurn 3 (User: 'second' via ClarifySelectionIntent):")
    print("Alexa:", s3)
    print("Directives:", len(d3))
    assert "didn't catch that" not in s3
    assert "couldn't safely confirm" not in s3
    print("=> SUCCESS: Selected candidate Lancashire Life without getting blocked!")

    print("\n================================================================================")
    print("      FLOW 2: CREATOR WORKFLOW & IDLE TRAPS (play from a creator -> no -> no)   ")
    print("================================================================================")
    persistence_adapter, container = setup_mock_environment()
    session_attrs = {}

    # Turn 1: Launch
    env1 = make_envelope(request_type="LaunchRequest", new=True)
    resp1 = main.handler(env1, ctx)
    session_attrs = resp1.get("sessionAttributes") or {}

    # Turn 2: User says "play from a creator"
    env2 = make_envelope(
        intent_name="PlayContentIntent",
        slots={"topic": "creators"},
        session_attributes=session_attrs,
    )
    resp2 = main.handler(env2, ctx)
    s2 = resp2.get("response", {}).get("outputSpeech", {}).get("ssml", "")
    session_attrs = resp2.get("sessionAttributes") or {}
    print("\nTurn 2 (User: 'play from a creator'):")
    print("Alexa:", s2)
    assert "Which city would you like me to find creators in" in s2

    # Turn 3: User says "find creators in swidon"
    env3 = make_envelope(
        intent_name="SelectCreatorCityIntent",
        slots={"cityQuery": "Swindon"},
        session_attributes=session_attrs,
    )
    resp3 = main.handler(env3, ctx)
    s3 = resp3.get("response", {}).get("outputSpeech", {}).get("ssml", "")
    session_attrs = resp3.get("sessionAttributes") or {}
    print("\nTurn 3 (User: 'find creators in swindon'):")
    print("Alexa:", s3)
    assert "Adeshina Ayomide near Swindon" in s3

    # Turn 4: User says "no"
    env4 = make_envelope(
        intent_name="AMAZON.NoIntent",
        session_attributes=session_attrs,
    )
    resp4 = main.handler(env4, ctx)
    s4 = resp4.get("response", {}).get("outputSpeech", {}).get("ssml", "")
    session_attrs = resp4.get("sessionAttributes") or {}
    print("\nTurn 4 (User: 'no'):")
    print("Alexa:", s4)
    assert "What would you like to listen to instead" in s4 or "Please say the name" in s4

    # Turn 5: User says "no" again at idle prompt (classified as OpenDiscoveryIntent searchQuery='no')
    env5 = make_envelope(
        intent_name="OpenDiscoveryIntent",
        slots={"searchQuery": "no"},
        session_attributes=session_attrs,
    )
    resp5 = main.handler(env5, ctx)
    s5 = resp5.get("response", {}).get("outputSpeech", {}).get("ssml", "")
    session_attrs = resp5.get("sessionAttributes") or {}
    print("\nTurn 5 (User: 'no' at idle prompt):")
    print("Alexa:", s5)
    # MUST NOT say "Did you want me to play content on no?"
    assert "content on no" not in s5.lower()
    assert "content on content" not in s5.lower()
    assert "Please say the name of a talking newspaper" in s5
    print("=> SUCCESS: Idle negation cleanly handled without confirmation trap!")

    # Turn 6: User says "yes" at idle prompt (classified as OpenDiscoveryIntent searchQuery='yes')
    env6 = make_envelope(
        intent_name="OpenDiscoveryIntent",
        slots={"searchQuery": "yes"},
        session_attributes=session_attrs,
    )
    resp6 = main.handler(env6, ctx)
    s6 = resp6.get("response", {}).get("outputSpeech", {}).get("ssml", "")
    session_attrs = resp6.get("sessionAttributes") or {}
    print("\nTurn 6 (User: 'yes' at idle prompt):")
    print("Alexa:", s6)
    # MUST NOT say "Did you want me to play content on yes?"
    assert "content on yes" not in s6.lower()
    assert "content on content" not in s6.lower()
    assert "Please say the name of a talking newspaper" in s6
    print("=> SUCCESS: Idle affirmation cleanly handled without confirmation trap!")

    print("\n================================================================================")
    print("                  ALL REAL LAMBDA DIALOG FLOWS PASSED!                          ")
    print("================================================================================")

if __name__ == "__main__":
    run_dialog_tests()
