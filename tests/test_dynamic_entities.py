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
