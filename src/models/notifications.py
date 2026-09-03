from __future__ import annotations

import logging

import config.permission_scopes as permission_scopes
from config import settings
from src.alexa.context import RequestContext
from src.alexa.request import AlexaRequest
from src.alexa.response import AlexaResponse
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.constants.notifications import NotificationConstants
from src.models.dialog import DialogStateManager
from src.models.search import Search
from src.utils.deadline import DeadlineBudget
from src.utils.filters import SearchFilters
from src.utils.search_payload import SearchPayload


class Notification:
    logger = logging.getLogger(__name__)
    __slots__ = ("_deps",)

    def __init__(self, *, deps: object | None = None) -> None:
        if deps is None:
            raise RuntimeError("Notification requires injected dependencies")
        self._deps = deps

    @staticmethod
    def _dialog_item(item: dict) -> dict:
        allowed = {
            "notificationId",
            "notificationType",
            "contentId",
            "publicationId",
            "title",
            "creatorId",
            "creatorName",
            "organizationId",
            "organizationName",
            "publishedAt",
        }
        return {key: item[key] for key in allowed if item.get(key) is not None}

    async def _safe_status(
        self,
        item: dict,
        status: str,
        *,
        listener_id: str | None = None,
    ) -> bool:
        resolved_listener_id = str(listener_id or item.get("listenerId") or "").strip()
        if not resolved_listener_id or not item.get("notificationId"):
            return False
        try:
            await self._deps.notification_inbox.set_status(
                resolved_listener_id, item["notificationId"], status
            )
            return True
        except Exception as exc:
            self.logger.warning(
                "Hear: notification status update failed status=%s error=%s",
                status,
                type(exc).__name__,
            )
            return False

    async def offer(self, handler_input, *, explicit: bool = False):
        if (
            not explicit
            and AlexaRequest.get_request_type(handler_input) != "LaunchRequest"
        ):
            return None
        store = self._deps.user.snapshot(handler_input)
        listener_id = str(store.get("listenerId") or "").strip()
        if not listener_id or not self._deps.notification_inbox.enabled:
            return (
                AlexaResponse.present_idle_next(
                    handler_input,
                    Speech.NOTIFICATIONS_UNAVAILABLE,
                    Speech.WELCOME_REPROMPT,
                )
                if explicit
                else None
            )
        try:
            items = await self._deps.notification_inbox.pending(
                listener_id,
                limit=max(1, settings.HEAR_NOTIFICATION_LIMIT),
            )
        except Exception as exc:
            self.logger.warning(
                "Hear: notification inbox read failed error=%s", type(exc).__name__
            )
            return (
                AlexaResponse.present_idle_next(
                    handler_input,
                    Speech.NOTIFICATIONS_UNAVAILABLE,
                    Speech.WELCOME_REPROMPT,
                )
                if explicit
                else None
            )
        if not items:
            return (
                AlexaResponse.present_idle_next(
                    handler_input,
                    Speech.NO_NOTIFICATIONS,
                    Speech.WELCOME_REPROMPT,
                )
                if explicit
                else None
            )
        source_item = items[0]
        item = Notification._dialog_item(source_item)
        await self._safe_status(source_item, "offered")
        self._deps.user.update(
            handler_input,
            {
                "awaitingNotificationChoice": True,
                "pendingNotification": item,
                "_requiresReliableSave": True,
            },
        )
        question = Speech.NOTIFICATION_OFFER(item, max(0, len(items) - 1))
        reprompt = Speech.NOTIFICATION_OFFER_REPROMPT(item)
        DialogStateManager.activate(
            handler_input,
            "notification",
            context={**item, "question": question},
        )
        return (
            handler_input.response_builder.speak(Ssml.ssml(question))
            .reprompt(Ssml.ssml(reprompt))
            .set_should_end_session(False)
            .response
        )

    async def accept(self, handler_input):
        store = self._deps.user.snapshot(handler_input)
        item = store.get("pendingNotification") or {}
        if not item.get("notificationId"):
            return AlexaResponse.present_idle_next(
                handler_input,
                Speech.NO_NOTIFICATIONS,
                Speech.WELCOME_REPROMPT,
            )
        listener_id = str(store.get("listenerId") or "").strip()
        await self._safe_status(item, "resolving", listener_id=listener_id)
        filters = (
            SearchFilters.content(item.get("contentId"))
            if item.get("notificationType") == NotificationConstants.CONTENT
            else SearchFilters.source("publication", item.get("publicationId"))
        )
        limit = 1 if item.get("notificationType") == NotificationConstants.CONTENT else 10
        payload = SearchPayload.build(
            AlexaRequest.get_user_id(handler_input),
            store,
            q="",
            limit=limit,
            page=0,
            sort="latest",
            nlp_filter=filters,
        )
        await self._deps.progressive.send(handler_input, Speech.NOTIFICATION_LOADING)
        try:
            result = await self._deps.heara.search(
                payload,
                timeout_ms=DeadlineBudget.compute_search_timeout_ms(handler_input),
            )
        except Exception as exc:
            self.logger.warning(
                "Hear: notification content lookup failed error=%s", type(exc).__name__
            )
            result = {"results": [], "failed": True}
        if result.get("failed"):
            await self._safe_status(item, "pending", listener_id=listener_id)
            self._clear_dialog(handler_input)
            return AlexaResponse.present_idle_next(
                handler_input,
                Speech.NOTIFICATION_LOOKUP_FAILED,
                Speech.WELCOME_REPROMPT,
            )
        results = list(result.get("results") or [])
        if not results:
            await self._safe_status(item, "unavailable", listener_id=listener_id)
            self._clear_dialog(handler_input)
            return AlexaResponse.present_idle_next(
                handler_input,
                Speech.NOTIFICATION_CONTENT_UNAVAILABLE,
                Speech.WELCOME_REPROMPT,
            )
        first = results[0]
        self._clear_dialog(handler_input)
        self._deps.user.update(
            handler_input,
            {
                "notificationPlayback": {
                    "notificationId": item["notificationId"],
                    "contentId": first.get("contentId"),
                }
            },
        )
        await self._safe_status(item, "queued", listener_id=listener_id)
        result["_search_payload"] = payload
        try:
            return await Search.auto_play_first_from_search(
                handler_input,
                result,
                {
                    "discoveryIntent": "notification",
                    "q": "",
                    "introOverride": Speech.NOTIFICATION_PLAYING(item),
                },
                deps=self._deps,
            )
        except Exception:
            await self._safe_status(item, "pending", listener_id=listener_id)
            self._deps.user.update(handler_input, {"notificationPlayback": None})
            raise

    async def decline(self, handler_input):
        store = self._deps.user.snapshot(handler_input)
        item = store.get("pendingNotification") or {}
        if item.get("notificationId"):
            await self._safe_status(
                item,
                "dismissed",
                listener_id=str(store.get("listenerId") or "").strip(),
            )
        self._clear_dialog(handler_input)
        return AlexaResponse.present_idle_next(
            handler_input,
            Speech.NOTIFICATION_DECLINED,
            Speech.WELCOME_REPROMPT,
        )

    def _clear_dialog(self, handler_input) -> None:
        self._deps.user.update(
            handler_input,
            {
                "awaitingNotificationChoice": False,
                "pendingNotification": None,
                "_requiresReliableSave": True,
            },
        )
        DialogStateManager.clear(handler_input, "notification")

    async def playback_started(self, handler_input, content_id: str) -> None:
        store = self._deps.user.snapshot(handler_input)
        pending = store.get("notificationPlayback") or {}
        if not pending.get("notificationId") or pending.get("contentId") != content_id:
            return
        await self._safe_status(
            pending,
            "consumed",
            listener_id=str(store.get("listenerId") or "").strip(),
        )
        self._deps.user.update(handler_input, {"notificationPlayback": None})

    async def playback_failed(self, handler_input, content_id: str) -> None:
        store = self._deps.user.snapshot(handler_input)
        pending = store.get("notificationPlayback") or {}
        if not pending.get("notificationId") or pending.get("contentId") != content_id:
            return
        await self._safe_status(
            pending,
            "pending",
            listener_id=str(store.get("listenerId") or "").strip(),
        )
        self._deps.user.update(handler_input, {"notificationPlayback": None})

    def enable(self, handler_input):
        if not self._has_permission(handler_input):
            return self._deps.permission.start_notifications(handler_input)
        return self.enable_after_permission(handler_input)

    def enable_after_permission(self, handler_input):
        self._publish_preference(handler_input, True)
        return AlexaResponse.present_idle_next(
            handler_input,
            Speech.NOTIFICATIONS_ENABLED,
            Speech.WELCOME_REPROMPT,
        )

    def disable(self, handler_input):
        self._publish_preference(handler_input, False)
        return AlexaResponse.present_idle_next(
            handler_input,
            Speech.NOTIFICATIONS_DISABLED,
            Speech.WELCOME_REPROMPT,
        )

    def _publish_preference(self, handler_input, enabled: bool) -> None:
        store = self._deps.user.snapshot(handler_input)
        user_id = AlexaRequest.get_user_id(handler_input)
        if not user_id:
            return
        self._deps.events.notification_preference(
            enabled=enabled,
            alexa_user_id=user_id,
            listener_id=store.get("listenerId"),
            permission_granted=(True if enabled else self._has_permission(handler_input)),
        )

    @staticmethod
    def _has_permission(handler_input) -> bool:
        return RequestContext.has_permission(handler_input, permission_scopes.NOTIFICATIONS_WRITE)
