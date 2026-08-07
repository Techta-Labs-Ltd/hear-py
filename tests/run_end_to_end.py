import asyncio
from src.runtime import AsyncSkill
from src.adapters.memory_persistence import MemoryPersistenceAdapter
from src.middleware import register_middleware

USER_ID = "amzn1.ask.account.AMA5VNMEKZ2IKKQ66FJFFNUFHIZWGKDJXHMTPAWPFIW6Q7NFOQDKCSUNC44TFDRZXRIMA7YZUNKJHK2KAVHFCOAQSSSLDEYEFMJYXTZYYOYK52IGMJMU3KWXBZPGNEUJC4HAKIJUSUZDKD3GRL26OQMBR4BPLCMTN4AVAML7OWIYSU5YAPQOTGCEEPHAMQQFZ4B7EEYUT5H56XOI3SQZ3P5S7IOVYU2UZJJXPGKLG2UA"


def make_event(request_type, intent_name=None, slots=None):
    req = {
        "type": request_type,
        "requestId": "amzn1.echo-api.request.test",
        "timestamp": "2026-07-05T08:35:35Z",
        "locale": "en-GB",
    }
    if intent_name:
        req["intent"] = {"name": intent_name, "slots": slots or {}}
    return {
        "version": "1.0",
        "session": {
            "new": True,
            "sessionId": "amzn1.echo-api.session.test",
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
                        "consentToken": "test",
                        "scopes": {"alexa::devices:all:geolocation:read": {"status": "GRANTED"}},
                    },
                },
                "device": {"deviceId": "amzn1.ask.device.TEST", "supportedInterfaces": {"AudioPlayer": {}}},
                "apiEndpoint": "https://api.amazonalexa.com",
                "apiAccessToken": "test-token",
            },
            "AudioPlayer": {"playerActivity": "IDLE"},
        },
        "request": req,
    }


def run_scenario(label, skill, event):
    r = asyncio.run(skill.invoke(event, None))
    resp = r.get("response", {})
    speech = resp.get("outputSpeech", {}).get("ssml", "NONE")
    end = resp.get("shouldEndSession")
    status = "ERROR_GENERIC" if "didn't quite catch" in str(speech) else ("NO SPEECH" if str(speech) == "NONE" else "OK")
    print(f"  [{status}] {label}")
    print(f"         Speech: {str(speech)[:160]}")
    print(f"         EndSession: {end}")
    return speech


# --- returning user ---
persistence = MemoryPersistenceAdapter()
persistence._store[USER_ID] = {
    "playCount": 5, "lastToken": "abc123",
    "userCity": "London", "locality": "London",
    "onboardingComplete": True, "userName": "John",
}

from src.handlers.launch import LaunchRequestHandler

from src.handlers.play import PlayContentHandler

from src.handlers.report import WhatsThisAboutHandler

from src.handlers.system import HelpIntentHandler, CancelIntentHandler


builder = AsyncSkill(persistence_adapter=persistence)
register_middleware(builder)
builder.add_request_handler(LaunchRequestHandler())
builder.add_request_handler(PlayContentHandler())
builder.add_request_handler(WhatsThisAboutHandler())
builder.add_request_handler(HelpIntentHandler())
builder.add_request_handler(CancelIntentHandler())

print("=" * 60)
print("END-TO-END SCENARIO TESTS")
print("=" * 60)
print()

print("--- Returning User (John, London) ---")
run_scenario("open test development", builder, make_event("LaunchRequest"))
run_scenario("play news", builder, make_event("IntentRequest", "PlayContentIntent", {"topic": {"name": "topic", "value": "news"}}))
run_scenario("help", builder, make_event("IntentRequest", "AMAZON.HelpIntent"))
run_scenario("cancel", builder, make_event("IntentRequest", "AMAZON.CancelIntent"))
print()

# --- new user ---
persistence2 = MemoryPersistenceAdapter()
builder2 = AsyncSkill(persistence_adapter=persistence2)
register_middleware(builder2)
builder2.add_request_handler(LaunchRequestHandler())

print("--- New User (empty store) ---")
run_scenario("open test development", builder2, make_event("LaunchRequest"))
run_scenario("help", builder2, make_event("IntentRequest", "AMAZON.HelpIntent"))
run_scenario("cancel", builder2, make_event("IntentRequest", "AMAZON.CancelIntent"))
print()

# --- error edge case ---
print("--- Edge: missing userId ---")
from src.handlers.fallback import UnmatchedIntentHandler

builder3 = AsyncSkill(persistence_adapter=MemoryPersistenceAdapter())
register_middleware(builder3)
builder3.add_request_handler(UnmatchedIntentHandler())
event_no_user = make_event("IntentRequest", "SomeUnknownIntent")
del event_no_user["context"]["System"]["user"]
run_scenario("unknown intent, no user", builder3, event_no_user)
print()

print("=" * 60)
print("ALL SCENARIOS COMPLETE")
print("=" * 60)
