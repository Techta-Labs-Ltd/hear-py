from __future__ import annotations

from src.alexa.request import AlexaRequest


def intent_slots(handler_input) -> dict:
    request = AlexaRequest.read(handler_input.request_envelope, "request")
    intent = AlexaRequest.read(request, "intent")
    if not intent:
        return {}
    slots = intent.get("slots") if hasattr(intent, "get") else None
    return slots or AlexaRequest.read(intent, "slots") or {}
