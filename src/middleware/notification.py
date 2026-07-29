from __future__ import annotations
from ask_sdk_core.dispatch_components import AbstractRequestInterceptor
from src.services.storage.persistence import get_store
from src.services.notifications import check_notifications
from src.services.playback.session import has_unfinished_playback


class NotificationMiddleware(AbstractRequestInterceptor):
    """Check for pending notifications on launch and attach them to request attrs.

    If a blocking interaction (feedback / still-listening / continue-after-flag)
    is active the notifications are deferred rather than announced immediately.
    """

    async def process(self, handler_input) -> None:
        try:
            request_type = handler_input.request_envelope.request.type
        except Exception:
            return
        if request_type != "LaunchRequest":
            return

        store = get_store(handler_input)
        try:
            user_id = handler_input.request_envelope.context.System.user.userId or None
        except Exception:
            return
        if not user_id:
            return

        if not store.get("notificationsEnabled"):
            return

        gated = bool(
            has_unfinished_playback(store)
            or store.get("awaitingFeedback")
            or store.get("awaitingStillListening")
            or store.get("awaitingContinueAfterFlag")
        )

        if gated:
            return

        try:
            items = await check_notifications(user_id)
        except Exception:
            return
        if not items:
            return

        attrs = handler_input.attributes_manager.request_attributes
        attrs["_pendingNotifications"] = {
            "items": items,
        }
        handler_input.attributes_manager.request_attributes = attrs
