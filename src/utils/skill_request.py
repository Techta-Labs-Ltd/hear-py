"""Extract Alexa request type and intent name from handler_input."""


def get_request_type(handler_input) -> str:
    """Extract the Alexa request type from the handler input."""
    envelope = getattr(handler_input, "request_envelope", {}) or {}
    request = envelope.get("request", {})
    return request.get("type", "")


def get_intent_name(handler_input) -> str | None:
    """Extract the Alexa intent name from the handler input."""
    envelope = getattr(handler_input, "request_envelope", {}) or {}
    request = envelope.get("request", {})
    intent = request.get("intent")
    return intent.get("name") if intent else None
