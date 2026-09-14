from pathlib import Path

p = Path("tests/test_resolver_dispatch_routing.py")
text = p.read_text(encoding="utf-8")

new_test = """

@pytest.mark.asyncio
async def test_ambiguity_turn_2_ordinal_selection_resolves_candidate(mock_handler_input):
    candidates = [
        {"id": "creator-1", "name": "Pendle Voice Dalesman", "type": "creator"},
        {"id": "creator-2", "name": "Pendle Voice Lancashire Life", "type": "creator"},
        {"id": "creator-3", "name": "Pendle Voice Leader and Times", "type": "creator"},
    ]
    nlp_data = {
        "status": "ambiguous",
        "intent": "creator",
        "ambiguities": [{"phrase": "pendle voice", "candidates": candidates}],
        "slots": {},
    }
    mock_handler_input.attributes_manager.request_attributes["_nlp"] = nlp_data
    container = ApplicationContainer()
    gate = IntentDispatchGateHandler(deps=container)
    turn1_res = gate.handle(mock_handler_input)
    assert "outputSpeech" in turn1_res

    store = User.snapshot(mock_handler_input)
    assert store.get("pendingAmbiguity") is not None
    assert store["pendingAmbiguity"]["expiresAt"] > 0

    envelope2 = AttrDict(
        {
            "version": "1.0",
            "context": {"System": {"user": {"userId": "test-alexa-user-123"}}},
            "request": {
                "type": "IntentRequest",
                "locale": "en-GB",
                "intent": {
                    "name": "ClarifySelectionIntent",
                    "slots": {"selection": {"name": "selection", "value": "second"}},
                },
            },
        }
    )
    attributes2 = AttributesManager(envelope2)
    attributes2.request_attributes = {
        "_store": dict(store),
        "_dirty": False,
    }
    hi2 = HandlerInput(envelope2, attributes2, None, ResponseBuilder())

    await ResolverInterceptor(deps=container).process(hi2)
    nlp2 = hi2.attributes_manager.request_attributes.get("_nlp")
    assert nlp2 is not None
    assert nlp2["status"] == "resolved"
    assert nlp2["intent"] == "creator"
    assert nlp2["slots"]["creatorIds"] == ["creator-2"]
    assert nlp2["slots"]["creatorName"] == "Pendle Voice Lancashire Life"
    assert User.snapshot(hi2).get("pendingAmbiguity") is None
"""

assert "test_ambiguity_turn_2_ordinal_selection_resolves_candidate" not in text
new_text = text.rstrip() + new_test + "\n"
p.write_text(new_text, encoding="utf-8")
print("Updated tests/test_resolver_dispatch_routing.py successfully")
