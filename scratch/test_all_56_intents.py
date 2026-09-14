import sys
sys.path.insert(0, "c:/Users/USER/Downloads/hear-py")
import json
from scratch.test_real_lambda_comprehensive import setup_lambda_environment, make_envelope, make_context
import main
from src.constants.state import StateSchema

persistence_adapter, container = setup_lambda_environment()
ctx = make_context()

from unittest.mock import MagicMock, AsyncMock
from src.models.availability import Availability
container.availability.ask_creator_city = MagicMock(side_effect=Availability.ask_creator_city)

async def mock_begin_local(handler_input, nlp=None):
    return (
        handler_input.response_builder.speak("Here is local content.")
        .set_should_end_session(False)
        .response
    )
container.availability.begin_local = AsyncMock(side_effect=mock_begin_local)

async def mock_begin_recommendations(handler_input, nlp=None):
    return (
        handler_input.response_builder.speak("Here are your recommendations.")
        .set_should_end_session(False)
        .response
    )
container.availability.begin_recommendations = AsyncMock(side_effect=mock_begin_recommendations)


with open("en-GB.json", encoding="utf-8") as f:
    data = json.load(f)
intents = [i["name"] for i in data["interactionModel"]["languageModel"]["intents"]]

sample_slots = {
    "SearchContentIntent": {"searchQuery": "news"},
    "SearchCreatorIntent": {"creatorQuery": "Adeshina"},
    "SearchOrganizationIntent": {"organizationQuery": "TNF"},
    "SearchPublicationIntent": {"publicationQuery": "Dalesman"},
    "SearchLocationIntent": {"locationQuery": "London"},
    "OpenDiscoveryIntent": {"searchQuery": "news"},
    "CarrierlessDiscoveryIntent": {"searchQuery": "podcasts"},
    "ChooseSourceKindIntent": {"sourceKind": "creator"},
    "PlayContentIntent": {"topic": "news"},
    "PlayByOrganizationIntent": {"organizationQuery": "TNF"},
    "PlayPublicationIntent": {"publication": "Dalesman"},
    "SelectOrganizationIntent": {"organization": "TNF"},
    "SelectPublicationSourceIntent": {"publication": "Dalesman"},
    "SelectCreatorCityIntent": {"cityQuery": "Swindon"},
    "SetPlaybackSpeedIntent": {"speed": "1.5"},
    "RateContentIntent": {"rating": "5"},
    "FeedbackResponseIntent": {"response": "good"},
    "TownCaptureIntent": {"townQuery": "Swindon"},
}

print(f"Testing all {len(intents)} intents from en-GB.json with fresh user state:\n")
passed = 0
failed = 0
for idx, intent_name in enumerate(intents, 1):
    persistence_adapter._store.clear()
    user_id = f"amzn1.ask.account.user-{idx}"
    persistence_adapter._store[user_id] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
        "listenerId": f"listener-{idx}",
        "userCity": "London",
    }
    persistence_adapter._store["test-listener-456"] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
        "listenerId": "test-listener-456",
        "userCity": "London",
    }
    slots = sample_slots.get(intent_name, {})
    envelope = make_envelope(
        request_type="IntentRequest",
        intent_name=intent_name,
        slots=slots,
        session_id=f"SessionId.test-{idx}",
    )
    envelope["session"]["user"]["userId"] = user_id
    envelope["context"]["System"]["user"]["userId"] = user_id
    try:
        resp = main.handler(envelope, ctx)
        speech = resp.get("response", {}).get("outputSpeech", {}).get("ssml", "")
        should_end = resp.get("response", {}).get("shouldEndSession")
        clean = speech.replace("<speak>", "").replace("</speak>", "").replace('<break time="400ms"/>', "").strip()
        is_error = "There was a problem with the requested skill" in speech
        if is_error:
            print(f"[{idx:02d}/56] FAIL: {intent_name:<32} -> ERROR: {clean}")
            failed += 1
        else:
            print(f"[{idx:02d}/56] PASS: {intent_name:<32} -> {clean[:65]} (end={should_end})")
            passed += 1
    except Exception as e:
        print(f"[{idx:02d}/56] CRASH: {intent_name:<32} -> {e}")
        failed += 1

print(f"\n================================================================================")
print(f"RESULT: {passed} PASSED, {failed} FAILED out of {len(intents)} intents")
print(f"================================================================================")
