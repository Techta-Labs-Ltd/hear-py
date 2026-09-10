from __future__ import annotations

from datetime import datetime

from src.utils.filters import SearchFilterUtils


class AlexaRequest:
    @staticmethod
    def read(value, *names):
        for name in names:
            if isinstance(value, dict) and name in value:
                return value.get(name)
            if value is not None and hasattr(value, name):
                return getattr(value, name)
        return None

    @staticmethod
    def _non_empty_string(value) -> str | None:
        if not isinstance(value, str):
            return None
        value = value.strip()
        return value or None

    @staticmethod
    def get_request_type(handler_input) -> str:
        """Extract the Alexa request type from the handler input."""
        envelope = getattr(handler_input, "request_envelope", {}) or {}
        request = envelope.get("request", {})
        return request.get("type", "")

    @staticmethod
    def get_request_id(handler_input) -> str | None:
        envelope = getattr(handler_input, "request_envelope", {}) or {}
        request = envelope.get("request", {})
        return AlexaRequest._non_empty_string(request.get("requestId"))

    @staticmethod
    def get_request_timestamp_ms(handler_input) -> int | None:
        envelope = getattr(handler_input, "request_envelope", {}) or {}
        request = envelope.get("request", {})
        timestamp = AlexaRequest._non_empty_string(request.get("timestamp"))
        if not timestamp:
            return None
        try:
            return int(datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp() * 1000)
        except ValueError:
            return None

    @staticmethod
    def get_intent_name(handler_input) -> str | None:
        """Extract the Alexa intent name from the handler input."""
        envelope = getattr(handler_input, "request_envelope", {}) or {}
        request = envelope.get("request", {})
        intent = request.get("intent")
        return intent.get("name") if intent else None

    @staticmethod
    def get_resolved_slot_value(slot) -> str | None:
        """Prefer Alexa's canonical entity match, then fall back to spoken text."""
        resolutions = AlexaRequest.read(slot, "resolutions")
        authorities = (
            AlexaRequest.read(resolutions, "resolutionsPerAuthority", "resolutions_per_authority")
            or []
        )
        for authority in authorities:
            status = AlexaRequest.read(AlexaRequest.read(authority, "status"), "code")
            if status and status != "ER_SUCCESS_MATCH":
                continue
            for item in AlexaRequest.read(authority, "values") or []:
                canonical = AlexaRequest._non_empty_string(
                    AlexaRequest.read(AlexaRequest.read(item, "value"), "name")
                )
                if canonical:
                    return canonical
        return AlexaRequest._non_empty_string(AlexaRequest.read(slot, "value"))

    @staticmethod
    def get_resolved_slot_id(slot) -> str | None:
        """Return Alexa's matched entity ID without falling back to spoken text."""
        resolutions = AlexaRequest.read(slot, "resolutions")
        authorities = (
            AlexaRequest.read(resolutions, "resolutionsPerAuthority", "resolutions_per_authority")
            or []
        )
        for authority in authorities:
            status = AlexaRequest.read(AlexaRequest.read(authority, "status"), "code")
            if status and status != "ER_SUCCESS_MATCH":
                continue
            for item in AlexaRequest.read(authority, "values") or []:
                entity_id = AlexaRequest._non_empty_string(
                    AlexaRequest.read(AlexaRequest.read(item, "value"), "id")
                )
                if entity_id:
                    return entity_id
        return None

    @staticmethod
    def get_slot_value(handler_input, slot_name: str) -> str | None:
        envelope = getattr(handler_input, "request_envelope", None)
        request = AlexaRequest.read(envelope, "request")
        intent = AlexaRequest.read(request, "intent")
        slots = AlexaRequest.read(intent, "slots") or {}
        slot = AlexaRequest.read(slots, slot_name)
        return AlexaRequest.get_resolved_slot_value(slot)

    @staticmethod
    def get_topic_slot(handler_input) -> str:
        return (
            AlexaRequest.get_slot_value(handler_input, "topic")
            or AlexaRequest.get_slot_value(handler_input, "category")
            or ""
        )

    @staticmethod
    def get_search_query(handler_input) -> str:
        intent_name = AlexaRequest.get_intent_name(handler_input) or ""
        creator = AlexaRequest.get_slot_value(handler_input, "creatorQuery") or ""
        if creator:
            return SearchFilterUtils.strip_conversational_topic_prefix(
                SearchFilterUtils._normalize_search_query_for_creator(creator)
            )
        if intent_name == "PlayByCreatorIntent":
            topic_as_creator = AlexaRequest.get_slot_value(handler_input, "topic") or ""
            if topic_as_creator:
                return SearchFilterUtils.strip_conversational_topic_prefix(
                    SearchFilterUtils._normalize_search_query_for_creator(topic_as_creator)
                )
        organization = AlexaRequest.get_slot_value(handler_input, "organizationQuery") or ""
        if organization:
            return SearchFilterUtils.strip_conversational_topic_prefix(
                SearchFilterUtils._normalize_search_query_for_creator(organization)
            )
        topic = AlexaRequest.get_topic_slot(handler_input)
        if topic:
            parsed = SearchFilterUtils.parse_topic_for_search(topic)
            return SearchFilterUtils._normalize_search_query_for_creator(parsed["q"])
        return ""

    @staticmethod
    def raw_search_phrase(handler_input) -> str:
        return AlexaRequest.get_slot_value(
            handler_input, "creatorQuery"
        ) or AlexaRequest.get_topic_slot(handler_input)

    @staticmethod
    def wants_local_community_content(handler_input, search_query: str = "") -> bool:
        return SearchFilterUtils.wants_local_community_content(
            search_query,
            AlexaRequest.get_topic_slot(handler_input),
            AlexaRequest.get_slot_value(handler_input, "category") or "",
        )

    @staticmethod
    def wants_play_from_followed_creators(handler_input, text_override: str = "") -> bool:
        text = (
            text_override
            or AlexaRequest.get_search_query(handler_input)
            or AlexaRequest.raw_search_phrase(handler_input)
        )
        return SearchFilterUtils.wants_play_from_followed_creators(text)

    @staticmethod
    def get_user_id(handler_input) -> str | None:
        """Extract the Alexa user ID from raw JSON or ASK SDK request models."""
        envelope = getattr(handler_input, "request_envelope", None)
        context = AlexaRequest.read(envelope, "context")
        system = AlexaRequest.read(context, "System", "system")
        user = AlexaRequest.read(system, "user")
        user_id = AlexaRequest._non_empty_string(AlexaRequest.read(user, "userId", "user_id"))
        if user_id:
            return user_id
        session = AlexaRequest.read(envelope, "session")
        session_user = AlexaRequest.read(session, "user")
        return AlexaRequest._non_empty_string(AlexaRequest.read(session_user, "userId", "user_id"))

    @staticmethod
    def get_audio_player_token(handler_input) -> str:
        """Read an AudioPlayer token from raw JSON or an ASK SDK request model."""
        request = handler_input.request_envelope.request
        if isinstance(request, dict):
            return str(request.get("token") or "")
        return str(getattr(request, "token", "") or "")

    @staticmethod
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
