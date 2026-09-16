from __future__ import annotations

import config.permission_scopes as permission_scopes
from src.alexa.context import RequestContext
from src.alexa.dialog import DialogStateManager
from src.alexa.request import AlexaRequest
from src.alexa.response import AlexaResponse
from src.alexa.search import Search
from src.alexa.speech import Speech
from src.alexa.ssml import Ssml
from src.models.notifications import (
    Notification,
    NotificationAcceptCommand,
    NotificationOfferCommand,
)
from src.utils.deadline import DeadlineBudget


class AlexaNotificationAdapter:
    """Alexa request/state and response adapter for the notification workflow."""

    __slots__ = (
        "_workflow",
        "_user",
        "_progressive",
        "_browse",
        "_playback",
        "_permission",
        "_events",
        "_notification_api_enabled",
    )

    def __init__(
        self,
        workflow: Notification,
        user,
        progressive,
        browse,
        playback,
        permission,
        events,
        *,
        notification_api_enabled: bool,
    ) -> None:
        self._workflow = workflow
        self._user = user
        self._progressive = progressive
        self._browse = browse
        self._playback = playback
        self._permission = permission
        self._events = events
        self._notification_api_enabled = notification_api_enabled

    async def offer(self, handler_input, *, explicit: bool = False):
        store = self._user.snapshot(handler_input)
        listener_id = str(store.get("listenerId") or "").strip()
        result = await self._workflow.offer(
            NotificationOfferCommand(
                explicit=explicit,
                request_type=AlexaRequest.get_request_type(handler_input),
                listener_id=listener_id,
                api_enabled=self._notification_api_enabled,
            )
        )
        if result.kind == "none":
            return None
        if result.kind in {"unavailable", "failed"}:
            return self._unavailable_response(handler_input) if explicit else None
        if result.kind == "empty":
            return self._empty_response(handler_input) if explicit else None
        item = result.item or {}
        self._user.update(
            handler_input,
            {
                "awaitingNotificationChoice": True,
                "pendingNotification": item,
                "_requiresReliableSave": True,
            },
        )
        question = Speech.NOTIFICATION_OFFER(item, result.remaining_count)
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
        store = self._user.snapshot(handler_input)
        item = store.get("pendingNotification") or {}
        if not item.get("notificationId"):
            return self._empty_response(handler_input)
        listener_id = str(store.get("listenerId") or "").strip()
        await self._progressive.send(handler_input, Speech.NOTIFICATION_LOADING)
        result = await self._workflow.accept(
            NotificationAcceptCommand(
                listener_id=listener_id,
                alexa_user_id=AlexaRequest.get_user_id(handler_input),
                store=store,
                item=item,
                timeout_ms=DeadlineBudget.compute_search_timeout_ms(handler_input),
            )
        )
        if result.kind == "missing":
            return self._empty_response(handler_input)
        if result.kind == "failed":
            self._clear_dialog(handler_input)
            return AlexaResponse.present_idle_next(
                handler_input,
                Speech.NOTIFICATION_LOOKUP_FAILED,
                Speech.WELCOME_REPROMPT,
            )
        if result.kind == "empty":
            self._clear_dialog(handler_input)
            return AlexaResponse.present_idle_next(
                handler_input,
                Speech.NOTIFICATION_CONTENT_UNAVAILABLE,
                Speech.WELCOME_REPROMPT,
            )
        first = result.results[0]
        self._clear_dialog(handler_input)
        self._user.update(
            handler_input,
            {
                "notificationPlayback": {
                    "notificationId": item["notificationId"],
                    "contentId": first.get("contentId"),
                }
            },
        )
        await self._workflow.update_status(
            listener_id=listener_id, item=item, status="queued"
        )
        search_result = {
            "results": list(result.results),
            "_search_payload": result.payload,
        }
        try:
            return await Search.auto_play_first_from_search(
                handler_input,
                search_result,
                {
                    "discoveryIntent": "notification",
                    "q": "",
                    "introOverride": Speech.NOTIFICATION_PLAYING(item),
                },
                user=self._user,
                browse=self._browse,
                playback=self._playback,
            )
        except Exception:
            await self._workflow.update_status(
                listener_id=listener_id, item=item, status="pending"
            )
            self._user.update(handler_input, {"notificationPlayback": None})
            raise

    async def decline(self, handler_input):
        store = self._user.snapshot(handler_input)
        item = store.get("pendingNotification") or {}
        if item.get("notificationId"):
            await self._workflow.update_status(
                listener_id=str(store.get("listenerId") or "").strip(),
                item=item,
                status="dismissed",
            )
        self._clear_dialog(handler_input)
        return AlexaResponse.present_idle_next(
            handler_input,
            Speech.NOTIFICATION_DECLINED,
            Speech.WELCOME_REPROMPT,
        )

    async def playback_started(self, handler_input, content_id: str) -> None:
        await self._resolve_playback(handler_input, content_id, "consumed")

    async def playback_failed(self, handler_input, content_id: str) -> None:
        await self._resolve_playback(handler_input, content_id, "pending")

    async def _resolve_playback(self, handler_input, content_id: str, status: str) -> None:
        store = self._user.snapshot(handler_input)
        pending = store.get("notificationPlayback") or {}
        if not pending.get("notificationId") or pending.get("contentId") != content_id:
            return
        await self._workflow.update_status(
            listener_id=str(store.get("listenerId") or "").strip(),
            item=pending,
            status=status,
        )
        self._user.update(handler_input, {"notificationPlayback": None})

    def enable(self, handler_input):
        if not self._has_permission(handler_input):
            return self._permission.start_notifications(handler_input)
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

    def _clear_dialog(self, handler_input) -> None:
        self._user.update(
            handler_input,
            {
                "awaitingNotificationChoice": False,
                "pendingNotification": None,
                "_requiresReliableSave": True,
            },
        )
        DialogStateManager.clear(handler_input, "notification")

    def _publish_preference(self, handler_input, enabled: bool) -> None:
        store = self._user.snapshot(handler_input)
        user_id = AlexaRequest.get_user_id(handler_input)
        if not user_id:
            return
        self._events.notification_preference(
            handler_input=handler_input,
            enabled=enabled,
            alexa_user_id=user_id,
            listener_id=store.get("listenerId"),
            permission_granted=(True if enabled else self._has_permission(handler_input)),
        )

    @staticmethod
    def _has_permission(handler_input) -> bool:
        return RequestContext.has_permission(handler_input, permission_scopes.NOTIFICATIONS_WRITE)

    @staticmethod
    def _unavailable_response(handler_input):
        return AlexaResponse.present_idle_next(
            handler_input,
            Speech.NOTIFICATIONS_UNAVAILABLE,
            Speech.WELCOME_REPROMPT,
        )

    @staticmethod
    def _empty_response(handler_input):
        return AlexaResponse.present_idle_next(
            handler_input,
            Speech.NO_NOTIFICATIONS,
            Speech.WELCOME_REPROMPT,
        )
