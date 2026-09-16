from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class ReportCommand:
    subject_type: Literal["content", "creator"]
    subject_id: str
    subject_name: str | None = None
    content_id: str | None = None
    publication_id: str | None = None

    @classmethod
    def from_subject(cls, subject: dict) -> "ReportCommand":
        subject_type = str(subject.get("type") or "").strip()
        subject_id = str(subject.get("id") or "").strip()
        if subject_type not in {"content", "creator"} or not subject_id:
            raise ValueError("report command requires a supported subject")
        typed_subject_type: Literal["content", "creator"] = (
            "content" if subject_type == "content" else "creator"
        )
        return cls(
            subject_type=typed_subject_type,
            subject_id=subject_id,
            subject_name=str(subject["name"]) if subject.get("name") else None,
            content_id=str(subject["contentId"]) if subject.get("contentId") else None,
            publication_id=str(subject["publicationId"]) if subject.get("publicationId") else None,
        )


@dataclass(frozen=True, slots=True)
class ReportReceipt:
    command: ReportCommand
    recorded_at: int
    status: Literal["pending"] = "pending"

    def event_payload(self) -> dict:
        return {
            "subjectType": self.command.subject_type,
            "subjectId": self.command.subject_id,
            "subjectName": self.command.subject_name,
            "contentId": self.command.content_id,
            "publicationId": self.command.publication_id,
            "recordedAt": self.recorded_at,
            "status": self.status,
        }


class Report:
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
            "requested": bool(saved.get("requested") or pending.get("requested")),
            "discoveryContext": saved.get("discoveryContext")
            or pending.get("discoveryContext")
            or active.get("discoveryContext")
            or (store.get("playbackQueue") or {}).get("discoveryContext"),
        }

    @staticmethod
    def snapshot_report_context(store: dict, *, audio_token: str | None = None) -> dict | None:
        context = Report.build_report_context(store, audio_token=audio_token)
        if not context.get("contentId"):
            return None
        return {**context, "capturedAt": int(time.time() * 1000)}

    @staticmethod
    def record_report(command: ReportCommand) -> ReportReceipt:
        return ReportReceipt(command=command, recorded_at=int(time.time() * 1000))
