import asyncio
from src.runtime import AsyncSkill
from src.adapters.memory_persistence import MemoryPersistenceAdapter
from src.middleware import register_middleware

USER_ID = "amzn1.ask.account.TEST"

def make_event(intent_name, slots=None):
    return {
        "version": "1.0",
        "session": {
            "new": True, "sessionId": "s1",
            "application": {"applicationId": "amzn1.ask.skill.test"},
            "attributes": {},
            "user": {"userId": USER_ID},
        },
        "context": {
            "System": {
                "application": {"applicationId": "amzn1.ask.skill.test"},
                "user": {
                    "userId": USER_ID,
                    "permissions": {
                        "consentToken": "t",
                        "scopes": {"alexa::devices:all:geolocation:read": {"status": "GRANTED"}},
                    },
                },
                "device": {"deviceId": "d", "supportedInterfaces": {"AudioPlayer": {}}},
                "apiEndpoint": "https://api.amazonalexa.com",
                "apiAccessToken": "t",
            },
            "AudioPlayer": {"playerActivity": "IDLE"},
        },
        "request": {
            "type": "IntentRequest",
            "requestId": "r1",
            "timestamp": "2026-07-05T08:35:35Z",
            "locale": "en-GB",
            "intent": {"name": intent_name, "slots": slots or {}},
        },
    }


def run(label, event):
    r = asyncio.run(skill.invoke(event, None))
    resp = r.get("response", {})
    speech = resp.get("outputSpeech", {}).get("ssml", "NONE")
    directives = resp.get("directives", [])
    end = resp.get("shouldEndSession")
    card = resp.get("card")

    print(f"--- {label} ---")
    print(f"  Speech: {speech}")
    if directives:
        for d in directives:
            t = d.get("type", "?")
            print(f"  Directive: {t}")
    if card:
        print(f"  Card: {card.get('type', '?')} - {card.get('permissions', [])}")
    print(f"  EndSession: {end}")
    print()


persistence = MemoryPersistenceAdapter()
persistence._store[USER_ID] = {
    "playCount": 5,
    "lastToken": "abc123",
    "userCity": "London",
    "locality": "London",
    "onboardingComplete": True,
    "userName": "John",
}

from src.handlers.intents.launch import LaunchRequestHandler
from src.handlers.intents.play import PlayContentHandler, PlayByCreatorHandler, WhatsTrendingHandler, BrowseContentHandler
from src.handlers.intents.system import HelpIntentHandler, CancelIntentHandler, YesIntentHandler, NoIntentHandler
from src.handlers.intents.social import FollowCreatorHandler

skill = AsyncSkill(persistence_adapter=persistence)
register_middleware(skill)
skill.add_request_handler(LaunchRequestHandler())
skill.add_request_handler(PlayContentHandler())
skill.add_request_handler(PlayByCreatorHandler())
skill.add_request_handler(BrowseContentHandler())
skill.add_request_handler(WhatsTrendingHandler())
skill.add_request_handler(HelpIntentHandler())
skill.add_request_handler(CancelIntentHandler())
skill.add_request_handler(YesIntentHandler())
skill.add_request_handler(NoIntentHandler())
skill.add_request_handler(FollowCreatorHandler())

# Test: "play me the latest sport from David"
run(
    'play me the latest sport from David',
    make_event("PlayContentIntent", {
        "topic": {"name": "topic", "value": "sport"},
        "creatorQuery": {"name": "creatorQuery", "value": "David"},
    }),
)

# Test: "play me the latest sport"
run(
    'play me the latest sport',
    make_event("PlayContentIntent", {
        "topic": {"name": "topic", "value": "sport"},
    }),
)

# Test: "play from David"
run(
    'play from David',
    make_event("PlayByCreatorIntent", {
        "creatorQuery": {"name": "creatorQuery", "value": "David"},
    }),
)

# Also check what the NLP classifier returns for this utterance
from src.nlp.classifier import classify_utterance
print("--- NLP classification ---")
result = classify_utterance("play me the latest sport from David")
print(f"  Result: {result}")
