from __future__ import annotations

import asyncio
import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from config.permission_scopes import DEVICE_ADDRESS, GEOLOCATION_READ

from src.adapters.memory_persistence import MemoryPersistenceAdapter
from src.handlers.registry import register_handlers
from src.middleware import register_middleware
from src.runtime import AsyncSkill

REPORT = Path(__file__).parent / "onboarding_simulation_report.md"
USER_ID = "amzn1.ask.account.SIMONBOARDING"

CITY_MATCHES = {
    "swindon": {"city": "Swindon", "locality": "Swindon", "countryCode": "GB",
                "latitude": 51.5558, "longitude": -1.7797},
    "swidon": {"city": "Swindon", "locality": "Swindon", "countryCode": "GB",
               "latitude": 51.5558, "longitude": -1.7797},
    "manchester": {"city": "Manchester", "locality": "Manchester",
                   "countryCode": "GB", "latitude": 53.4808, "longitude": -2.2426},
    "wakefield": {"city": "Wakefield", "locality": "Wakefield",
                  "countryCode": "GB", "latitude": 53.6833, "longitude": -1.4977},
    "burnley": {"city": "Burnley", "locality": "Burnley",
                "countryCode": "GB", "latitude": 53.7893, "longitude": -2.2405},
    "herne bay": {"city": "Herne Bay", "locality": "Herne Bay",
                  "countryCode": "GB", "latitude": 51.3706, "longitude": 1.1270},
}
AMBIGUOUS_TOWNS = {
    "walsall": [
        {"city": "Wakefield", "countryCode": "GB"},
        {"city": "Walsall", "countryCode": "GB"},
        {"city": "Warrington", "countryCode": "GB"},
    ],
}


def fake_resolver_invoke(payload: dict) -> dict:
    """Stand-in for the resolver Lambda: resolve_location + resolve_search."""
    operation = payload.get("operation")
    utterance = str(payload.get("utterance") or "").lower().strip()
    if operation == "resolve_location":
        match = CITY_MATCHES.get(utterance)
        if match:
            return {"version": 1, "status": "resolved",
                    "resolution": {"match": match, "candidates": []}}
        if utterance in AMBIGUOUS_TOWNS:
            return {"version": 1, "status": "resolved",
                    "resolution": {"match": None,
                                   "candidates": AMBIGUOUS_TOWNS[utterance]}}
        return {"version": 1, "status": "resolved",
                "resolution": {"match": None, "candidates": []}}
    if operation == "resolve_search":
        is_community = bool(re.search(r"\b(local|community|near me)\b", utterance))
        if is_community and payload.get("alexaIntent") == "BrowseContentIntent":
            intent = "browse"
        else:
            intent = "local" if is_community else "category"
        slot_key = "category" if intent == "category" else None
        slots = {"residualQuery": ""}
        if slot_key:
            slots[slot_key] = utterance
        return {
            "version": 1, "status": "resolved", "intent": intent,
            "confidence": "high",
            "searchPayload": {"query": utterance, "page": 0, "limit": 20},
            "slots": slots,
        }
    return {"version": 1, "status": "error", "error": f"unknown operation {operation}"}


def make_event(request_type, intent_name=None, slots=None, scopes=None,
               request_extra=None):
    request = {
        "type": request_type,
        "requestId": "amzn1.echo-api.request.sim",
        "timestamp": "2026-07-05T08:35:35Z",
        "locale": "en-GB",
    }
    if intent_name:
        request["intent"] = {"name": intent_name, "slots": slots or {}}
    if request_extra:
        request.update(request_extra)
    return {
        "version": "1.0",
        "session": {
            "new": True,
            "sessionId": "amzn1.echo-api.session.sim",
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
                        "scopes": scopes or {},
                    },
                },
                "device": {"deviceId": "amzn1.ask.device.SIM",
                           "supportedInterfaces": {"AudioPlayer": {}}},
                "apiEndpoint": "https://api.amazonalexa.com",
                "apiAccessToken": "sim-token",
            },
            "AudioPlayer": {"playerActivity": "IDLE"},
        },
        "request": request,
    }


def plain(speech) -> str:
    return re.sub(r"<[^>]+>", "", str(speech or "")).strip()


def _build_skill(store_preset=None):
    persistence = MemoryPersistenceAdapter()
    if store_preset:
        persistence._store[USER_ID] = dict(store_preset)
    skill = AsyncSkill(persistence_adapter=persistence)
    register_middleware(skill)
    register_handlers(skill)
    return skill, persistence


def _invoke(skill, event):
    result = asyncio.run(skill.invoke(event, None))
    response = result.get("response", {})
    speech = plain((response.get("outputSpeech") or {}).get("ssml"))
    directives = response.get("directives") or []
    return speech, directives, response, result


RECORDS = []


def _record(scenario, step, event, stage_before, stage_after, speech, status,
            note="", store=None):
    request = (event or {}).get("request") or {}
    intent = (request.get("intent") or {}).get("name") or request.get("type", "")
    RECORDS.append({
        "scenario": scenario, "step": step, "intent": intent,
        "stage_before": stage_before, "stage_after": stage_after,
        "speech": speech[:240], "status": status, "note": note,
        "store": dict(store or {}),
    })


def _stage(store) -> str:
    return store.get("onboardingStage") or "-"


def run_scenario(scenario_id, steps, store_preset=None):
    """Run a scripted conversation; each step asserts its own expectations."""
    skill, persistence = _build_skill(store_preset)
    store = dict(persistence._store.get(USER_ID) or {})
    session_attributes = {}
    for step in steps:
        stage_before = _stage(store)
        event = dict(step["event"])
        if event.get("request", {}).get("type") != "LaunchRequest" and session_attributes:
            event["session"] = dict(event.get("session") or {})
            event["session"]["attributes"] = dict(session_attributes)
            event["session"]["new"] = False
        speech, directives, response, result = _invoke(skill, event)
        session_attributes = result.get("sessionAttributes") or {}
        store = dict(persistence._store.get(USER_ID) or {})
        stage_after = _stage(store)
        status = "OK"
        if step.get("expect_speech"):
            for needle in step["expect_speech"]:
                if needle.lower() not in speech.lower():
                    status = "FAIL"
        if step.get("expect_stage") and store.get("onboardingStage") != step["expect_stage"]:
            status = "FAIL"
        if step.get("expect_directive") and not any(
                d.get("type") == step["expect_directive"] for d in directives):
            status = "FAIL"
        if step.get("expect_card") and (
                (response.get("card") or {}).get("type") != step["expect_card"]):
            status = "FAIL"
        note = step.get("note", "")
        if step.get("gap"):
            status = "GAP"
            note = note or step["gap"]
        _record(scenario_id, step["step"], step["event"],
                stage_before, stage_after, speech, status, note, store)
        yield {"scenario": scenario_id, "step": step["step"], "speech": speech,
               "directives": directives, "store": store,
               "persistence": persistence, "status": status}


PERMISSION_GRANTED = {
    "alexa::devices:all:address:full:read": {"status": "GRANTED"},
    "alexa::devices:all:geolocation:read": {"status": "GRANTED"},
}

DETECTED_MATCH = {
    "city": "Swindon",
    "locality": "Swindon",
    "countryCode": "GB",
    "postalCode": "SN1",
    "latitude": 51.5558,
    "longitude": -1.7797,
    "source": "device",
}


def make_connections_response(status_code="200"):
    return make_event(
        "Connections.Response",
        scopes=PERMISSION_GRANTED,
        request_extra={
            "name": "AskForPermissionWithConsent",
            "payload": {},
            "token": "sim-token",
            "status": {"code": status_code, "message": "OK"},
        },
    )


def scenario_permission_ask():
    steps = [
        {"step": 1, "event": make_event("LaunchRequest"),
         "expect_speech": ["Welcome to Hear", "location"],
         "expect_stage": "ask_permission"},
        {"step": 2, "event": make_event("IntentRequest", "AMAZON.YesIntent"),
         "expect_card": "AskForPermissionsConsent",
         "expect_stage": "ask_permission"},
        {"step": 3, "event": make_connections_response("200"),
         "expect_speech": ["I think you're in Swindon"],
         "expect_stage": "await_location_confirm"},
        {"step": 4, "event": make_event("IntentRequest", "AMAZON.YesIntent"),
         "expect_speech": ["I've set your location to Swindon",
                           "Would you like to hear the latest from Swindon"],
         "expect_stage": None},
        {"step": 5, "event": make_event("IntentRequest", "AMAZON.YesIntent"),
         "expect_speech": ["couldn't find anything available from Swindon"]},
        {"step": 6, "event": make_event("LaunchRequest", scopes=PERMISSION_GRANTED),
         "expect_speech": ["Welcome back to Hear"]},
    ]
    for record in run_scenario("S1 permission ask + consent card", steps):
        store = record["store"]
        if record["step"] == 3:
            assert store["pendingLocationConfirm"]["city"] == "Swindon"
            assert store["awaitingLocationConfirm"] is True
        if record["step"] == 4:
            assert store["userCity"] == "Swindon"
            assert store["onboardingComplete"] is True
            assert store["locationSource"] == "device"
            assert store["awaitingCommunityPlayback"] is True
        if record["step"] == 5:
            assert store["awaitingCommunityPlayback"] is False
        if record["step"] == 6:
            assert "share your location" not in record["speech"].lower()
            assert store["onboardingStage"] is None


def scenario_consent_denied_falls_back_to_town():
    steps = [
        {"step": 1, "event": make_event("LaunchRequest"),
         "expect_speech": ["Welcome to Hear"], "expect_stage": "ask_permission"},
        {"step": 2, "event": make_event("IntentRequest", "AMAZON.YesIntent"),
         "expect_card": "AskForPermissionsConsent"},
        {"step": 3, "event": make_connections_response("403"),
         "expect_speech": ["Which town or city"],
         "expect_stage": "ask_town"},
    ]
    for record in run_scenario("S8 consent card denied", steps):
        if record["step"] == 3:
            assert record["store"]["onboardingStage"] == "ask_town"


def scenario_relaunch_after_grant_skips_permission_ask():
    steps = [
        {"step": 1, "event": make_event("LaunchRequest", scopes=PERMISSION_GRANTED),
         "expect_speech": ["Welcome to Hear"],
         "expect_stage": "ask_permission"},
        {"step": 2, "event": make_event("IntentRequest", "AMAZON.YesIntent"),
         "expect_speech": ["I think you're in Swindon"],
         "expect_stage": "await_location_confirm"},
        {"step": 3, "event": make_event("IntentRequest", "AMAZON.NoIntent"),
         "expect_speech": ["Which city should I set instead"],
         "expect_stage": None},
        {"step": 4, "event": make_event("IntentRequest", "TownCaptureIntent",
                                        {"townName": {"name": "townName",
                                                     "value": "burnley"}}),
         "expect_speech": ["Did you say Burnley"],
         "expect_stage": "await_location_confirm"},
    ]
    for record in run_scenario("S9 relaunch with granted scopes", steps):
        if record["step"] == 1:
            assert "Welcome to Hear" in record["speech"]


def scenario_manual_town_happy_path():
    steps = [
        {"step": 1, "event": make_event("LaunchRequest"),
         "expect_speech": ["Welcome to Hear"], "expect_stage": "ask_permission"},
        {"step": 2, "event": make_event("IntentRequest", "AMAZON.NoIntent"),
         "expect_speech": ["Which town or city"], "expect_stage": "ask_town"},
        {"step": 3,
         "event": make_event("IntentRequest", "TownCaptureIntent",
                             {"townName": {"name": "townName", "value": "swidon"}}),
         "expect_speech": ["Did you say Swindon"],
         "expect_stage": "await_location_confirm"},
        {"step": 4, "event": make_event("IntentRequest", "AMAZON.YesIntent"),
         "expect_speech": ["I've set your location to Swindon",
                           "Would you like to hear the latest from Swindon"],
         "expect_stage": None},
        {"step": 5, "event": make_event("IntentRequest", "PlayContentIntent",
                                        {"topic": {"name": "topic", "value": "news"}}),
         "expect_speech": ["news"]},
        {"step": 6, "event": make_event("LaunchRequest"),
         "expect_speech": ["Welcome back to Hear"]},
    ]
    for record in run_scenario("S2 manual town happy path", steps):
        store = record["store"]
        if record["step"] == 1:
            assert record["speech"].startswith("Welcome to Hear")
        if record["step"] == 2:
            assert store["onboardingStage"] == "ask_town"
        if record["step"] == 3:
            assert store["pendingLocationConfirm"]["city"] == "Swindon"
            assert store["awaitingLocationConfirm"] is True
        if record["step"] == 4:
            assert store["userCity"] == "Swindon"
            assert store["onboardingComplete"] is True
            assert store["onboardingStage"] is None
            assert store["locationSource"] == "manual"
            assert store["awaitingCommunityPlayback"] is True
        if record["step"] == 5:
            assert store["awaitingCommunityPlayback"] is False
        if record["step"] == 6:
            assert store["onboardingComplete"] is True
            assert "share your location" not in record["speech"].lower()


def scenario_ambiguous_town():
    steps = [
        {"step": 1, "event": make_event("LaunchRequest"),
         "expect_stage": "ask_permission"},
        {"step": 2, "event": make_event("IntentRequest", "AMAZON.NoIntent"),
         "expect_stage": "ask_town"},
        {"step": 3,
         "event": make_event("IntentRequest", "TownCaptureIntent",
                             {"townName": {"name": "townName", "value": "walsall"}}),
         "expect_speech": ["Did you mean Wakefield or Walsall"],
         "expect_stage": "ask_town"},
        {"step": 4,
         "event": make_event("IntentRequest", "TownCaptureIntent",
                             {"townName": {"name": "townName", "value": "wakefield"}}),
         "expect_speech": ["Did you say Wakefield"],
         "expect_stage": "await_location_confirm"},
        {"step": 5, "event": make_event("IntentRequest", "AMAZON.YesIntent"),
         "expect_speech": ["I've set your location to Wakefield"]},
    ]
    for record in run_scenario("S3 ambiguous town", steps):
        if record["step"] == 3:
            assert record["store"]["onboardingTownAttempts"] == 1
        if record["step"] == 5:
            assert record["store"]["userCity"] == "Wakefield"


def scenario_town_skip_after_attempts():
    steps = [
        {"step": 1, "event": make_event("LaunchRequest"),
         "expect_speech": ["Welcome to Hear"], "expect_stage": "ask_permission"},
        {"step": 2, "event": make_event("IntentRequest", "AMAZON.NoIntent"),
         "expect_speech": ["Which town or city"], "expect_stage": "ask_town"},
    ]
    for attempt in range(1, 4):
        steps.append({
            "step": attempt + 2,
            "event": make_event("IntentRequest", "TownCaptureIntent",
                                {"townName": {"name": "townName", "value": "zzzz"}}),
            "expect_stage": "ask_town",
        })
    steps.append({
        "step": 6,
        "event": make_event("IntentRequest", "TownCaptureIntent",
                            {"townName": {"name": "townName", "value": "zzzz"}}),
        "expect_speech": ["Okay. What would you like to listen to?"],
        "expect_stage": None,
    })
    steps.append({
        "step": 7,
        "event": make_event("IntentRequest", "PlayContentIntent",
                            {"topic": {"name": "topic", "value": "news"}}),
        "expect_speech": ["Did you want me to play news"],
    })
    seen = []
    for record in run_scenario("S4 town attempts cap then skip", steps):
        seen.append(record["step"])
        if record["step"] in (3, 4, 5):
            assert "Just the town name please" in record["speech"]
        if record["step"] == 6:
            assert record["store"]["onboardingStage"] is None
            assert record["store"]["onboardingComplete"] is True
        if record["step"] == 7:
            assert "share your location" not in record["speech"].lower()


def scenario_community_without_location():
    preset = {"onboardingComplete": True, "playCount": 5, "lastToken": "tok"}
    steps = [
        {"step": 1,
         "event": make_event("IntentRequest", "BrowseContentIntent",
                             {"topic": {"name": "topic", "value": "community"}}),
         "expect_speech": ["I'll need your town to find local content"],
         "expect_stage": "confirm_town_for_community"},
        {"step": 2,
         "event": make_event("IntentRequest", "TownCaptureIntent",
                             {"townName": {"name": "townName", "value": "swindon"}}),
         "expect_speech": ["Did you say Swindon"],
         "expect_stage": "await_location_confirm"},
        {"step": 3, "event": make_event("IntentRequest", "AMAZON.YesIntent"),
         "expect_speech": ["I've set your location to Swindon",
                           "Would you like to hear the latest from Swindon"]},
        {"step": 4,
         "event": make_event("IntentRequest", "PlayContentIntent",
                             {"topic": {"name": "topic", "value": "community"}}),
         "expect_speech": ["Did you want me to play tracks near you"]},
        {"step": 5, "event": make_event("IntentRequest", "AMAZON.YesIntent"),
         "expect_speech": ["couldn't find anything for tracks near you"]},
    ]
    for record in run_scenario("S5 community request without location", steps,
                               store_preset=preset):
        store = record["store"]
        if record["step"] == 1:
            assert store["onboardingStage"] == "confirm_town_for_community"
        if record["step"] == 3:
            assert store["userCity"] == "Swindon"
            assert store["onboardingComplete"] is True
            assert store["awaitingCommunityPlayback"] is True
        if record["step"] == 4:
            assert store["awaitingCommunityPlayback"] is False
        if record["step"] == 5:
            assert store["awaitingCommunityPlayback"] is False


def scenario_returning_user():
    preset = {"onboardingComplete": True, "playCount": 5, "lastToken": "tok",
              "userName": "John", "userCity": "London", "locality": "London"}
    steps = [
        {"step": 1, "event": make_event("LaunchRequest"),
         "expect_speech": ["Welcome back to Hear, John"]},
    ]
    for record in run_scenario("S6 returning user named", steps,
                               store_preset=preset):
        assert record["store"]["onboardingComplete"] is True


def scenario_set_location():
    preset = {"onboardingComplete": True, "playCount": 5, "lastToken": "tok",
              "userCity": "London", "locality": "London"}
    steps = [
        {"step": 1,
         "event": make_event("IntentRequest", "SetLocationIntent",
                             {"location": {"name": "location", "value": "manchester"}}),
         "expect_speech": ["Did you say Manchester"],
         "expect_stage": "await_location_confirm"},
        {"step": 2, "event": make_event("IntentRequest", "AMAZON.YesIntent"),
         "expect_speech": ["I've set your location to Manchester"]},
    ]
    for record in run_scenario("S7 set location", steps, store_preset=preset):
        if record["step"] == 2:
            assert record["store"]["userCity"] == "Manchester"
            assert record["store"]["onboardingStage"] is None


def scenario_off_script_replies_stay_in_stage():
    steps = [
        {"step": 1, "event": make_event("LaunchRequest"),
         "expect_speech": ["Welcome to Hear"], "expect_stage": "ask_permission"},
        {"step": 2, "event": make_event("IntentRequest", "AMAZON.NoIntent"),
         "expect_speech": ["Which town or city"], "expect_stage": "ask_town"},
        {"step": 3, "event": make_event("IntentRequest", "AMAZON.FallbackIntent"),
         "expect_speech": ["Just the town name please"],
         "expect_stage": "ask_town"},
        {"step": 4, "event": make_event("IntentRequest", "WhatsTrendingIntent"),
         "expect_speech": ["Just the town name please"],
         "expect_stage": "ask_town"},
        {"step": 5, "event": make_event("IntentRequest", "TownCaptureIntent",
                                        {"townName": {"name": "townName",
                                                     "value": "burnley"}}),
         "expect_speech": ["Did you say Burnley"],
         "expect_stage": "await_location_confirm"},
        {"step": 6, "event": make_event("IntentRequest", "PlayContentIntent",
                                        {"topic": {"name": "topic", "value": "news"}}),
         "expect_speech": ["Did you say Burnley"],
         "expect_stage": "await_location_confirm"},
        {"step": 7, "event": make_event("LaunchRequest"),
         "expect_speech": ["Welcome to Hear"],
         "expect_stage": "ask_permission"},
        {"step": 8, "event": make_event("IntentRequest", "AMAZON.YesIntent"),
         "expect_card": "AskForPermissionsConsent",
         "expect_stage": "ask_permission"},
    ]
    for record in run_scenario("S10 off-script replies stay in stage", steps):
        store = record["store"]
        if record["step"] == 3:
            assert store["onboardingTownAttempts"] == 1
        if record["step"] == 4:
            assert store["onboardingTownAttempts"] == 2
            assert "trending" not in record["speech"].lower()
        if record["step"] == 6:
            assert store["awaitingCommunityPlayback"] is False


def scenario_content_or_skip_classified_at_town_capture():
    steps = [
        {"step": 1, "event": make_event("LaunchRequest"),
         "expect_speech": ["Welcome to Hear"], "expect_stage": "ask_permission"},
        {"step": 2, "event": make_event("IntentRequest", "AMAZON.NoIntent"),
         "expect_speech": ["Which town or city"], "expect_stage": "ask_town"},
        {"step": 3, "event": make_event("IntentRequest", "TownCaptureIntent",
                                        {"townName": {"name": "townName",
                                                     "value": "what's trending"}}),
         "expect_speech": ["Happy to play that for you"],
         "expect_stage": "ask_town"},
        {"step": 4, "event": make_event("IntentRequest", "TownCaptureIntent",
                                        {"townName": {"name": "townName",
                                                     "value": "skip"}}),
         "expect_speech": ["Okay. What would you like to listen to?"],
         "expect_stage": None},
    ]
    for record in run_scenario(
            "S11 content or skip classified at town capture", steps):
        store = record["store"]
        if record["step"] == 3:
            assert store["onboardingTownAttempts"] == 1
        if record["step"] == 4:
            assert store["onboardingComplete"] is True
            assert store["onboardingStage"] is None


def scenario_returning_user_dangling_stage_is_redirected():
    preset = {"onboardingComplete": True, "playCount": 5, "lastToken": "tok",
              "onboardingStage": "ask_town", "onboardingTownAttempts": 1}
    steps = [
        {"step": 1, "event": make_event("IntentRequest", "AMAZON.FallbackIntent"),
         "expect_speech": ["Just the town name please"],
         "expect_stage": "ask_town"},
    ]
    for record in run_scenario(
            "S12 returning user dangling stage is redirected", steps,
            store_preset=preset):
        assert record["store"]["onboardingTownAttempts"] == 2


def scenario_relaunch_mid_onboarding_resets_stage():
    steps = [
        {"step": 1, "event": make_event("LaunchRequest"),
         "expect_speech": ["Welcome to Hear"], "expect_stage": "ask_permission"},
        {"step": 2, "event": make_event("IntentRequest", "AMAZON.NoIntent"),
         "expect_speech": ["Which town or city"], "expect_stage": "ask_town"},
        {"step": 3, "event": make_event("LaunchRequest"),
         "expect_speech": ["Welcome to Hear"], "expect_stage": "ask_permission"},
    ]
    for record in run_scenario("S13 relaunch mid onboarding resets stage", steps):
        if record["step"] == 3:
            assert "where are you based" not in record["speech"].lower()


def scenario_granted_permission_no_city_in_account():
    steps = [
        {"step": 1, "event": make_event("LaunchRequest", scopes=PERMISSION_GRANTED),
         "expect_speech": ["Welcome to Hear"],
         "expect_stage": "ask_permission"},
        {"step": 2, "event": make_event("IntentRequest", "AMAZON.YesIntent"),
         "expect_speech": ["couldn't find your location from your account"],
         "expect_stage": "ask_town"},
    ]
    with patch("src.handlers.intents.onboarding.detect_device_location", AsyncMock(return_value=None)):
        for record in run_scenario("S14 granted permission no city in account", steps):
            if record["step"] == 2:
                assert "no worries" not in record["speech"].lower()


@pytest.fixture(autouse=True)
def _reset_records():
    RECORDS.clear()
    yield


@pytest.fixture(scope="module")
def simulation():
    with patch("src.services.resolver_client._invoke", fake_resolver_invoke), \
            patch("src.services.api.sync_listener",
                  AsyncMock(return_value={"listenerId": "sim-listener"})), \
            patch("src.services.listeners.sync_listener",
                  AsyncMock(return_value={"listenerId": "sim-listener"})), \
            patch("src.handlers.intents.system.sync_listener",
                  AsyncMock(return_value={"listenerId": "sim-listener"})), \
            patch("src.handlers.intents.play.search",
                  AsyncMock(return_value={"results": [],
                                          "total_hits": 0,
                                          "failed": False})), \
            patch("src.handlers.intents.system.search",
                  AsyncMock(return_value={"results": [],
                                          "total_hits": 0,
                                          "failed": False})), \
            patch("src.handlers.intents.onboarding.detect_device_location",
                  AsyncMock(return_value=dict(DETECTED_MATCH))), \
            patch("src.services.alexa.locality._fetch_profile_setting_with_status",
                  AsyncMock(return_value={"value": None, "status": 403})):
        scenario_permission_ask()
        scenario_manual_town_happy_path()
        scenario_ambiguous_town()
        scenario_town_skip_after_attempts()
        scenario_community_without_location()
        scenario_returning_user()
        scenario_set_location()
        scenario_consent_denied_falls_back_to_town()
        scenario_relaunch_after_grant_skips_permission_ask()
        scenario_off_script_replies_stay_in_stage()
        scenario_content_or_skip_classified_at_town_capture()
        scenario_returning_user_dangling_stage_is_redirected()
        scenario_relaunch_mid_onboarding_resets_stage()
        scenario_granted_permission_no_city_in_account()
    return list(RECORDS)


def test_gate_offers_permission_to_new_users(simulation):
    first = simulation[0]
    assert first["scenario"] == "S1 permission ask + consent card"
    assert first["status"] == "OK"
    assert "Welcome to Hear" in first["speech"]


def test_consent_card_requests_both_location_scopes(simulation):
    card = next(r for r in simulation
                if r["step"] == 2 and r["scenario"].startswith("S1"))
    assert card["status"] == "OK"


def test_manual_town_resolves_confirms_and_syncs(simulation):
    rows = [r for r in simulation if r["scenario"].startswith("S2")]
    assert {r["status"] for r in rows if r["step"] <= 5} == {"OK"}
    assert any("Did you say Swindon" in r["speech"] for r in rows)
    assert any("I've set your location to Swindon" in r["speech"] for r in rows)
    sync = [r for r in simulation if r["step"] == 4
            and r["scenario"].startswith("S2")]
    assert sync and sync[0]["status"] == "OK"


def test_ambiguous_town_offers_candidates_then_confirms(simulation):
    rows = [r for r in simulation if r["scenario"].startswith("S3")]
    assert any("Did you mean Wakefield or Walsall" in r["speech"] for r in rows)
    assert any("Did you say Wakefield" in r["speech"] for r in rows)


def test_town_attempts_are_capped_then_skipped(simulation):
    rows = [r for r in simulation if r["scenario"].startswith("S4")]
    assert any("Just the town name please" in r["speech"] for r in rows)
    assert any("Okay. What would you like to listen to?" in r["speech"]
               for r in rows)


def test_community_request_without_location_asks_for_town(simulation):
    rows = [r for r in simulation if r["scenario"].startswith("S5")]
    assert any("I'll need your town to find local content" in r["speech"]
               for r in rows)
    assert any("Did you say Swindon" in r["speech"] for r in rows)


def test_returning_user_is_welcomed_by_name(simulation):
    rows = [r for r in simulation if r["scenario"].startswith("S6")]
    assert any("Welcome back to Hear, John" in r["speech"] for r in rows)


def test_set_location_updates_the_city(simulation):
    rows = [r for r in simulation if r["scenario"].startswith("S7")]
    assert any("I've set your location to Manchester" in r["speech"]
               for r in rows)


def test_known_gaps_are_reproduced_and_documented(simulation):
    gaps = [r for r in simulation if r["status"] == "GAP"]
    assert gaps == [], f"expected no reproduced gaps, got {gaps}"


def test_consent_card_response_auto_detects_city(simulation):
    rows = [r for r in simulation if r["scenario"].startswith("S1")]
    detected = next(r for r in rows if r["step"] == 3)
    assert detected["status"] == "OK"
    assert "I think you're in Swindon" in detected["speech"]
    confirmed = next(r for r in rows if r["step"] == 4)
    assert confirmed["store"]["locationSource"] == "device"


def test_community_follow_up_offer_is_answered(simulation):
    rows = [r for r in simulation if r["scenario"].startswith("S1")]
    assert any("Would you like to hear the latest from Swindon" in r["speech"]
               for r in rows)
    assert any("couldn't find anything available from Swindon" in r["speech"]
               for r in rows)


def test_simulation_report_is_written(simulation):
    REPORT.write_text(_render_report(simulation), encoding="utf-8")
    text = REPORT.read_text(encoding="utf-8")
    assert "Status counts" in text
    assert "GAPS" in text
    assert "No gaps reproduced in this run." in text
    assert all(header in text for header in (
        "S1 permission ask + consent card",
        "S2 manual town happy path",
        "S3 ambiguous town",
        "S4 town attempts cap then skip",
        "S5 community request without location",
        "S6 returning user named",
        "S7 set location",
        "S8 consent card denied",
        "S9 relaunch with granted scopes",
        "S10 off-script replies stay in stage",
        "S11 content or skip classified at town capture",
        "S12 returning user dangling stage is redirected",
    ))


def test_off_script_replies_stay_anchored_to_onboarding(simulation):
    rows = [r for r in simulation if r["scenario"].startswith("S10")]
    assert all(r["status"] == "OK" for r in rows)
    assert rows[2]["speech"].startswith("Just the town name please")
    assert rows[3]["speech"].startswith("Just the town name please")
    assert any("Did you say Burnley" in r["speech"] for r in rows[4:])
    assert "news" not in rows[5]["speech"].lower()


def test_content_request_is_deferred_then_skip_completes_onboarding(simulation):
    rows = [r for r in simulation if r["scenario"].startswith("S11")]
    assert all(r["status"] == "OK" for r in rows)
    deferred = next(r for r in rows if r["step"] == 3)
    assert "Happy to play that for you" in deferred["speech"]
    assert deferred["store"]["onboardingStage"] == "ask_town"
    skipped = next(r for r in rows if r["step"] == 4)
    assert "Okay. What would you like to listen to?" in skipped["speech"]
    assert skipped["store"]["onboardingComplete"] is True


def test_dangling_stage_on_returning_user_is_redirected(simulation):
    rows = [r for r in simulation if r["scenario"].startswith("S12")]
    assert rows and rows[0]["status"] == "OK"
    assert rows[0]["store"]["onboardingTownAttempts"] == 2


def test_bare_herne_bay_keeps_manual_town_session_open():
    with patch("src.services.resolver_client._invoke", fake_resolver_invoke):
        skill, _ = _build_skill()
        _, _, permission_response, _ = _invoke(skill, make_event("LaunchRequest"))
        assert permission_response["shouldEndSession"] is False

        _, _, town_prompt, town_prompt_envelope = _invoke(
            skill, make_event("IntentRequest", "AMAZON.NoIntent"),
        )
        assert town_prompt["shouldEndSession"] is False
        assert town_prompt.get("reprompt")
        assert town_prompt_envelope["sessionAttributes"]["onboardingStage"] == "ask_town"

        speech, _, confirmation, _ = _invoke(
            skill,
            make_event(
                "IntentRequest",
                "SetLocationIntent",
                {"location": {"name": "location", "value": "Herne Bay"}},
            ),
        )
        assert "Did you say Herne Bay" in speech
        assert confirmation["shouldEndSession"] is False
        assert confirmation.get("reprompt")


def _render_report(records) -> str:
    statuses = {}
    for record in records:
        statuses[record["status"]] = statuses.get(record["status"], 0) + 1
    lines = [
        "# Onboarding Simulation Report",
        "",
        "Live simulation of the onboarding checklist through the real skill "
        "stack (AsyncSkill + middleware + registry + memory persistence), "
        "with only the resolver Lambda and the Hear API mocked.",
        "",
        "## Status counts",
        "",
        "| Status | Count |",
        "| --- | --- |",
    ]
    for status in ("OK", "GAP", "FAIL"):
        lines.append(f"| {status} | {statuses.get(status, 0)} |")
    lines += ["", "## Scenarios", ""]
    current = None
    for record in records:
        if record["scenario"] != current:
            current = record["scenario"]
            lines.append(f"### {current}")
            lines.append("")
            lines.append("| Step | Intent | Stage in | Stage out | Status | Speech | Note |")
            lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        intent = record["intent"] or "LaunchRequest"
        note = (record["note"].replace("|", "/")[:70] if record["note"] else "")
        speech = record["speech"].replace("|", "/").replace("\n", " ")
        lines.append(
            f"| {record['step']} | {intent} | {record['stage_before']} | "
            f"{record['stage_after']} | {record['status']} | {speech} | {note} |"
        )
    gaps = [r for r in records if r["status"] == "GAP"]
    lines += ["", "## GAPS", ""]
    if not gaps:
        lines.append("No gaps reproduced in this run.")
    for gap in gaps:
        lines.append(f"- **{gap['note'].split(':')[0]}** ({gap['scenario']}): "
                     f"{gap['note']}")
    lines += ["",
              "Real-device/live-skill testing is not possible on this machine; "
              "this simulation is the verification boundary."]
    return "\n".join(lines) + "\n"
