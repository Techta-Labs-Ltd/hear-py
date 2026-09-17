import json
import sys
import types
from unittest.mock import AsyncMock

import main
from src.application import Application
from src.constants.state import StateSchema
from src.container import ApplicationContainer
from src.database.persistence import MemoryPersistenceAdapter

sys.path.insert(0, "c:/Users/USER/Downloads/hear-py")



def make_context():
    return types.SimpleNamespace(
        function_name="hear-alexa-skill",
        memory_limit_in_mb=512,
        invoked_function_arn="arn:aws:lambda:eu-west-1:123456789012:function:hear-alexa-skill",
        aws_request_id="test-req-1234",
        get_remaining_time_in_millis=lambda: 30000,
    )

def make_envelope(request_type="IntentRequest", intent_name=None, slots=None, session_attributes=None, session_id="SessionId.test-session-123", new=False):
    slots_dict = {}
    if slots:
        for name, val in slots.items():
            slots_dict[name] = {
                "name": name,
                "value": val,
                "confirmationStatus": "NONE",
                "resolutions": {
                    "resolutionsPerAuthority": [
                        {
                            "status": {"code": "ER_SUCCESS_MATCH" if val in ("Swindon", "creators") else "ER_SUCCESS_NO_MATCH"},
                            "authority": "amzn1.er-authority.echo-sdk.1",
                            "values": [{"value": {"name": val, "id": val.lower()}}] if val in ("Swindon", "creators") else []
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

def setup_lambda_environment():
    persistence_adapter = MemoryPersistenceAdapter()
    user_id = "amzn1.ask.account.test-user"
    
    # Pre-populate onboarded user in persistence
    persistence_adapter._store[user_id] = {
        **StateSchema.DEFAULT_STORE,
        "onboardingComplete": True,
        "listenerId": "test-listener-456",
        "userCity": "London",
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
        if "dalesman" in u:
            return {
                "status": "resolved",
                "intent": "publication",
                "slots": {"publication": "Dalesman"},
                "searchPayload": {"query": "dalesman", "filter": {}},
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

    mock_heara = AsyncMock()
    mock_heara.search = AsyncMock(return_value={
        "results": [
            {
                "id": "track-101",
                "title": "Test Track",
                "creator": "Test Creator",
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

def run_tests():
    user_id = "amzn1.ask.account.test-user"
    persistence_adapter, container = setup_lambda_environment()
    ctx = make_context()
    
    intents_to_test = [
        # 1. Lifecycle
        ("LaunchRequest", "LaunchRequest", None, {}),
        ("HelpIntent", "IntentRequest", "AMAZON.HelpIntent", {}),
        ("StopIntent", "IntentRequest", "AMAZON.StopIntent", {}),
        ("CancelIntent", "IntentRequest", "AMAZON.CancelIntent", {}),
        ("NavigateHomeIntent", "IntentRequest", "AMAZON.NavigateHomeIntent", {}),
        ("FallbackIntent", "IntentRequest", "AMAZON.FallbackIntent", {}),

        # 2. Discovery & Search
        ("OpenDiscovery (idle negation 'no')", "IntentRequest", "OpenDiscoveryIntent", {"searchQuery": "no"}),
        ("OpenDiscovery (idle affirmation 'yes')", "IntentRequest", "OpenDiscoveryIntent", {"searchQuery": "yes"}),
        ("OpenDiscovery ('news')", "IntentRequest", "OpenDiscoveryIntent", {"searchQuery": "news"}),
        ("SearchContentIntent", "IntentRequest", "SearchContentIntent", {"searchQuery": "talking news"}),
        ("SearchCreatorIntent", "IntentRequest", "SearchCreatorIntent", {"creatorQuery": "Adeshina"}),
        ("SearchPublicationIntent", "IntentRequest", "SearchPublicationIntent", {"publicationQuery": "Dalesman"}),
        ("SearchLocationIntent", "IntentRequest", "SearchLocationIntent", {"locationQuery": "London"}),
        ("CarrierlessDiscoveryIntent", "IntentRequest", "CarrierlessDiscoveryIntent", {"searchQuery": "podcasts"}),
        ("ChooseSourceKindIntent", "IntentRequest", "ChooseSourceKindIntent", {"sourceKind": "creator"}),

        # 3. Playback & Routing
        ("PlayContentIntent (topic='creators')", "IntentRequest", "PlayContentIntent", {"topic": "creators"}),
        ("SelectCreatorCityIntent (Swindon)", "IntentRequest", "SelectCreatorCityIntent", {"cityQuery": "Swindon"}),
        ("PlayLatestContentIntent", "IntentRequest", "PlayLatestContentIntent", {}),
        ("PlayLocalIntent", "IntentRequest", "PlayLocalIntent", {}),
        ("PlayRecommendationIntent", "IntentRequest", "PlayRecommendationIntent", {}),
        ("PlayByOrganizationIntent", "IntentRequest", "PlayByOrganizationIntent", {"organizationQuery": "TNF"}),
        ("PlayPublicationIntent", "IntentRequest", "PlayPublicationIntent", {"publication": "Dalesman"}),
        ("SelectOrganizationIntent", "IntentRequest", "SelectOrganizationIntent", {"organization": "TNF"}),

        # 4. Browse & Trending
        ("BrowseContentIntent", "IntentRequest", "BrowseContentIntent", {}),
        ("WhatsTrendingIntent", "IntentRequest", "WhatsTrendingIntent", {}),
        ("ShowMoreBrowseIntent", "IntentRequest", "ShowMoreBrowseIntent", {}),
        ("ShowPreviousBrowseIntent", "IntentRequest", "ShowPreviousBrowseIntent", {}),
        ("DismissChoicesIntent", "IntentRequest", "DismissChoicesIntent", {}),
        ("WhatsThisAboutIntent", "IntentRequest", "WhatsThisAboutIntent", {}),

        # 5. Playback Controls
        ("PauseIntent", "IntentRequest", "AMAZON.PauseIntent", {}),
        ("ResumeIntent", "IntentRequest", "AMAZON.ResumeIntent", {}),
        ("NextIntent", "IntentRequest", "AMAZON.NextIntent", {}),
        ("PreviousIntent", "IntentRequest", "AMAZON.PreviousIntent", {}),
        ("RepeatIntent", "IntentRequest", "AMAZON.RepeatIntent", {}),
        ("StartOverIntent", "IntentRequest", "AMAZON.StartOverIntent", {}),
        ("RewindIntent", "IntentRequest", "RewindIntent", {}),
        ("FastForwardIntent", "IntentRequest", "FastForwardIntent", {}),
        ("SetPlaybackSpeedIntent", "IntentRequest", "SetPlaybackSpeedIntent", {"speed": "1.5"}),
        ("IncreaseSpeedIntent", "IntentRequest", "IncreaseSpeedIntent", {}),
        ("DecreaseSpeedIntent", "IntentRequest", "DecreaseSpeedIntent", {}),

        # 6. Social & Follow
        ("WhoIsCreatorIntent", "IntentRequest", "WhoIsCreatorIntent", {}),
        ("FollowCreatorIntent", "IntentRequest", "FollowCreatorIntent", {}),
        ("UnfollowCreatorIntent", "IntentRequest", "UnfollowCreatorIntent", {}),

        # 7. Feedback & Reporting
        ("RateContentIntent", "IntentRequest", "RateContentIntent", {"rating": "5"}),
        ("FeedbackResponseIntent", "IntentRequest", "FeedbackResponseIntent", {"response": "good"}),
        ("SkipFeedbackIntent", "IntentRequest", "SkipFeedbackIntent", {}),
        ("ReportContentIntent", "IntentRequest", "ReportContentIntent", {}),
        ("ReportCreatorIntent", "IntentRequest", "ReportCreatorIntent", {}),

        # 8. Account & Notifications
        ("HearNotificationsIntent", "IntentRequest", "HearNotificationsIntent", {}),
        ("EnableNotificationsIntent", "IntentRequest", "EnableNotificationsIntent", {}),
        ("DisableNotificationsIntent", "IntentRequest", "DisableNotificationsIntent", {}),
        ("SetUpAccountIntent", "IntentRequest", "SetUpAccountIntent", {}),
        ("SetLocationIntent", "IntentRequest", "SetLocationIntent", {}),
        ("TownCaptureIntent", "IntentRequest", "TownCaptureIntent", {"townQuery": "Swindon"}),
    ]

    print("================================================================================")
    print("      RUNNING REAL LAMBDA HANDLER TESTS ACROSS ALL INTENTS                      ")
    print("================================================================================\n")
    
    passed_count = 0
    failed_count = 0
    results = []

    for test_label, req_type, intent_name, slots in intents_to_test:
        persistence_adapter._store[user_id] = {
            **StateSchema.DEFAULT_STORE,
            "onboardingComplete": True,
            "listenerId": "test-listener-456",
            "userCity": "London",
        }
        envelope = make_envelope(
            request_type=req_type,
            intent_name=intent_name,
            slots=slots,
            session_id=f"SessionId.test-{test_label.replace(' ', '_')}",
        )
        try:
            resp = main.handler(envelope, ctx)
            speech = resp.get("response", {}).get("outputSpeech", {}).get("ssml", "")
            directives = resp.get("response", {}).get("directives", [])
            should_end = resp.get("response", {}).get("shouldEndSession")
            
            # Check for crashes, unhandled errors, or bad traps
            is_error = "There was a problem with the requested skill" in speech
            has_trap = "content on no" in speech.lower() or "content on yes" in speech.lower() or "content on content" in speech.lower()
            
            if is_error or has_trap:
                status = "FAIL"
                failed_count += 1
            else:
                status = "PASS"
                passed_count += 1
            
            clean_speech = speech.replace("<speak>", "").replace("</speak>", "").strip()[:80]
            results.append((test_label, status, clean_speech, should_end))
            print(f"[{status}] {test_label:<42} | Speech: {clean_speech!r} | EndSession: {should_end}")
        except Exception as e:
            failed_count += 1
            results.append((test_label, "CRASH", str(e), None))
            print(f"[CRASH] {test_label:<42} | Exception: {e}")

    print("\n================================================================================")
    print(f"SUMMARY: {passed_count} PASSED, {failed_count} FAILED out of {len(intents_to_test)} INTENTS")
    print("================================================================================")
    
    return failed_count == 0

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
