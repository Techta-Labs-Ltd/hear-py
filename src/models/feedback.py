from __future__ import annotations

import time

from src.alexa.request import AlexaRequest
from src.constants.notifications import NotificationConstants
from src.constants.playback import PlaybackConstants
from src.models.dialog import DialogStateManager
from src.models.user import User
from src.services.alexa_reminder import AlexaReminderService
from src.services.events import OutboundEventService
from src.utils.content import ContentIdentity
from src.utils.playback import PlaybackUtils
from src.utils.playback_history import PlaybackHistoryUtils


class FeedbackService:
    __slots__ = ("_reminders", "_events")

    def __init__(
        self,
        reminders: AlexaReminderService | None = None,
        events: OutboundEventService | None = None,
    ) -> None:
        self._reminders = reminders
        self._events = events

    rating_intents = {
        "FeedbackEnjoyedIntent",
        "FeedbackSomewhatIntent",
        "FeedbackNotEnjoyedIntent",
        "RateContentIntent",
        "SkipFeedbackIntent",
    }
    follow_intents = {"FollowCreatorIntent", "UnfollowCreatorIntent"}
    report_intents = {"ReportCreatorIntent", "ReportContentIntent"}

    def should_evaluate(self, handler_input) -> bool:
        request_type = AlexaRequest.get_request_type(handler_input)
        if request_type.startswith("AudioPlayer."):
            return False
        if request_type == "SessionEndedRequest":
            return False
        if request_type == "IntentRequest" and AlexaRequest.get_intent_name(handler_input) in {
            "AMAZON.StopIntent",
            "AMAZON.CancelIntent",
        }:
            return False
        return User.snapshot(handler_input).get("onboardingStage") != "ask_town"

    def should_block(self, handler_input) -> bool:
        if not self.should_evaluate(handler_input):
            return False
        request_type = AlexaRequest.get_request_type(handler_input)
        if request_type in PlaybackConstants.TRANSPORT_REQUEST_TYPES:
            return False
        store = User.snapshot(handler_input)
        pending = store.get("pendingFeedback") or {}
        if (
            store.get("awaitingFeedback")
            and pending.get("completed") is False
            and not pending.get("requested")
        ):
            User.update(
                handler_input,
                {
                    "pendingFeedback": None,
                    "awaitingFeedback": False,
                    "activeDialog": None,
                },
            )
            return False
        if not store.get("awaitingFeedback"):
            self.clear_stale_state(handler_input)
            return False
        if request_type != "IntentRequest":
            return True
        intent_name = AlexaRequest.get_intent_name(handler_input)
        allowed = (
            self.rating_intents
            | self.report_intents
            | PlaybackConstants.TRANSPORT_INTENTS
            | NotificationConstants.INTENTS
            | {"AMAZON.YesIntent", "AMAZON.NoIntent"}
        )
        return intent_name not in allowed

    @staticmethod
    def request_current_rating(handler_input) -> dict | None:
        store = User.snapshot(handler_input)
        state = store.get("activePlayback")
        if not isinstance(state, dict) or not state.get("contentId"):
            pending = store.get("pendingFeedback")
            if not isinstance(pending, dict) or not pending.get("feedbackKey"):
                return None
            selected = {**pending, "requested": True}
        else:
            content_id = str(state["contentId"])
            subject_type = ContentIdentity.subject_type(state)
            selected = {
                "feedbackKey": ContentIdentity.subject_key(state) or content_id,
                "subjectType": subject_type,
                "contentId": content_id,
                "publicationId": state.get("publicationId"),
                "title": ContentIdentity.subject_title(state) or state.get("title"),
                "publicationTitle": state.get("publicationTitle"),
                "creatorId": state.get("creatorId"),
                "creatorName": state.get("creatorName"),
                "organizationId": state.get("organizationId"),
                "organizationName": state.get("organizationName"),
                "category": state.get("category"),
                "listenedMs": FeedbackService._safe_int(state.get("listenedMs")),
                "timeSpentMs": FeedbackService._safe_int(state.get("timeSpentMs")),
                "timeSpentHours": PlaybackUtils.hours(state.get("timeSpentMs")),
                "completed": state.get("status") == "completed",
                "requested": True,
                "sessionId": state.get("sessionId"),
                "playbackStartedAt": FeedbackService._safe_int(state.get("startedAt")),
                "createdAt": int(time.time() * 1000),
            }
        User.update(
            handler_input,
            {
                "pendingFeedback": selected,
                "awaitingFeedback": True,
                "_requiresReliableSave": True,
            },
        )
        DialogStateManager.activate(handler_input, "feedback", context=selected)
        return selected

    def clear_stale_state(self, handler_input) -> None:
        if AlexaRequest.get_request_type(handler_input) != "IntentRequest":
            return
        store = User.snapshot(handler_input)
        intent_name = AlexaRequest.get_intent_name(handler_input)
        if store.get("awaitingFollow"):
            if intent_name not in self.follow_intents | {"AMAZON.NoIntent"}:
                User.update(
                    handler_input,
                    {"awaitingFollow": False, "pendingFollowSource": None},
                )
            return
        if store.get("awaitingReportDecision"):
            allowed = self.report_intents | {"SkipFeedbackIntent", "AMAZON.NoIntent"}
            if intent_name not in allowed:
                User.update(handler_input, {"awaitingReportDecision": False})

    @staticmethod
    def _safe_int(value, default: int = 0) -> int:
        try:
            return int(value or default)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _feedback_key(state: dict) -> str | None:
        return ContentIdentity.subject_key(state)

    @staticmethod
    def _candidate_recency(candidate: dict | None) -> int:
        value = candidate if isinstance(candidate, dict) else {}
        playback_started = FeedbackService._safe_int(value.get("playbackStartedAt"))
        return playback_started or FeedbackService._safe_int(value.get("createdAt"))

    @staticmethod
    def _publication_is_last_track(state: dict, store: dict) -> bool:
        track_index = state.get("trackIndex")
        track_count = state.get("trackCount")
        if isinstance(track_index, int) and isinstance(track_count, int) and (track_count > 0):
            if track_index + 1 >= track_count:
                return True
        queue = PlaybackUtils.read_playback_queue(store)
        pagination = queue.get("pagination") if queue else None
        has_more_pages = bool(
            isinstance(pagination, dict)
            and int(pagination.get("currentPage") or 0) + 1 < int(pagination.get("totalPages") or 0)
        )
        return bool(
            queue
            and (not has_more_pages)
            and (queue.get("publicationId") == state.get("publicationId"))
            and (int(queue.get("currentIndex") or 0) >= len(queue["orderedContentIds"]) - 1)
        )

    @staticmethod
    def _publication_coverage(progress: dict) -> tuple[float, int]:
        tracks = progress.get("tracks") or {}
        expected = max(
            1,
            FeedbackService._safe_int(progress.get("expectedTrackCount"), len(tracks) or 1),
        )
        meaningful = 0
        listened_total = 0
        for track in tracks.values():
            listened = max(0, FeedbackService._safe_int(track.get("listenedMs")))
            duration = max(0, FeedbackService._safe_int(track.get("durationMs")))
            listened_total += min(listened, duration) if duration else listened
            threshold = duration * 0.5 if duration else 60000
            if track.get("completed") or listened >= threshold:
                meaningful += 1
        total_duration = max(0, FeedbackService._safe_int(progress.get("expectedDurationMs")))
        coverage = (
            min(1.0, listened_total / total_duration)
            if total_duration > 0
            else min(1.0, meaningful / expected)
        )
        return (coverage, meaningful)

    @staticmethod
    def publication_track_listening(progress: dict) -> list[dict]:
        tracks = (progress.get("tracks") or {}) if isinstance(progress, dict) else {}
        return [
            {
                "contentId": str(content_id),
                "trackIndex": track.get("trackIndex"),
                "durationMs": FeedbackService._safe_int(track.get("durationMs")),
                "listenedMs": FeedbackService._safe_int(track.get("listenedMs")),
                "timeSpentMs": FeedbackService._safe_int(track.get("timeSpentMs")),
                "timeSpentHours": PlaybackUtils.hours(track.get("timeSpentMs")),
                "completed": bool(track.get("completed")),
            }
            for content_id, track in tracks.items()
            if isinstance(track, dict)
        ]

    @staticmethod
    def publication_listening_metrics(store: dict, publication_id: str) -> dict:
        progress = (store.get("publicationFeedbackProgress") or {}).get(
            str(publication_id)
        )
        candidates = [
            store.get("pendingFeedback"),
            *(store.get("feedbackCandidates") or []),
        ]
        if not isinstance(progress, dict):
            progress = next(
                (
                    candidate
                    for candidate in candidates
                    if isinstance(candidate, dict)
                    and str(candidate.get("publicationId") or "")
                    == str(publication_id)
                ),
                {},
            )
        track_listening = progress.get("trackListening")
        if not isinstance(track_listening, list):
            track_listening = FeedbackService.publication_track_listening(progress)
        time_spent = FeedbackService._safe_int(progress.get("timeSpentMs"))
        if not time_spent:
            time_spent = sum(
                FeedbackService._safe_int(track.get("timeSpentMs"))
                for track in track_listening
                if isinstance(track, dict)
            )
        return {
            "publicationTimeSpentMs": time_spent,
            "publicationTimeSpentHours": PlaybackUtils.hours(time_spent),
            "trackListening": track_listening,
        }

    @staticmethod
    def update_publication_progress(
        handler_input, state: dict, *, completed: bool = False
    ) -> dict | None:
        publication_id = state.get("publicationId")
        content_id = state.get("contentId")
        if not publication_id or not content_id:
            return None
        store = User.snapshot(handler_input)
        all_progress = dict(store.get("publicationFeedbackProgress") or {})
        current = dict(all_progress.get(str(publication_id)) or {})
        queue = PlaybackUtils.read_playback_queue(store)
        expected_count = max(
            FeedbackService._safe_int(current.get("expectedTrackCount")),
            FeedbackService._safe_int(state.get("trackCount")),
            FeedbackService._safe_int((queue or {}).get("publicationTrackCount"))
            if (queue or {}).get("publicationId") == publication_id
            else 0,
            1,
        )
        expected_duration = FeedbackService._safe_int(current.get("expectedDurationMs"))
        if queue and queue.get("publicationId") == publication_id:
            expected_duration = max(
                expected_duration,
                FeedbackService._safe_int(queue.get("publicationTotalDurationMs")),
            )
        tracks = dict(current.get("tracks") or {})
        existing_track = dict(tracks.get(str(content_id)) or {})
        sessions = PlaybackHistoryUtils.session_ledger(existing_track, state)
        track_time_spent = PlaybackHistoryUtils.accumulated_time(
            existing_track,
            state,
            sessions,
        )
        tracks[str(content_id)] = {
            "contentId": str(content_id),
            "trackIndex": state.get("trackIndex"),
            "listenedMs": max(
                FeedbackService._safe_int(existing_track.get("listenedMs")),
                FeedbackService._safe_int(state.get("listenedMs")),
            ),
            "durationMs": max(
                FeedbackService._safe_int(existing_track.get("durationMs")),
                FeedbackService._safe_int(state.get("durationMs")),
            ),
            "completed": bool(existing_track.get("completed") or completed),
            "timeSpentMs": track_time_spent,
            "timeSpentHours": PlaybackUtils.hours(track_time_spent),
            "sessions": sessions,
        }
        tracks = dict(list(tracks.items())[-100:])
        publication_time_spent = sum(
            FeedbackService._safe_int(track.get("timeSpentMs"))
            for track in tracks.values()
            if isinstance(track, dict)
        )
        progress = {
            **current,
            "publicationId": str(publication_id),
            "publicationTitle": state.get("publicationTitle") or current.get("publicationTitle"),
            "organizationId": state.get("organizationId") or current.get("organizationId"),
            "organizationName": state.get("organizationName") or current.get("organizationName"),
            "creatorId": state.get("creatorId") or current.get("creatorId"),
            "creatorName": state.get("creatorName") or current.get("creatorName"),
            "category": state.get("category") or current.get("category"),
            "queueId": state.get("queueId") or current.get("queueId"),
            "expectedTrackCount": expected_count,
            "expectedDurationMs": expected_duration or None,
            "representativeContentId": str(content_id),
            "latestPlaybackStartedAt": max(
                FeedbackService._safe_int(current.get("latestPlaybackStartedAt")),
                FeedbackService._safe_int(state.get("startedAt")),
            ),
            "timeSpentMs": publication_time_spent,
            "timeSpentHours": PlaybackUtils.hours(publication_time_spent),
            "tracks": tracks,
            "updatedAt": int(time.time() * 1000),
        }
        progress.pop("closedAt", None)
        coverage, meaningful = FeedbackService._publication_coverage(progress)
        progress["coverage"] = coverage
        progress["meaningfulTrackCount"] = meaningful
        all_progress[str(publication_id)] = progress
        if len(all_progress) > 5:
            newest = sorted(
                all_progress.items(),
                key=lambda pair: FeedbackService._safe_int((pair[1] or {}).get("updatedAt")),
            )[-5:]
            all_progress = dict(newest)
        legacy_candidates = [
            candidate
            for candidate in store.get("feedbackCandidates") or []
            if not (
                candidate.get("publicationId") == publication_id
                and candidate.get("subjectType") != "publication"
            )
        ]
        User.update(
            handler_input,
            {
                "publicationFeedbackProgress": all_progress,
                "feedbackCandidates": legacy_candidates,
            },
        )
        return progress

    @staticmethod
    def finalize_publication(handler_input, publication_id: str | None) -> dict | None:
        if not publication_id:
            return None
        store = User.snapshot(handler_input)
        all_progress = dict(store.get("publicationFeedbackProgress") or {})
        progress = all_progress.get(str(publication_id))
        if not isinstance(progress, dict):
            return None
        coverage, meaningful = FeedbackService._publication_coverage(progress)
        expected = max(1, FeedbackService._safe_int(progress.get("expectedTrackCount"), 1))
        key = f"publication:{publication_id}"
        eligible = coverage >= 0.5 and (expected == 1 or meaningful >= 2)
        if key in (store.get("answeredFeedbackKeys") or []):
            all_progress.pop(str(publication_id), None)
            User.update(handler_input, {"publicationFeedbackProgress": all_progress})
            return None
        if not eligible:
            progress["closedAt"] = int(time.time() * 1000)
            progress["coverage"] = coverage
            progress["meaningfulTrackCount"] = meaningful
            all_progress[str(publication_id)] = progress
            User.update(handler_input, {"publicationFeedbackProgress": all_progress})
            return None
        all_progress.pop(str(publication_id), None)
        updates = {"publicationFeedbackProgress": all_progress}
        listened_ms = sum(
            (
                FeedbackService._safe_int(track.get("listenedMs"))
                for track in (progress.get("tracks") or {}).values()
                if isinstance(track, dict)
            )
        )
        track_listening = FeedbackService.publication_track_listening(progress)
        time_spent_ms = sum(
            FeedbackService._safe_int(track.get("timeSpentMs"))
            for track in track_listening
        )
        candidate = {
            "feedbackKey": key,
            "subjectType": "publication",
            "publicationId": str(publication_id),
            "contentIds": list((progress.get("tracks") or {}).keys()),
            "title": progress.get("publicationTitle") or "that publication",
            "publicationTitle": progress.get("publicationTitle"),
            "creatorId": progress.get("creatorId"),
            "creatorName": progress.get("creatorName"),
            "organizationId": progress.get("organizationId"),
            "organizationName": progress.get("organizationName"),
            "category": progress.get("category"),
            "coverage": coverage,
            "expectedTrackCount": expected,
            "meaningfulTrackCount": meaningful,
            "listenedMs": listened_ms,
            "timeSpentMs": time_spent_ms,
            "timeSpentHours": PlaybackUtils.hours(time_spent_ms),
            "trackListening": track_listening,
            "completed": True,
            "sessionId": key,
            "playbackStartedAt": FeedbackService._safe_int(progress.get("latestPlaybackStartedAt")),
            "createdAt": int(time.time() * 1000),
        }
        existing = [
            item for item in store.get("feedbackCandidates") or [] if item.get("feedbackKey") != key
        ]
        updates["feedbackCandidates"] = (existing + [candidate])[-20:]
        User.update(handler_input, updates)
        return candidate

    @staticmethod
    def finalize_other_publications(handler_input, next_publication_id: str | None) -> bool:
        store = User.snapshot(handler_input)
        progress_ids = list((store.get("publicationFeedbackProgress") or {}).keys())
        created = False
        for publication_id in progress_ids:
            if str(publication_id) != str(next_publication_id or ""):
                created = (
                    bool(FeedbackService.finalize_publication(handler_input, publication_id))
                    or created
                )
        return created

    @staticmethod
    def record_candidate(handler_input, state: dict, *, completed: bool) -> dict | None:
        if not completed:
            return None
        if state.get("publicationId"):
            FeedbackService.update_publication_progress(handler_input, state, completed=True)
            if FeedbackService._publication_is_last_track(state, User.snapshot(handler_input)):
                return FeedbackService.finalize_publication(
                    handler_input, str(state["publicationId"])
                )
            return None
        key = FeedbackService._feedback_key(state)
        listened_ms = max(0, int(state.get("listenedMs") or 0))
        if not key:
            return None
        store = User.snapshot(handler_input)
        if key in (store.get("answeredFeedbackKeys") or []):
            return None
        candidate = {
            "feedbackKey": key,
            "subjectType": "content",
            "contentId": state.get("contentId"),
            "publicationId": state.get("publicationId"),
            "title": state.get("title") or state.get("publicationTitle"),
            "publicationTitle": state.get("publicationTitle"),
            "creatorId": state.get("creatorId"),
            "creatorName": state.get("creatorName"),
            "organizationId": state.get("organizationId"),
            "organizationName": state.get("organizationName"),
            "category": state.get("category"),
            "listenedMs": listened_ms,
            "timeSpentMs": FeedbackService._safe_int(state.get("timeSpentMs")),
            "timeSpentHours": PlaybackUtils.hours(state.get("timeSpentMs")),
            "completed": bool(completed),
            "sessionId": state.get("sessionId"),
            "playbackStartedAt": FeedbackService._safe_int(state.get("startedAt")),
            "createdAt": int(time.time() * 1000),
        }
        existing = [
            value
            for value in store.get("feedbackCandidates") or []
            if value.get("feedbackKey") != key
        ]
        User.update(handler_input, {"feedbackCandidates": (existing + [candidate])[-20:]})
        return candidate

    @staticmethod
    def activate_best(handler_input) -> dict | None:
        store = User.snapshot(handler_input)
        pending = store.get("pendingFeedback") if store.get("awaitingFeedback") else None
        candidates = [
            item
            for item in store.get("feedbackCandidates") or []
            if item.get("completed") is True
            if item.get("feedbackKey") not in (store.get("answeredFeedbackKeys") or [])
        ]
        if not candidates:
            return pending
        candidates.sort(
            key=lambda item: (
                FeedbackService._candidate_recency(item),
                int(item.get("listenedMs") or 0),
            ),
            reverse=True,
        )
        selected = candidates[0]
        if isinstance(pending, dict) and FeedbackService._candidate_recency(
            selected
        ) <= FeedbackService._candidate_recency(pending):
            User.update(handler_input, {"feedbackCandidates": []})
            return pending
        User.update(
            handler_input,
            {
                "pendingFeedback": selected,
                "feedbackCandidates": [],
                "awaitingFeedback": True,
                "_requiresReliableSave": True,
            },
        )
        DialogStateManager.activate(handler_input, "feedback", context=selected)
        return selected

    @staticmethod
    def mark_answered(handler_input) -> dict:
        store = User.snapshot(handler_input)
        pending = store.get("pendingFeedback") or {}
        key = pending.get("feedbackKey")
        answered = list(store.get("answeredFeedbackKeys") or [])
        if key and key not in answered:
            answered.append(key)
        return User.update(
            handler_input,
            {
                "answeredFeedbackKeys": answered[-100:],
                "pendingFeedback": None,
                "awaitingFeedback": False,
                "activeDialog": None,
                "_requiresReliableSave": True,
                "deferredIntent": None,
                "pendingFollowSource": None,
            },
        )

    async def submit(self, handler_input, value: str) -> dict:
        store = User.snapshot(handler_input)
        pending = dict(store.get("pendingFeedback") or {})
        user_id = AlexaRequest.get_user_id(handler_input)
        if self._events is not None and user_id:
            self._events.feedback(
                alexa_user_id=user_id,
                listener_id=store.get("listenerId"),
                pending=pending,
                value=value,
            )
        return FeedbackService.mark_answered(handler_input)

    async def clear(self, handler_input) -> dict:
        if self._reminders is not None:
            try:
                await self._reminders.cancel(handler_input)
            except Exception:
                pass
        return User.update(
            handler_input,
            {
                "activeDialog": None,
                "awaitingFeedback": False,
                "awaitingFollow": False,
                "pendingFollowSource": None,
                "awaitingReportDecision": False,
                "reportContext": None,
                "pendingFeedback": None,
                "feedbackContentId": None,
                "feedbackPromptText": None,
                "feedbackCategory": None,
                "feedbackCreator": None,
                "feedbackCreatorId": None,
                "feedbackContentTitle": None,
                "feedbackReminderAlertToken": None,
                "feedbackAskedForToken": None,
                "playbackDurationEstimateMs": None,
                "deferredIntent": None,
            },
        )

    @staticmethod
    def dismiss(handler_input) -> dict:
        active = User.snapshot(handler_input).get("activeDialog")
        if isinstance(active, dict) and active.get("type") == "feedback":
            active = None
        reset_keys = (
            "pendingFollowSource pendingFeedback feedbackContentId feedbackCategory feedbackCreator feedbackCreatorId "
            "feedbackContentTitle feedbackPromptText feedbackAskedForToken feedbackReminderAlertToken playbackDurationEstimateMs deferredIntent"
        )
        return User.update(handler_input, {
            **dict.fromkeys(reset_keys.split()),
            "activeDialog": active, "feedbackCandidates": [],
            "awaitingFeedback": False, "awaitingFollow": False,
            "_requiresReliableSave": True,
        })
