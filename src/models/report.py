from __future__ import annotations

import time

from src.alexa.request import AlexaRequest
from src.models.user import User
from src.services.events import OutboundEventService


class Report:
    __slots__ = ("_events",)

    def __init__(self, events: OutboundEventService | None = None) -> None:
        self._events = events

    @staticmethod
    def resolve_report_track_context(store: dict, *, audio_token: str | None = None) -> dict:
        if not isinstance(store, dict):
            return {"contentId": None}
        saved = store.get("reportContext") or {}
        if saved.get("contentId"):
            return {
                "contentId": str(saved["contentId"]),
                "publicationId": saved.get("publicationId"),
            }
        pending = store.get("pendingFeedback") or {}
        active = store.get("activePlayback") or {}
        content_id = pending.get("contentId") or active.get("contentId") or audio_token
        publication_id = pending.get("publicationId") or active.get("publicationId")
        return {
            "contentId": str(content_id) if content_id is not None else None,
            "publicationId": str(publication_id) if publication_id is not None else None,
        }

    @staticmethod
    def build_report_context(store: dict, *, audio_token: str | None = None) -> dict:
        if not isinstance(store, dict):
            return {
                "contentId": None,
                "title": None,
                "creatorId": None,
                "creatorName": None,
            }
        context = Report.resolve_report_track_context(store, audio_token=audio_token)
        pending = store.get("pendingFeedback") or {}
        active = store.get("activePlayback") or {}
        saved = store.get("reportContext") or {}
        return {
            "contentId": context["contentId"],
            "publicationId": saved.get("publicationId") or context.get("publicationId"),
            "title": saved.get("title") or pending.get("title") or active.get("title"),
            "publicationTitle": saved.get("publicationTitle")
            or pending.get("publicationTitle")
            or active.get("publicationTitle"),
            "subjectTitle": saved.get("subjectTitle")
            or pending.get("subjectTitle")
            or active.get("subjectTitle"),
            "subjectType": saved.get("subjectType")
            or pending.get("subjectType")
            or active.get("subjectType"),
            "creatorId": saved.get("creatorId")
            or pending.get("creatorId")
            or active.get("creatorId"),
            "creatorName": saved.get("creatorName")
            or pending.get("creatorName")
            or active.get("creatorName"),
        }

    @staticmethod
    def snapshot_report_context(store: dict, *, audio_token: str | None = None) -> dict | None:
        context = Report.build_report_context(store, audio_token=audio_token)
        if not context.get("contentId"):
            return None
        return {**context, "capturedAt": int(time.time() * 1000)}

    async def record_report(self, handler_input, subject: dict) -> dict:
        report = {
            "subjectType": subject.get("type"),
            "subjectId": str(subject.get("id")),
            "subjectName": subject.get("name"),
            "contentId": subject.get("contentId"),
            "publicationId": subject.get("publicationId"),
            "recordedAt": int(time.time() * 1000),
            "status": "pending",
        }
        store = User.snapshot(handler_input)
        user_id = AlexaRequest.get_user_id(handler_input)
        if self._events is not None and user_id:
            self._events.report(
                alexa_user_id=user_id,
                listener_id=store.get("listenerId"),
                report=report,
            )
        return report
