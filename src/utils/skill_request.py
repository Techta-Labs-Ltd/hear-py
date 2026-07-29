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


def get_user_id(handler_input) -> str | None:
    """Extract the Alexa user ID from the request context."""
    try:
        ctx = handler_input.request_envelope.context
    except Exception:
        return None
    if ctx and getattr(ctx, "System", None) and ctx.System.user:
        return ctx.System.user.userId
    return None


def get_audio_player_token(handler_input) -> str:
    """Read an AudioPlayer token from raw JSON or an ASK SDK request model."""
    request = handler_input.request_envelope.request
    if isinstance(request, dict):
        return str(request.get("token") or "")
    return str(getattr(request, "token", "") or "")


def get_audio_player_offset_ms(handler_input) -> int:
    """Read Alexa's camel-case offset while remaining ASK SDK compatible."""
    request = handler_input.request_envelope.request
    if isinstance(request, dict):
        value = request.get("offsetInMilliseconds")
        if value is None:
            value = request.get("offset_in_milliseconds")
    else:
        value = getattr(request, "offset_in_milliseconds", None)
        if value is None:
            value = getattr(request, "offsetInMilliseconds", None)
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
