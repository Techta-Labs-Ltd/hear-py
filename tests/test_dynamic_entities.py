from src.utils.dynamic_entities import build_ambiguity_dynamic_entities_directive


def test_ambiguity_dynamic_entities_include_unique_names_and_suffixes():
    directive = build_ambiguity_dynamic_entities_directive([{
        "type": "creator",
        "id": "creator-leader",
        "name": "Pendle Voice Leader and Times",
    }, {
        "type": "creator",
        "id": "creator-dalesman",
        "name": "Pendle Voice Dalesman",
    }, {
        "type": "organization",
        "id": "org-leader",
        "name": "Pendle Voice Leader and Times",
    }])

    assert directive["type"] == "Dialog.UpdateDynamicEntities"
    assert directive["updateBehavior"] == "REPLACE"
    values = directive["types"][0]["values"]
    assert [value["name"]["value"] for value in values] == [
        "Pendle Voice Leader and Times",
        "Pendle Voice Dalesman",
    ]
    assert values[0]["name"]["synonyms"] == [
        "Leader and Times", "first", "one", "number one",
    ]
    assert values[1]["name"]["synonyms"] == [
        "Dalesman", "second", "two", "number two",
    ]
