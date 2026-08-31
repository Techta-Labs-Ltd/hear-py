from __future__ import annotations

import json
import re
from pathlib import Path


def _model():
    return json.loads((Path(__file__).parents[1] / "en-GB.json").read_text(encoding="utf-8"))


def test_constrained_latest_utterances_preserve_the_full_topic_slot():
    model = _model()
    intents = {item["name"]: item for item in model["interactionModel"]["languageModel"]["intents"]}
    trending = intents["WhatsTrendingIntent"]
    assert trending["slots"] == [
        {"name": "topic", "type": "AMAZON.SearchQuery"},
        {"name": "dateQuery", "type": "AMAZON.DATE"},
    ]
    assert "what's the latest {topic}" in trending["samples"]
    assert "what is the latest {topic}" in trending["samples"]


def test_search_query_samples_always_include_a_carrier_phrase():
    """Alexa rejects phrase-type samples made entirely from one slot."""
    intents = _model()["interactionModel"]["languageModel"]["intents"]
    for intent in intents:
        search_slots = {
            slot["name"] for slot in intent.get("slots", []) if slot["type"] == "AMAZON.SearchQuery"
        }
        for sample in intent.get("samples", []):
            if search_slots:
                assert sample.strip() not in {
                    "{" + slot_name + "}" for slot_name in search_slots
                }, f"{intent['name']} has a slot-only phrase-type sample"


def test_key_conversation_intents_have_the_expected_slot_contracts():
    intents = {
        item["name"]: item for item in _model()["interactionModel"]["languageModel"]["intents"]
    }
    expected = {
        "TownCaptureIntent": {"townName": "AMAZON.City"},
        "PlayContentIntent": {
            "topic": "AMAZON.SearchQuery",
            "format": "ContentFormat",
            "dateQuery": "AMAZON.DATE",
        },
        "PlayLatestContentIntent": {"topic": "AMAZON.SearchQuery"},
        "PlayByOrganizationIntent": {"organizationQuery": "AMAZON.SearchQuery"},
        "PlayByCreatorIntent": {"creatorQuery": "AMAZON.SearchQuery"},
        "WhatsTrendingIntent": {
            "topic": "AMAZON.SearchQuery",
            "dateQuery": "AMAZON.DATE",
        },
        "ClarifySelectionIntent": {"selection": "HEAR_CLARIFICATION"},
        "SetPlaybackSpeedIntent": {"speed": "HEAR_PLAYBACK_SPEED"},
    }
    for intent_name, slots in expected.items():
        assert {
            slot["name"]: slot["type"] for slot in intents[intent_name].get("slots", [])
        } == slots


def test_location_dialogs_elicit_bare_town_replies():
    dialog_intents = {
        item["name"]: item for item in _model()["interactionModel"]["dialog"]["intents"]
    }
    assert dialog_intents["TownCaptureIntent"]["slots"][0] == {
        "name": "townName",
        "type": "AMAZON.City",
        "confirmationRequired": False,
        "elicitationRequired": True,
        "prompts": {"elicitation": "Elicit.TownCaptureIntent.townName"},
    }
    assert dialog_intents["SetLocationIntent"]["slots"][0]["elicitationRequired"] is True


def test_town_intent_owns_bare_city_and_extends_alexa_city_aliases():
    model = _model()["interactionModel"]["languageModel"]
    intents = {item["name"]: item for item in model["intents"]}
    city_type = next((item for item in model["types"] if item["name"] == "AMAZON.City"))
    herne_bay = next((item for item in city_type["values"] if item["name"]["value"] == "Herne Bay"))
    assert "{townName}" in intents["TownCaptureIntent"]["samples"]
    assert "{location}" not in intents["SetLocationIntent"]["samples"]
    assert herne_bay["id"] == "location-1826454069"
    assert "arn bay" in herne_bay["name"]["synonyms"]


def test_content_discovery_intents_accept_date_constraints():
    intents = {
        item["name"]: item for item in _model()["interactionModel"]["languageModel"]["intents"]
    }
    dated_intents = {
        "PlayContentIntent",
        "PlayPublicationIntent",
        "BrowseContentIntent",
        "WhatsTrendingIntent",
    }
    for intent_name in dated_intents:
        slots = {slot["name"]: slot["type"] for slot in intents[intent_name].get("slots", [])}
        assert slots["dateQuery"] == "AMAZON.DATE"
        assert any(("{dateQuery}" in sample for sample in intents[intent_name]["samples"]))
    for intent_name in {
        "PlayLocalIntent",
        "PlayRecommendationIntent",
        "PlayByOrganizationIntent",
        "PlayByCreatorIntent",
    }:
        assert all((slot["name"] != "dateQuery" for slot in intents[intent_name].get("slots", [])))
        assert all(("{dateQuery}" not in sample for sample in intents[intent_name]["samples"]))


def test_local_community_phrases_are_owned_by_local_intent():
    intents = {
        item["name"]: item for item in _model()["interactionModel"]["languageModel"]["intents"]
    }
    samples = intents["PlayLocalIntent"]["samples"]
    assert "play something from my local community" in samples
    assert "play from my local community" in samples


def test_search_query_is_the_only_slot_in_each_sample_that_uses_it():
    intents = _model()["interactionModel"]["languageModel"]["intents"]
    for intent in intents:
        phrase_slots = {
            slot["name"] for slot in intent.get("slots", []) if slot["type"] == "AMAZON.SearchQuery"
        }
        for sample in intent.get("samples", []):
            used_slots = set(re.findall("\\{([^}]+)\\}", sample))
            if used_slots & phrase_slots:
                assert len(used_slots) == 1, (
                    f"{intent['name']} mixes a phrase slot with another slot: {sample}"
                )


def test_intent_samples_are_unique_within_each_intent():
    intents = _model()["interactionModel"]["languageModel"]["intents"]
    for intent in intents:
        samples = [sample.casefold().strip() for sample in intent.get("samples", [])]
        assert len(samples) == len(set(samples)), f"{intent['name']} contains duplicate samples"


def test_playback_speed_type_has_all_six_named_levels():
    types = {item["name"]: item for item in _model()["interactionModel"]["languageModel"]["types"]}
    values = types["HEAR_PLAYBACK_SPEED"]["values"]
    assert [item["name"]["value"] for item in values] == [
        "0.5",
        "0.75",
        "1",
        "1.25",
        "1.5",
        "2",
    ]
    assert "first speed" in values[0]["name"]["synonyms"]
    assert "sixth speed" in values[-1]["name"]["synonyms"]
