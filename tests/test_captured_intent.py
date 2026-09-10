from __future__ import annotations

import pytest

from src.alexa.captured_intent import CapturedIntentRouter
from src.alexa.runtime import AttrDict


@pytest.mark.parametrize(
    ("phrase", "intent_name", "slots"),
    [
        ("help", "AMAZON.HelpIntent", {}),
        ("what's trending", "WhatsTrendingIntent", {}),
        (
            "play from a creator",
            "ChooseSourceKindIntent",
            {"sourceKind": "creator"},
        ),
        (
            "play a publication",
            "ChooseSourceKindIntent",
            {"sourceKind": "publication"},
        ),
        (
            "play the latest publication",
            "PlayPublicationIntent",
            {"publicationSort": "latest"},
        ),
        (
            "set my location to Bristol",
            "SearchLocationIntent",
            {"searchQuery": "Bristol"},
        ),
        (
            "play content by Unknown Reader",
            "SearchCreatorIntent",
            {"searchQuery": "Unknown Reader"},
        ),
        (
            "play Liverpool",
            "SearchContentIntent",
            {"searchQuery": "Liverpool"},
        ),
    ],
)
def test_captured_command_reuses_the_existing_interaction_model(phrase, intent_name, slots):
    route = CapturedIntentRouter.resolve(phrase)

    assert route["name"] == intent_name
    assert {name: slot["value"] for name, slot in route["slots"].items()} == slots


@pytest.mark.parametrize("phrase", ["Liverpool", "Orion Meta Glasses", "Unknown title"])
def test_bare_discovery_text_is_not_reclassified_locally(phrase):
    assert CapturedIntentRouter.resolve(phrase) is None


def test_router_restores_a_command_captured_by_the_open_search_dialog(mock_handler_input):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "dialogState": "IN_PROGRESS",
            "intent": {
                "name": "SearchContentIntent",
                "slots": {
                    "searchQuery": {
                        "name": "searchQuery",
                        "value": "play from a creator",
                    }
                },
            },
        }
    )

    CapturedIntentRouter.apply(mock_handler_input)

    request = mock_handler_input.request_envelope.request
    assert request.dialogState == "COMPLETED"
    assert request.intent["name"] == "ChooseSourceKindIntent"
    assert request.intent["slots"]["sourceKind"]["value"] == "creator"


def test_router_leaves_bare_discovery_for_the_resolver(mock_handler_input):
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "dialogState": "IN_PROGRESS",
            "intent": {
                "name": "SearchContentIntent",
                "slots": {
                    "searchQuery": {"name": "searchQuery", "value": "Liverpool"}
                },
            },
        }
    )

    CapturedIntentRouter.apply(mock_handler_input)

    request = mock_handler_input.request_envelope.request
    assert request.dialogState == "IN_PROGRESS"
    assert request.intent["name"] == "SearchContentIntent"
    assert request.intent["slots"]["searchQuery"]["value"] == "Liverpool"
