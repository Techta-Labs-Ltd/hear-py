import pytest

from src.alexa.resume_speech import ResumeSpeech
from src.models.confirmation import ConfirmationPolicy
from src.models.resolver import ResolverResult


def _otley_location_result() -> dict:
    # Production 2026-10-08: "otley and districts" missed the organisation, so the
    # resolver returned the town and a "talking newspaper" tag.
    utterance = "play otley and districts talking newspaper"
    return ResolverResult.from_payload(
        {
            "status": "resolved",
            "intent": "location",
            "entities": [
                {
                    "entityType": "location",
                    "entityId": "loc-otley",
                    "canonicalValue": "Otley",
                    "originalText": "otley",
                    "confidence": 95,
                    "method": "exact",
                    "start": 5,
                    "end": 10,
                    "latitude": 53.9,
                    "longitude": -1.69,
                    "countryCode": "GB",
                    "locationRole": "unspecified",
                    "locationType": "town",
                },
                {
                    "entityType": "tag",
                    "entityId": "talking-newspaper",
                    "canonicalValue": "talking newspaper",
                    "originalText": "talking newspaper",
                    "confidence": 90,
                    "method": "exact",
                    "start": 25,
                    "end": 42,
                },
            ],
            "slots": {
                "residualQuery": "",
                "latest": False,
                "isRecommended": False,
                "isPublication": False,
                "publishedFrom": None,
                "publishedTo": None,
            },
            "ambiguities": [],
            "timingMs": 2,
        }
    ).to_alexa_payload(original_utterance=utterance)


def test_location_primary_request_asks_before_playing():
    nlp = _otley_location_result()
    nlp = {**nlp, "intent": nlp["semanticIntent"]}
    assert nlp["intent"] == "location"

    decision = ConfirmationPolicy.decide(
        nlp,
        request_type="IntentRequest",
        alexa_intent="PlayByOrganizationIntent",
        raw_utterance="play otley and districts talking newspaper",
        validation_failed=False,
    )

    assert decision.kind == "confirm"
    assert decision.pending["confirmText"] == "content on talking newspaper in Otley"


@pytest.mark.parametrize(
    ("active", "store", "expected"),
    [
        ({"organizationName": "Northampton Sound News", "title": "16_Oct5"}, {}, "Northampton Sound News"),
        (
            {"title": "b2b10fb9-4ede-47d4-b80d-2d00435c0071"},
            {"playbackQueue": {"discoveryContext": {"kind": "location", "name": "content on talking newspaper in Otley"}}},
            "content on talking newspaper in Otley",
        ),
        (
            {"title": "b2b10fb9-4ede-47d4-b80d-2d00435c0071"},
            {"playbackQueue": {"discoveryContext": {"kind": "location", "name": "Otley"}}},
            "content from Otley",
        ),
        (
            {"title": "x"},
            {"playbackQueue": {"discoveryContext": {"kind": "topic", "name": "Cancer Support"}}},
            "content on Cancer Support",
        ),
        ({"title": "Living with cancer"}, {}, "Living with cancer"),
        ({"title": "16_Oct5"}, {}, "16 Oct5"),
    ],
)
def test_resume_prompt_always_names_what_was_playing(active, store, expected):
    prompt = ResumeSpeech.prompt(active, store)

    assert prompt == f"You were listening to {expected}. Would you like to continue?"
