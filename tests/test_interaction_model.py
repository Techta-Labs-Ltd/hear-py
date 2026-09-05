from __future__ import annotations

import json
from pathlib import Path


def _model():
    return json.loads((Path(__file__).parents[1] / "en-GB.json").read_text(encoding="utf-8"))


def test_constrained_latest_utterances_preserve_the_full_topic_slot():
    model = _model()
    intents = {item["name"]: item for item in model["interactionModel"]["languageModel"]["intents"]}
    latest = intents["PlayLatestContentIntent"]
    trending = intents["WhatsTrendingIntent"]
    assert "what's the latest {topic}" in latest["samples"]
    assert "what is the latest {topic}" in latest["samples"]
    assert "what's the latest {topic}" not in trending["samples"]


def test_discovery_intents_use_domain_specific_generated_slots():
    intents = {
        item["name"]: item
        for item in _model()["interactionModel"]["languageModel"]["intents"]
    }
    protected = {
        "PlayContentIntent",
        "PlayLatestContentIntent",
        "PlayLocalIntent",
        "PlayRecommendationIntent",
        "PlayByOrganizationIntent",
        "PlayPublicationIntent",
        "PlayByCreatorIntent",
        "WhatsTrendingIntent",
    }
    for intent_name in protected:
        assert all(
            slot["type"] != "AMAZON.SearchQuery"
            for slot in intents[intent_name].get("slots", [])
        )
    assert {
        slot["type"]
        for intent_name in protected
        for slot in intents[intent_name].get("slots", [])
        if slot["type"].startswith("HEAR_")
    }.issuperset({"HEAR_LOCATION", "HEAR_ORGANIZATION", "HEAR_CREATOR", "HEAR_TOPIC"})


def test_key_conversation_intents_have_the_expected_slot_contracts():
    intents = {
        item["name"]: item for item in _model()["interactionModel"]["languageModel"]["intents"]
    }
    expected = {
        "TownCaptureIntent": {"townName": "HEAR_LOCATION"},
        "SetLocationIntent": {"location": "HEAR_LOCATION"},
        "PlayContentIntent": {
            "topic": "HEAR_TOPIC",
            "format": "ContentFormat",
            "dateQuery": "AMAZON.DATE",
        },
        "PlayLatestContentIntent": {"topic": "HEAR_TOPIC"},
        "PlayRecommendationIntent": {"recommendationQuery": "HEAR_TOPIC"},
        "PlayByOrganizationIntent": {
            "organizationQuery": "HEAR_ORGANIZATION",
            "topic": "HEAR_TOPIC",
        },
        "PlayByCreatorIntent": {
            "creatorQuery": "HEAR_CREATOR",
            "topic": "HEAR_TOPIC",
        },
        "PlayPublicationIntent": {
            "publicationSourceQuery": "HEAR_ORGANIZATION",
            "publicationSort": "HEAR_PUBLICATION_SORT",
            "dateQuery": "AMAZON.DATE",
        },
        "PlayLocalIntent": {
            "localQuery": "HEAR_LOCATION",
            "cityQuery": "HEAR_LOCATION",
            "topic": "HEAR_TOPIC",
        },
        "WhatsTrendingIntent": {
            "topic": "HEAR_TOPIC",
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
        "type": "HEAR_LOCATION",
        "confirmationRequired": False,
        "elicitationRequired": True,
        "prompts": {"elicitation": "Elicit.TownCaptureIntent.townName"},
    }
    assert dialog_intents["SetLocationIntent"]["slots"][0]["elicitationRequired"] is True


def test_town_intent_owns_bare_city_and_uses_generated_location_slot():
    model = _model()["interactionModel"]["languageModel"]
    intents = {item["name"]: item for item in model["intents"]}
    city_type = next((item for item in model["types"] if item["name"] == "HEAR_LOCATION"))
    herne_bay = next((item for item in city_type["values"] if item["name"]["value"] == "Herne Bay"))
    assert "{townName}" in intents["TownCaptureIntent"]["samples"]
    assert "{location}" not in intents["SetLocationIntent"]["samples"]
    assert "id" not in herne_bay
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


def test_local_search_keeps_city_search_separate_from_location_mutation():
    intents = {
        item["name"]: item for item in _model()["interactionModel"]["languageModel"]["intents"]
    }
    local_samples = set(intents["PlayLocalIntent"]["samples"])
    location_samples = set(intents["SetLocationIntent"]["samples"])
    assert "play content in {cityQuery}" in local_samples
    assert "find content around {localQuery}" in local_samples
    assert "play something from {cityQuery}" in local_samples
    assert all("{cityQuery}" not in sample for sample in location_samples)


def test_generic_source_search_is_neutral_and_specialized_routes_are_explicit():
    intents = {
        item["name"]: item for item in _model()["interactionModel"]["languageModel"]["intents"]
    }
    general = set(intents["PlayContentIntent"]["samples"])
    creators = set(intents["PlayByCreatorIntent"]["samples"])
    organizations = set(intents["PlayByOrganizationIntent"]["samples"])
    content_topic = next(
        slot for slot in intents["PlayContentIntent"]["slots"] if slot["name"] == "topic"
    )
    creator_slot = next(
        slot
        for slot in intents["PlayByCreatorIntent"]["slots"]
        if slot["name"] == "creatorQuery"
    )
    assert {"play from {topic}", "play content from {topic}"}.isdisjoint(general)
    assert "from {topic}" not in content_topic["samples"]
    assert "by {creatorQuery}" in creator_slot["samples"]
    assert "play by {creatorQuery}" in creators
    assert "play from {organizationQuery}" in organizations
    assert "play {topic} from {organizationQuery}" in organizations
    assert "play {topic} by {creatorQuery}" in creators
    assert "find the creator {creatorQuery}" in creators
    assert "find the talking newspaper {organizationQuery}" in organizations


def test_elicited_slots_have_reply_samples_and_dialog_contracts():
    model = _model()["interactionModel"]
    intents = {item["name"]: item for item in model["languageModel"]["intents"]}
    for intent_name, slot_name in {
        "PlayContentIntent": "topic",
        "PlayByCreatorIntent": "creatorQuery",
        "PlayByOrganizationIntent": "organizationQuery",
        "PlayPublicationIntent": "publicationSourceQuery",
        "ClarifySelectionIntent": "selection",
        "TownCaptureIntent": "townName",
        "SetLocationIntent": "location",
    }.items():
        slot = next(item for item in intents[intent_name]["slots"] if item["name"] == slot_name)
        assert slot.get("samples"), f"{intent_name}.{slot_name} needs reply samples"
    dialog_intents = {item["name"]: item for item in model["dialog"]["intents"]}
    for intent_name, dialog_intent in dialog_intents.items():
        language_slots = {
            item["name"]: item["type"] for item in intents[intent_name].get("slots", [])
        }
        for dialog_slot in dialog_intent["slots"]:
            assert dialog_slot["type"] == language_slots[dialog_slot["name"]]
    assert dialog_intents["PlayByCreatorIntent"]["slots"][0]["elicitationRequired"] is True
    assert dialog_intents["ClarifySelectionIntent"]["slots"][0]["elicitationRequired"] is True


def test_talking_newspaper_language_model_has_safe_source_phrases_and_synonyms():
    language_model = _model()["interactionModel"]["languageModel"]
    intents = {item["name"]: item for item in language_model["intents"]}
    types = {item["name"]: item for item in language_model["types"]}
    organization_samples = set(intents["PlayByOrganizationIntent"]["samples"])
    newspaper = next(
        item
        for item in types["ContentFormat"]["values"]
        if item["name"]["value"] == "newspaper"
    )
    assert {
        "play from talking news",
        "play from a talking paper",
        "play from an audio newspaper",
    }.issubset(organization_samples)
    assert {
        "talking newspaper",
        "talking news",
        "talking paper",
        "audio newspaper",
    }.issubset(set(newspaper["name"]["synonyms"]))
    assert "top english paper" not in newspaper["name"]["synonyms"]


def test_publication_choice_navigation_has_forward_and_back_phrases():
    intents = {
        item["name"]: item for item in _model()["interactionModel"]["languageModel"]["intents"]
    }
    assert "samples" not in intents["AMAZON.NextIntent"]
    assert "samples" not in intents["AMAZON.PreviousIntent"]
    assert {"next choices", "show next choices", "more choices"}.issubset(
        set(intents["ShowMoreBrowseIntent"]["samples"])
    )
    assert {
        "more publication",
        "more publications",
        "show more publication",
        "show more publication choices",
    }.issubset(set(intents["ShowMoreBrowseIntent"]["samples"]))
    assert {
        "previous publication choices",
        "show earlier publications",
        "go back to previous choices",
    }.issubset(
        set(intents["ShowPreviousBrowseIntent"]["samples"])
    )
    assert {
        "something else",
        "none of these",
        "go back to search",
        "I don't want any of these",
    }.issubset(set(intents["DismissChoicesIntent"]["samples"]))


def test_generated_domain_slots_have_id_free_backend_replaceable_values():
    types = {
        item["name"]: item
        for item in _model()["interactionModel"]["languageModel"]["types"]
    }
    generated = {
        "HEAR_LOCATION",
        "HEAR_ORGANIZATION",
        "HEAR_CREATOR",
        "HEAR_TOPIC",
    }
    assert generated.issubset(types)
    assert "HEAR_SEARCH_QUERY" not in types
    for slot_name in generated:
        assert types[slot_name]["values"]
        assert all("id" not in item for item in types[slot_name]["values"])
        assert all(item["name"]["value"].strip() for item in types[slot_name]["values"])


def test_backend_domain_slot_schema_forbids_value_ids():
    schema = json.loads(
        (Path(__file__).parents[1] / "schemas" / "alexa-search-slot.schema.json").read_text(
            encoding="utf-8"
        )
    )
    slot_names = [
        item["properties"]["name"]["const"]
        for item in (
            schema["$defs"]["locationSlot"],
            schema["$defs"]["organizationSlot"],
            schema["$defs"]["creatorSlot"],
            schema["$defs"]["topicSlot"],
        )
    ]
    value_schema = schema["$defs"]["baseSlot"]["properties"]["values"]["items"]
    assert slot_names == [
        "HEAR_LOCATION",
        "HEAR_ORGANIZATION",
        "HEAR_CREATOR",
        "HEAR_TOPIC",
    ]
    assert value_schema["additionalProperties"] is False
    assert set(value_schema["properties"]) == {"name"}


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


def test_active_audio_commands_include_natural_speed_and_rating_phrases():
    intents = {
        item["name"]: item for item in _model()["interactionModel"]["languageModel"]["intents"]
    }
    assert {"play fast", "play this fast"}.issubset(
        set(intents["IncreaseSpeedIntent"]["samples"])
    )
    assert {"play slow", "play this slow"}.issubset(
        set(intents["DecreaseSpeedIntent"]["samples"])
    )
    assert "double speed" not in intents["IncreaseSpeedIntent"]["samples"]
    assert "half speed" not in intents["DecreaseSpeedIntent"]["samples"]
    assert "{speed} speed" in intents["SetPlaybackSpeedIntent"]["samples"]
    assert {
        "rate this content",
        "rate this recording",
        "give feedback",
        "leave feedback on this content",
        "rate what I'm listening to",
        "score this recording",
    }.issubset(
        set(intents["RateContentIntent"]["samples"])
    )


def test_all_backend_playback_intents_are_declared_in_the_language_model():
    intents = {
        item["name"] for item in _model()["interactionModel"]["languageModel"]["intents"]
    }
    assert {
        "AMAZON.PauseIntent",
        "AMAZON.ResumeIntent",
        "AMAZON.NextIntent",
        "AMAZON.PreviousIntent",
        "AMAZON.RepeatIntent",
        "AMAZON.StartOverIntent",
        "AMAZON.StopIntent",
        "RewindIntent",
        "FastForwardIntent",
        "IncreaseSpeedIntent",
        "DecreaseSpeedIntent",
        "SetPlaybackSpeedIntent",
    }.issubset(intents)


def test_rating_and_reporting_use_distinct_asr_friendly_phrases():
    intents = {
        item["name"]: item for item in _model()["interactionModel"]["languageModel"]["intents"]
    }
    rating = set(intents["RateContentIntent"]["samples"])
    reporting = set(intents["ReportContentIntent"]["samples"])
    assert not rating.intersection(reporting)
    assert {"report", "report this"}.isdisjoint(reporting)
    assert {
        "report this content as inappropriate",
        "flag this recording as inappropriate",
        "report a safety issue",
    }.issubset(reporting)
    assert "this is wrong" not in reporting


def test_feedback_and_follow_samples_do_not_claim_ambiguous_actions():
    intents = {
        item["name"]: item for item in _model()["interactionModel"]["languageModel"]["intents"]
    }
    skip_feedback = set(intents["SkipFeedbackIntent"]["samples"])
    negative = set(intents["FeedbackNotEnjoyedIntent"]["samples"])
    follow = set(intents["FollowCreatorIntent"]["samples"])
    assert {"skip", "move on", "carry on", "just play the next one"}.isdisjoint(skip_feedback)
    assert "change it" not in negative
    assert {"I like this creator", "I love this creator", "I want to hear more from them"}.isdisjoint(follow)
