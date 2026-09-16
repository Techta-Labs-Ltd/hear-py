import asyncio

from src.application import Application
from src.container import ApplicationContainer
from src.database.persistence import MemoryPersistenceAdapter

USER_ID = "amzn1.ask.account.TEST"


def make_event(intent_name, slots=None):
    return {
        "version": "1.0",
        "session": {
            "new": True,
            "sessionId": "s1",
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
skill = Application.build_skill(persistence, container=ApplicationContainer())
run(
    "play me the latest sport from David",
    make_event(
        "PlayContentIntent",
        {
            "topic": {"name": "topic", "value": "sport"},
            "creatorQuery": {"name": "creatorQuery", "value": "David"},
        },
    ),
)
run(
    "play me the latest sport",
    make_event("PlayContentIntent", {"topic": {"name": "topic", "value": "sport"}}),
)
run(
    "play from David",
    make_event(
        "SearchCreatorIntent",
        {"searchQuery": {"name": "searchQuery", "value": "David"}},
    ),
)
