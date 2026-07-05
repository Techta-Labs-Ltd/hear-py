from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput

from config import settings
from config.permission_scopes import NOTIFICATIONS_WRITE

from src.services.persistence import (
    get_store, update_store, resolve_top_categories, get_browse_catalog,
)
from src.utils.skill_request import get_request_type, get_intent_name
from src.utils.speech import (
    ssml, NOTIFICATION_PERMISSION_REQUEST, NOTIFICATIONS_ENABLE_FAILED,
    NOTIFICATIONS_ENABLED, IDLE_DO_NEXT_REPROMPT, NOTIFICATIONS_DISABLED,
    BROWSE_ACTIVE_NOT_NOTIFICATIONS, WELCOME_REPROMPT, ERROR_GENERIC,
)
from src.utils.feedback_gate import enforce_interaction_gate
from src.utils.search_filters import build_user_field
from src.utils.lambda_deadline import compute_bounded_api_timeout_ms

from src.webhooks.dispatch import dispatch

logger = logging.getLogger(__name__)
NOTIFICATIONS = {"PERMISSION_SCOPE": NOTIFICATIONS_WRITE}


def has_notification_permission(handler_input: HandlerInput) -> bool:
    """Check whether the user has granted notification permissions."""
    try:
        permissions = handler_input.request_envelope.context.system.user.permissions
        if not permissions or not permissions.scopes:
            return False
        return permissions.scopes.get(NOTIFICATIONS["PERMISSION_SCOPE"], {}).get("status") == "GRANTED"
    except Exception:
        return False


def _resolve_notification_categories(store: Dict[str, Any]) -> list:
    """Resolve categories to subscribe to for notifications."""
    from_pattern = resolve_top_categories(store.get("listeningPattern"), 3)
    if from_pattern:
        return from_pattern
    if store.get("currentCategory"):
        return [store["currentCategory"]]
    if store.get("feedbackCategory"):
        return [store["feedbackCategory"]]
    return ["news"]


def build_notification_permission_response(handler_input: HandlerInput):
    """Build a response asking the user to grant notification permission."""
    return handler_input.response_builder \
        .speak(ssml(NOTIFICATION_PERMISSION_REQUEST)) \
        .set_should_end_session(True) \
        .response


async def ensure_subscription(handler_input: HandlerInput, store: Optional[Dict[str, Any]] = None):
    """Ensure the user's notification subscription is active."""
    if not has_notification_permission(handler_input):
        return {"ok": False, "reason": "permission_missing"}
    if store is None:
        store = get_store(handler_input)

    ctx = handler_input.request_envelope.context
    alexa_user_id = ctx.system.user.user_id if ctx.system and ctx.system.user else None
    device_id = ctx.system.device.device_id if ctx.system and ctx.system.device else None
    if not alexa_user_id or not device_id:
        return {"ok": False, "reason": "missing_identity"}

    categories = _resolve_notification_categories(store)
    try:
        locale = handler_input.request_envelope.request.locale \
            if hasattr(handler_input.request_envelope, "request") else None
        await dispatch("notification.subscribed", {
            "userId": alexa_user_id,
            "listenerId": store.get("listenerId"),
            "deviceId": device_id,
            "categories": categories,
            "creatorIds": [c.get("id") for c in (store.get("followedCreators") or []) if c.get("id")],
            "locality": store.get("locality"),
            "timestamp": int(time.time() * 1000),
            "apiEndpoint": ctx.system.api_endpoint if ctx.system else None,
            "locale": locale,
        }, {"awaitQueue": True})
        update_store(handler_input, {"notificationsEnabled": True, "deviceId": device_id})
        return {"ok": True, "categories": categories}
    except Exception as err:
        logger.warning("Notification subscription error: %s", err)
        return {"ok": False, "reason": "api_error", "error": str(err)}


async def complete_notification_opt_in(handler_input: HandlerInput) -> Dict[str, Any]:
    """Complete the notification opt-in after permission is granted."""
    if not has_notification_permission(handler_input):
        return {"ok": False, "reason": "permission_missing"}

    store = get_store(handler_input)
    result = await ensure_subscription(handler_input, store)
    if result.get("ok"):
        update_store(handler_input, {"awaitingNotificationOptIn": False})
    return result


class EnableNotificationsHandler(AbstractRequestHandler):
    """Handles the EnableNotificationsIntent — turns on notification alerts."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "EnableNotificationsIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        try:
            gated = enforce_interaction_gate(handler_input)
            if gated:
                return gated

            has_perm = has_notification_permission(handler_input)
            logger.info("Hear: EnableNotifications entry hasPermission=%s", has_perm)

            if not has_perm:
                update_store(handler_input, {"awaitingNotificationOptIn": True})
                return build_notification_permission_response(handler_input)

            result = await complete_notification_opt_in(handler_input)
            logger.info("Hear: EnableNotifications subscribe result ok=%s", result.get("ok"))

            if not result.get("ok"):
                return handler_input.response_builder \
                    .speak(ssml(NOTIFICATIONS_ENABLE_FAILED)) \
                    .reprompt(ssml(IDLE_DO_NEXT_REPROMPT)) \
                    .set_should_end_session(False) \
                    .response

            return handler_input.response_builder \
                .speak(ssml(NOTIFICATIONS_ENABLED())) \
                .reprompt(ssml(IDLE_DO_NEXT_REPROMPT)) \
                .set_should_end_session(False) \
                .response
        except Exception as err:
            logger.error("Hear: EnableNotificationsHandler failed %s", err)
            return handler_input.response_builder \
                .speak(ssml(ERROR_GENERIC)) \
                .reprompt(ssml(IDLE_DO_NEXT_REPROMPT)) \
                .set_should_end_session(False) \
                .response


class DisableNotificationsHandler(AbstractRequestHandler):
    """Handles the DisableNotificationsIntent — turns off notification alerts."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            get_request_type(handler_input) == "IntentRequest"
            and get_intent_name(handler_input) == "DisableNotificationsIntent"
        )

    async def handle(self, handler_input: HandlerInput):
        gated = enforce_interaction_gate(handler_input)
        if gated:
            return gated

        store = get_store(handler_input)
        catalog = get_browse_catalog(store)
        if (catalog and catalog.get("items")) or (
            isinstance(store.get("pendingBrowseItems"), list) and store.get("pendingBrowseItems")
        ):
            return handler_input.response_builder \
                .speak(ssml(BROWSE_ACTIVE_NOT_NOTIFICATIONS)) \
                .reprompt(ssml(WELCOME_REPROMPT)) \
                .set_should_end_session(False) \
                .response

        user_id = handler_input.request_envelope.context.system.user.user_id \
            if handler_input.request_envelope.context and handler_input.request_envelope.context.system \
            and handler_input.request_envelope.context.system.user else None
        if not user_id:
            return handler_input.response_builder \
                .speak(ERROR_GENERIC) \
                .reprompt(WELCOME_REPROMPT) \
                .set_should_end_session(False) \
                .response

        try:
            await dispatch("notification.unsubscribed", {
                "userId": user_id,
                "listenerId": store.get("listenerId"),
                "timestamp": int(time.time() * 1000),
            }, {"awaitQueue": True})
        except Exception as err:
            logger.warning("Unsubscribe notification dispatch error: %s", err)

        update_store(handler_input, {"notificationsEnabled": False})
        return handler_input.response_builder \
            .speak(ssml(NOTIFICATIONS_DISABLED)) \
            .reprompt(ssml(IDLE_DO_NEXT_REPROMPT)) \
            .set_should_end_session(False) \
            .response
