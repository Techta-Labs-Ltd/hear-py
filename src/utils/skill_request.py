"""Extract Alexa request type and intent name from handler_input."""


def _read(value, *names):
    for name in names:
        if isinstance(value, dict) and name in value:
            return value.get(name)
        if value is not None and hasattr(value, name):
            return getattr(value, name)
    return None


def _non_empty_string(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


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


def get_resolved_slot_value(slot) -> str | None:
    """Prefer Alexa's canonical entity match, then fall back to spoken text."""
    resolutions = _read(slot, "resolutions")
    authorities = _read(
        resolutions, "resolutionsPerAuthority", "resolutions_per_authority"
    ) or []
    for authority in authorities:
        status = _read(_read(authority, "status"), "code")
        if status and status != "ER_SUCCESS_MATCH":
            continue
        for item in _read(authority, "values") or []:
            canonical = _non_empty_string(_read(_read(item, "value"), "name"))
            if canonical:
                return canonical
    return _non_empty_string(_read(slot, "value"))


def get_resolved_slot_id(slot) -> str | None:
    """Return Alexa's matched entity ID without falling back to spoken text."""
    resolutions = _read(slot, "resolutions")
    authorities = _read(
        resolutions, "resolutionsPerAuthority", "resolutions_per_authority"
    ) or []
    for authority in authorities:
        status = _read(_read(authority, "status"), "code")
        if status and status != "ER_SUCCESS_MATCH":
            continue
        for item in _read(authority, "values") or []:
            entity_id = _non_empty_string(_read(_read(item, "value"), "id"))
            if entity_id:
                return entity_id
    return None


def get_user_id(handler_input) -> str | None:
    """Extract the Alexa user ID from raw JSON or ASK SDK request models."""
    envelope = getattr(handler_input, "request_envelope", None)
    context = _read(envelope, "context")
    system = _read(context, "System", "system")
    user = _read(system, "user")
    user_id = _non_empty_string(_read(user, "userId", "user_id"))
    if user_id:
        return user_id
    session = _read(envelope, "session")
    session_user = _read(session, "user")
    return _non_empty_string(_read(session_user, "userId", "user_id"))


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
