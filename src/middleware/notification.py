from __future__ import annotations
from ask_sdk_core.dispatch_components import AbstractRequestInterceptor
from src.services.persistence import get_store
from src.webhooks.notification_webhook import check_notifications


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
            store.get("awaitingFeedback")
            or store.get("awaitingStillListening")
            or store.get("awaitingContinueAfterFlag")
        )

        try:
            tracks = await check_notifications(user_id)
        except Exception:
            return

        if not tracks:
            return

        attrs = handler_input.attributes_manager.request_attributes

        if gated:
            attrs["_deferredNotifications"] = {
                "tracks": tracks,
                "trackIds": [t["trackId"] for t in tracks if t.get("trackId")],
            }
        else:
            attrs["_pendingNotifications"] = {
                "tracks": tracks,
                "trackIds": [t["trackId"] for t in tracks if t.get("trackId")],
            }

        handler_input.attributes_manager.request_attributes = attrs
