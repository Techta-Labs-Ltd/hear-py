from src.alexa.entities import AlexaEntities
from src.constants.discovery import DiscoveryConstants


def test_ambiguity_dynamic_entities_include_unique_names_and_suffixes():
    directive = AlexaEntities.build_ambiguity_dynamic_entities_directive(
        [
            {
                "type": "creator",
                "id": "creator-leader",
                "name": "Pendle Voice Leader and Times",
            },
            {
                "type": "creator",
                "id": "creator-dalesman",
                "name": "Pendle Voice Dalesman",
            },
            {
                "type": "organization",
                "id": "org-leader",
                "name": "Pendle Voice Leader and Times",
            },
        ]
    )
    assert directive["type"] == "Dialog.UpdateDynamicEntities"
    assert directive["updateBehavior"] == "REPLACE"
    values = directive["types"][0]["values"]
    assert [value["name"]["value"] for value in values] == [
        "Pendle Voice Leader and Times",
        "Pendle Voice Dalesman",
    ]
    assert values[0]["name"]["synonyms"] == [
        "Leader and Times",
        *DiscoveryConstants.CHOICE_ORDINAL_SYNONYMS[0],
    ]
    assert values[1]["name"]["synonyms"] == [
        "Dalesman",
        *DiscoveryConstants.CHOICE_ORDINAL_SYNONYMS[1],
    ]


def test_feedback_dynamic_entities_cover_each_feedback_outcome():
    directive = AlexaEntities.build_feedback_dynamic_entities_directive()

    assert directive["type"] == "Dialog.UpdateDynamicEntities"
    assert directive["updateBehavior"] == "REPLACE"
    assert directive["types"][0]["name"] == "HEAR_FEEDBACK"
    values = directive["types"][0]["values"]
    assert [value["id"] for value in values] == [
        "enjoyed",
        "somewhat",
        "not-enjoyed",
    ]
    assert "I enjoyed it" in values[0]["name"]["synonyms"]
    assert "not for me" in values[2]["name"]["synonyms"]
