from __future__ import annotations

import pytest

from scripts.apply_alexa_slot_lexicon import AlexaSlotLexicon


def test_all_generated_domain_slots_are_validated():
    assert AlexaSlotLexicon.SLOT_NAMES == (
        "HEAR_LOCATION",
        "HEAR_ORGANIZATION",
        "HEAR_TOPIC",
    )


def test_generic_source_kinds_are_rejected_from_topic_slot():
    with pytest.raises(ValueError, match="generic source kinds"):
        AlexaSlotLexicon._validate(
            [["Talking Newspaper", "", "talking news"]],
            "HEAR_TOPIC",
        )


def test_cross_slot_phrase_collision_must_be_explicitly_allowed():
    slots = {
        "HEAR_ORGANIZATION": [["York", "", "York Talking News"]],
        "HEAR_LOCATION": [["York", "", "City of York"]],
    }
    with pytest.raises(ValueError, match="Cross-slot phrase collisions"):
        AlexaSlotLexicon._validate_cross_slot(slots, set())
    AlexaSlotLexicon._validate_cross_slot(slots, {"york"})
