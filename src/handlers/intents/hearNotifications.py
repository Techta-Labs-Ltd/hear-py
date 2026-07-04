from __future__ import annotations

import logging
from typing import Any, Dict

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput
from src.webhooks.notification_webhook import check_notifications
from src.services.persistence import get_store, update_store
from src.utils.skill_request import get_request_type, get_intent_name
from src.utils.speech import (
    ssml, NO_NOTIFICATIONS_ENABLED, NO_PENDING_NOTIFICATIONS,
    NOTIFICATIONS_SUMMARY, NOTIFICATIONS_QUEUE_PROMPT,
)
from src.utils.feedback_gate import enforce_interaction_gate

logger = logging.getLogger(__name__)


class HearNotificationsHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "HearNotificationsIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        gated = enforce_interaction_gate(handler_input)
        if gated:
            return gated

        store = get_store(handler_input)
        user_id = handler_input.request_envelope.context.system.user.user_id \
            if handler_input.request_envelope.context and handler_input.request_envelope.context.system \
            and handler_input.request_envelope.context.system.user else None

        if not store.get("notificationsEnabled"):
            return handler_input.response_builder \
                .speak(ssml(NO_NOTIFICATIONS_ENABLED)) \
                .reprompt(ssml("Say enable notifications to turn them on, or ask me to play something.")) \
                .set_should_end_session(False) \
                .response

        try:
            tracks = await check_notifications(user_id)
        except Exception:
            tracks = []

        if not tracks:
            return handler_input.response_builder \
                .speak(ssml(NO_PENDING_NOTIFICATIONS)) \
                .reprompt(ssml("What would you like to listen to?")) \
                .set_should_end_session(False) \
                .response

        summary = NOTIFICATIONS_SUMMARY(tracks)
        prompt = NOTIFICATIONS_QUEUE_PROMPT

        update_store(handler_input, {"pendingNotificationQueue": tracks})

        return handler_input.response_builder \
            .speak(ssml(summary + " " + prompt)) \
            .reprompt(ssml("Would you like me to queue them for you?")) \
            .set_should_end_session(False) \
            .response
