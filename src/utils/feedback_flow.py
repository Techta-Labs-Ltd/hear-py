from __future__ import annotations

from src.utils.speech import ssml, IDLE_NEXT_REPROMPT


def idle_next_response(handler_input, speak_text: str, reprompt_text: str | None = None):
    """Build a response that keeps the session open with an idle next prompt."""
    return handler_input.response_builder \
        .speak(ssml(speak_text)) \
        .reprompt(ssml(reprompt_text or IDLE_NEXT_REPROMPT)) \
        .set_should_end_session(False) \
        .response
