import sys
sys.path.insert(0, "c:/Users/USER/Downloads/hear-py")

import json
import types
from unittest.mock import AsyncMock

import main
from src.application import Application
from src.container import ApplicationContainer
from src.constants.state import StateSchema
from src.database.persistence import MemoryPersistenceAdapter

def make_context():
    return types.SimpleNamespace(
        function_name="hear-alexa-skill",
        memory_limit_in_mb=512,
        invoked_function_arn="arn:aws:lambda:eu-west-1:123456789012:function:hear-alexa-skill",
        aws_request_id="test-req-1234",
        get_remaining_time_in_millis=lambda: 30000,
    )

def test_ambiguity_flow():
    persistence_adapter = MemoryPersistenceAdapter()
    user_id = "amzn1.ask.account.test-user"
    
    # Preload user
    persistence_adapter._store[user_id] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
        "listenerId": "test-listener-456",
        "userCity": "London",
    }

    mock_resolver = AsyncMock()
    async def mock_resolve_utterance(utterance, *args, **kwargs):
        u = str(utterance or "").lower()
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
        if "lancashire life" in u:
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
    mock_progressive = AsyncMock(send=AsyncMock(return_value=True))

    mock_container = ApplicationContainer(
        resolver=mock_resolver,
        progressive=mock_progressive,
    )

    main._application._dependencies = mock_container
    main._application._skill = Application.build_skill(
        persistence_adapter=persistence_adapter,
        deps=mock_container,
    )
    
    ctx = make_context()

    # Turn 1: play pendle voice
    print("=== Turn 1: play pendle voice ===")
    turn1_envelope = {
        "version": "1.0",
        "session": {
            "sessionId": "SessionId.test-session-ambiguity",
            "application": {"applicationId": "amzn1.ask.skill.test"},
            "attributes": {},
            "user": {"userId": user_id},
            "new": True,
        },
        "context": {
            "System": {
                "application": {"applicationId": "amzn1.ask.skill.test"},
                "user": {"userId": user_id},
                "device": {"supportedInterfaces": {"AudioPlayer": {}}},
            },
            "AudioPlayer": {"playerActivity": "IDLE"},
        },
        "request": {
            "type": "IntentRequest",
            "requestId": "Edna.test-request-1",
            "timestamp": "2026-09-14T00:00:00Z",
            "locale": "en-GB",
            "intent": {
                "name": "PlayContentIntent",
                "confirmationStatus": "NONE",
                "slots": {
                    "topic": {
                        "name": "topic",
                        "value": "play pendle voice",
                        "confirmationStatus": "NONE",
                    }
                },
            },
        },
    }

    resp1 = main.handler(turn1_envelope, ctx)
    speech1 = resp1.get("response", {}).get("outputSpeech", {}).get("ssml", "")
    session_attrs1 = resp1.get("sessionAttributes") or {}
    print("Turn 1 Speech:", speech1)
    saved_pending = persistence_adapter._store[user_id].get("pendingAmbiguity")
    print("Persistence store pendingAmbiguity:", bool(saved_pending))

    # Turn 2A: User says "second" via ClarifySelectionIntent
    print("\n=== Turn 2A: User says 'second' via ClarifySelectionIntent ===")
    turn2a_envelope = {
        "version": "1.0",
        "session": {
            "sessionId": "SessionId.test-session-ambiguity",
            "application": {"applicationId": "amzn1.ask.skill.test"},
            "attributes": session_attrs1,
            "user": {"userId": user_id},
            "new": False,
        },
        "context": {
            "System": {
                "application": {"applicationId": "amzn1.ask.skill.test"},
                "user": {"userId": user_id},
                "device": {"supportedInterfaces": {"AudioPlayer": {}}},
            },
            "AudioPlayer": {"playerActivity": "IDLE"},
        },
        "request": {
            "type": "IntentRequest",
            "requestId": "Edna.test-request-2a",
            "timestamp": "2026-09-14T00:00:00Z",
            "locale": "en-GB",
            "intent": {
                "name": "ClarifySelectionIntent",
                "confirmationStatus": "NONE",
                "slots": {
                    "selection": {
                        "name": "selection",
                        "value": "second",
                        "confirmationStatus": "NONE",
                        "resolutions": {
                            "resolutionsPerAuthority": [
                                {
                                    "status": {"code": "ER_SUCCESS_MATCH"},
                                    "authority": "amzn1.er-authority.echo-sdk.1",
                                    "values": [{"value": {"name": "second", "id": "second"}}]
                                }
                            ]
                        }
                    }
                },
            },
        },
    }

    resp2a = main.handler(turn2a_envelope, ctx)
    speech2a = resp2a.get("response", {}).get("outputSpeech", {}).get("ssml", "")
    directives2a = resp2a.get("response", {}).get("directives", [])
    print("Turn 2A Speech:", speech2a)
    print("Turn 2A Directives:", len(directives2a))

    # Re-arm pendingAmbiguity for Turn 2B test
    persistence_adapter._store[user_id]["pendingAmbiguity"] = saved_pending

    # Turn 2B: What if Alexa classified "second" as OpenDiscoveryIntent searchQuery="second"?
    print("\n=== Turn 2B: User says 'second' via OpenDiscoveryIntent ===")
    turn2b_envelope = {
        "version": "1.0",
        "session": {
            "sessionId": "SessionId.test-session-ambiguity-2",
            "application": {"applicationId": "amzn1.ask.skill.test"},
            "attributes": session_attrs1,
            "user": {"userId": user_id},
            "new": False,
        },
        "context": {
            "System": {
                "application": {"applicationId": "amzn1.ask.skill.test"},
                "user": {"userId": user_id},
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
    }

    resp2b = main.handler(turn2b_envelope, ctx)
    speech2b = resp2b.get("response", {}).get("outputSpeech", {}).get("ssml", "")
    directives2b = resp2b.get("response", {}).get("directives", [])
    print("Turn 2B Speech:", speech2b)
    print("Turn 2B Directives:", len(directives2b))

if __name__ == "__main__":
    test_ambiguity_flow()
