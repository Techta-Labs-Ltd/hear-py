from __future__ import annotations

import json
import re
from pathlib import Path


def _model():
    return json.loads(
        (Path(__file__).parents[1] / "en-GB.json").read_text(encoding="utf-8")
    )


def test_constrained_latest_utterances_preserve_the_full_topic_slot():
    model = _model()
    intents = {
        item["name"]: item
        for item in model["interactionModel"]["languageModel"]["intents"]
    }
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
            slot["name"] for slot in intent.get("slots", [])
            if slot["type"] == "AMAZON.SearchQuery"
        }
        for sample in intent.get("samples", []):
            if search_slots:
                assert sample.strip() not in {
                    "{" + slot_name + "}" for slot_name in search_slots
                }, f"{intent['name']} has a slot-only phrase-type sample"


def test_key_conversation_intents_have_the_expected_slot_contracts():
    intents = {
        item["name"]: item
        for item in _model()["interactionModel"]["languageModel"]["intents"]
    }
    expected = {
        "TownCaptureIntent": {"townName": "AMAZON.SearchQuery"},
        "PlayContentIntent": {
            "topic": "AMAZON.SearchQuery",
            "format": "ContentFormat",
            "dateQuery": "AMAZON.DATE",
        },
        "PlayByOrganizationIntent": {
            "organizationQuery": "AMAZON.SearchQuery",
        },
        "PlayByCreatorIntent": {
            "creatorQuery": "AMAZON.SearchQuery",
        },
        "WhatsTrendingIntent": {
            "topic": "AMAZON.SearchQuery",
            "dateQuery": "AMAZON.DATE",
        },
        "ClarifySelectionIntent": {"selection": "HEAR_CLARIFICATION"},
    }

    for intent_name, slots in expected.items():
        assert {
            slot["name"]: slot["type"]
            for slot in intents[intent_name].get("slots", [])
        } == slots


def test_content_discovery_intents_accept_date_constraints():
    intents = {
        item["name"]: item
        for item in _model()["interactionModel"]["languageModel"]["intents"]
    }
    dated_intents = {
        "PlayContentIntent", "PlayPublicationIntent", "BrowseContentIntent",
        "WhatsTrendingIntent",
    }

    for intent_name in dated_intents:
        slots = {
            slot["name"]: slot["type"]
            for slot in intents[intent_name].get("slots", [])
        }
        assert slots["dateQuery"] == "AMAZON.DATE"
        assert any(
            "{dateQuery}" in sample
            for sample in intents[intent_name]["samples"]
        )

    for intent_name in {
        "PlayLocalIntent", "PlayRecommendationIntent",
        "PlayByOrganizationIntent", "PlayByCreatorIntent",
    }:
        assert all(
            slot["name"] != "dateQuery"
            for slot in intents[intent_name].get("slots", [])
        )
        assert all(
            "{dateQuery}" not in sample
            for sample in intents[intent_name]["samples"]
        )


def test_search_query_is_the_only_slot_in_each_sample_that_uses_it():
    intents = _model()["interactionModel"]["languageModel"]["intents"]
    for intent in intents:
        phrase_slots = {
            slot["name"] for slot in intent.get("slots", [])
            if slot["type"] == "AMAZON.SearchQuery"
        }
        for sample in intent.get("samples", []):
            used_slots = set(re.findall(r"\{([^}]+)\}", sample))
            if used_slots & phrase_slots:
                assert len(used_slots) == 1, (
                    f"{intent['name']} mixes a phrase slot with another slot: {sample}"
                )


def test_intent_samples_are_unique_within_each_intent():
    intents = _model()["interactionModel"]["languageModel"]["intents"]
    for intent in intents:
        samples = [sample.casefold().strip() for sample in intent.get("samples", [])]
        assert len(samples) == len(set(samples)), (
            f"{intent['name']} contains duplicate samples"
        )
