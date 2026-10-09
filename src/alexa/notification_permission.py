from __future__ import annotations

import time

import config.permission_scopes as permission_scopes
from src.alexa.context import RequestContext
from src.alexa.response import AlexaResponse
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml


class NotificationPermissionPrompt:
    REPEAT_AFTER_SECONDS = 30 * 86400

    @staticmethod
    def granted(handler_input) -> bool:
        return RequestContext.has_permission(handler_input, permission_scopes.NOTIFICATIONS_WRITE)

    @staticmethod
    def due(handler_input, store: dict) -> bool:
        if NotificationPermissionPrompt.granted(handler_input):
            return False
        prompted_at = int(store.get("notificationPermissionPromptedAt") or 0)
        return int(time.time()) - prompted_at >= NotificationPermissionPrompt.REPEAT_AFTER_SECONDS

    @staticmethod
    def respond(handler_input, user, speech: str, reprompt: str):
        user.update(
            handler_input,
            {"notificationPermissionPromptedAt": int(time.time()), "_requiresReliableSave": True},
        )
        return (
            handler_input.response_builder.speak(Ssml.ssml(speech))
            .reprompt(Ssml.ssml(reprompt))
            .with_ask_for_permissions_consent_card([permission_scopes.NOTIFICATIONS_WRITE])
            .add_directive(AlexaResponse.discovery_capture_directive())
            .set_should_end_session(False)
            .response
        )

    @staticmethod
    def after_follow(handler_input, user, source_name: str):
        speech = (
            f"{Speech.FOLLOW_CREATOR_ACK(source_name)} "
            f"{Speech.NOTIFICATION_PERMISSION_AFTER_FOLLOW} "
            "What would you like to listen to next?"
        )
        return NotificationPermissionPrompt.respond(
            handler_input, user, speech, Speech.WELCOME_REPROMPT
        )
