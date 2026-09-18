from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractRequestHandler

from src.alexa.permission import Permission
from src.alexa.request import AlexaRequest
from src.models.permission_policy import PermissionResumeCommand


class PermissionResumeRequestAdapter:
    @staticmethod
    def command(handler_input) -> PermissionResumeCommand:
        request = getattr(handler_input.request_envelope, "request", {}) or {}
        cause = (
            request.get("cause", {})
            if isinstance(request, dict)
            else getattr(request, "cause", {})
        )
        token = cause.get("token", "") if isinstance(cause, dict) else getattr(cause, "token", "")
        result = cause.get("result", {}) if isinstance(cause, dict) else getattr(cause, "result", {})
        status = result.get("status", "") if isinstance(result, dict) else getattr(result, "status", "")
        connection = cause.get("status", {}) if isinstance(cause, dict) else getattr(cause, "status", {})
        code = connection.get("code", "") if isinstance(connection, dict) else getattr(connection, "code", "")
        return PermissionResumeCommand(
            purpose=str(token or ""),
            status=str(status or ""),
            connection_code=str(code or ""),
        )


class PermissionResumeHandler(AbstractRequestHandler):
    def __init__(self, permission: Permission) -> None:
        self._permission = permission

    def can_handle(self, handler_input) -> bool:
        return AlexaRequest.get_request_type(handler_input) == "SessionResumedRequest"

    async def handle(self, handler_input):
        return await self._permission.resume(
            handler_input,
            PermissionResumeRequestAdapter.command(handler_input),
        )


class SetUpAccountHandler(AbstractRequestHandler):
    def __init__(self, permission: Permission) -> None:
        self._permission = permission

    def can_handle(self, handler_input) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input) == "SetUpAccountIntent"
        )

    async def handle(self, handler_input):
        return self._permission.ask_profile_setup(handler_input)
