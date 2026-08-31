from __future__ import annotations


class RequestContext:
    _GRANTED_STATUS: str = "GRANTED"

    @staticmethod
    def get_request_id(handler_input) -> str:
        try:
            return str(handler_input.request_envelope.request.requestId or "")
        except Exception:
            return ""

    @staticmethod
    def get_system_context(handler_input):
        try:
            return handler_input.request_envelope.context.System
        except Exception:
            return None

    @staticmethod
    def has_permission(handler_input, scope: str) -> bool:
        system = RequestContext.get_system_context(handler_input)
        try:
            scopes = system.user.permissions.scopes
            return (scopes or {}).get(scope, {}).get("status") == RequestContext._GRANTED_STATUS
        except Exception:
            return False

    @staticmethod
    def get_geolocation(handler_input) -> dict | None:
        try:
            geolocation = handler_input.request_envelope.context.Geolocation
        except Exception:
            return None
        if not geolocation or not geolocation.coordinate:
            return None
        return {
            "latitude": geolocation.coordinate.latitudeInDegrees,
            "longitude": geolocation.coordinate.longitudeInDegrees,
            "accuracy": geolocation.coordinate.accuracyInMeters,
            "timestamp": geolocation.timestamp,
        }

    @staticmethod
    def request(handler_input) -> dict:
        manager = handler_input.attributes_manager
        if hasattr(manager, "request_attributes"):
            return manager.request_attributes
        return manager.get_request_attributes()

    @staticmethod
    def replace_request(handler_input, attributes: dict) -> dict:
        value = attributes if attributes is not None else {}
        manager = handler_input.attributes_manager
        if hasattr(manager, "set_request_attributes"):
            manager.set_request_attributes(value)
        else:
            manager.request_attributes = value
        return value

    @staticmethod
    def session(handler_input) -> dict:
        return handler_input.attributes_manager.get_session_attributes() or {}

    @staticmethod
    def replace_session(handler_input, attributes: dict) -> dict:
        value = attributes if attributes is not None else {}
        handler_input.attributes_manager.set_session_attributes(value)
        return value

    @staticmethod
    def value(handler_input, key: str, default=None):
        return RequestContext.request(handler_input).get(key, default)

    @staticmethod
    def set_value(handler_input, key: str, value):
        attributes = RequestContext.request(handler_input)
        attributes[key] = value
        RequestContext.replace_request(handler_input, attributes)
        return value

    @staticmethod
    def pop(handler_input, key: str, default=None):
        attributes = RequestContext.request(handler_input)
        value = attributes.pop(key, default)
        RequestContext.replace_request(handler_input, attributes)
        return value
