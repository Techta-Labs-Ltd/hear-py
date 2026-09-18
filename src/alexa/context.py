from __future__ import annotations

from typing import Any


class RequestContext:
    """The one transient gateway for a single Alexa invocation.

    The context retains references to the SDK-owned request/session maps. It
    therefore never creates a second mutable copy of persistent listener state.
    Existing static helpers are retained only as Alexa-bound adapters while
    feature slices move to receiving this object directly.
    """

    __slots__ = ("_handler_input",)

    _GRANTED_STATUS: str = "GRANTED"

    def __init__(self, handler_input) -> None:
        self._handler_input = handler_input

    @classmethod
    def bind(cls, handler_input) -> "RequestContext":
        current = getattr(handler_input, "request_context", None)
        if isinstance(current, cls) and current._handler_input is handler_input:
            return current
        current = cls(handler_input)
        try:
            handler_input.request_context = current
        except Exception:
            pass
        return current

    @property
    def handler_input(self):
        return self._handler_input

    @property
    def request_id(self) -> str:
        envelope = getattr(self._handler_input, "request_envelope", {}) or {}
        request = (
            envelope.get("request", {})
            if isinstance(envelope, dict)
            else getattr(envelope, "request", {})
        )
        value = request.get("requestId") if isinstance(request, dict) else getattr(request, "requestId", None)
        return str(value or "")

    @property
    def system(self):
        envelope = getattr(self._handler_input, "request_envelope", {}) or {}
        context = (
            envelope.get("context", {})
            if isinstance(envelope, dict)
            else getattr(envelope, "context", {})
        )
        return context.get("System") if isinstance(context, dict) else getattr(context, "System", None)

    @property
    def alexa_user_id(self) -> str:
        try:
            system = self.system
            if system is None:
                return ""
            user = system.get("user") if isinstance(system, dict) else system.user
            if user is None:
                return ""
            value = user.get("userId") if isinstance(user, dict) else user.userId
            return str(value or "")
        except Exception:
            return ""

    @property
    def request_attributes(self) -> dict:
        manager = self._handler_input.attributes_manager
        if hasattr(manager, "request_attributes"):
            return manager.request_attributes
        return manager.get_request_attributes()

    @request_attributes.setter
    def request_attributes(self, attributes: dict) -> None:
        value = attributes if attributes is not None else {}
        manager = self._handler_input.attributes_manager
        if hasattr(manager, "set_request_attributes"):
            manager.set_request_attributes(value)
        else:
            manager.request_attributes = value

    @property
    def session_attributes(self) -> dict:
        return self._handler_input.attributes_manager.get_session_attributes() or {}

    @session_attributes.setter
    def session_attributes(self, attributes: dict) -> None:
        self._handler_input.attributes_manager.set_session_attributes(
            attributes if attributes is not None else {}
        )

    def permission_granted(self, scope: str) -> bool:
        try:
            system = self.system
            if system is None:
                return False
            user = system.get("user") if isinstance(system, dict) else system.user
            if user is None:
                return False
            permissions = user.get("permissions") if isinstance(user, dict) else user.permissions
            if permissions is None:
                return False
            scopes = permissions.get("scopes") if isinstance(permissions, dict) else permissions.scopes
            record = (scopes or {}).get(scope, {})
            if record is None:
                return False
            status = record.get("status") if isinstance(record, dict) else record.status
            return status == self._GRANTED_STATUS
        except Exception:
            return False

    @staticmethod
    def get_request_id(handler_input) -> str:
        return RequestContext.bind(handler_input).request_id

    @staticmethod
    def get_system_context(handler_input):
        return RequestContext.bind(handler_input).system

    @staticmethod
    def has_permission(handler_input, scope: str) -> bool:
        return RequestContext.bind(handler_input).permission_granted(scope)

    @staticmethod
    def request(handler_input) -> dict:
        return RequestContext.bind(handler_input).request_attributes

    @staticmethod
    def replace_request(handler_input, attributes: dict) -> dict:
        context = RequestContext.bind(handler_input)
        context.request_attributes = attributes
        return context.request_attributes

    @staticmethod
    def session(handler_input) -> dict:
        return RequestContext.bind(handler_input).session_attributes

    @staticmethod
    def replace_session(handler_input, attributes: dict) -> dict:
        context = RequestContext.bind(handler_input)
        context.session_attributes = attributes
        return context.session_attributes

    @staticmethod
    def value(handler_input, key: str, default=None):
        return RequestContext.request(handler_input).get(key, default)

    @staticmethod
    def set_value(handler_input, key: str, value: Any):
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
