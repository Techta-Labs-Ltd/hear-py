import asyncio
from unittest.mock import AsyncMock

from src.controllers.link_phone import LinkPhoneHandler, LinkPhoneSpeech


def _intent(handler_input):
    handler_input.request_envelope["request"] = {
        "type": "IntentRequest",
        "intent": {"name": "LinkPhoneIntent", "slots": {}},
    }
    builder = handler_input.response_builder
    builder.speak.return_value = builder
    builder.with_simple_card.return_value = builder
    builder.set_should_end_session.return_value = builder
    return handler_input


def test_link_my_phone_reads_out_the_code_twice(mock_handler_input):
    handler_input = _intent(mock_handler_input)
    client = AsyncMock()
    client.create_link_code.return_value = {"code": "042917", "expiresInSeconds": 600}
    handler = LinkPhoneHandler(lambda _input: client)

    assert handler.can_handle(handler_input)
    asyncio.run(handler.handle(handler_input))

    spoken = handler_input.response_builder.speak.call_args.args[0]
    assert spoken.count('<say-as interpret-as="digits">042917</say-as>') == 2
    assert "say link Alexa" in spoken
    assert "ten minutes" in spoken
    card = handler_input.response_builder.with_simple_card.call_args.args
    assert card[0] == LinkPhoneSpeech.CARD_TITLE and "042917" in card[1]


def test_link_my_phone_says_so_when_no_code_comes_back(mock_handler_input):
    handler_input = _intent(mock_handler_input)
    client = AsyncMock()
    client.create_link_code.return_value = None

    asyncio.run(LinkPhoneHandler(lambda _input: client).handle(handler_input))

    spoken = handler_input.response_builder.speak.call_args.args[0]
    assert LinkPhoneSpeech.FAILED in spoken
