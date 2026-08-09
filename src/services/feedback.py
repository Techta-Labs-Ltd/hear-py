from __future__ import annotations
from src.services.store import get_store, update_store
from src.utils.skill_request import get_intent_name, get_request_type
from src.utils.speech import (
    FEEDBACK_AWAITING_REPROMPT,
    LAUNCH_PENDING_FEEDBACK,
    escape_ssml_lite,
    humanize_spoken_title,
    ssml,
)
import time
from src.services.dialog_state import activate_dialog
from src.clients.alexa import cancel_feedback_reminder
from src.services.queue import read_playback_queue


class FeedbackService:
    rating_intents = {
        "FeedbackEnjoyedIntent",
        "FeedbackSomewhatIntent",
        "FeedbackNotEnjoyedIntent",
        "SkipFeedbackIntent",
    }
    replay_intents = {"AMAZON.RepeatIntent", "AMAZON.StartOverIntent"}
    follow_intents = {"FollowCreatorIntent", "UnfollowCreatorIntent"}
    report_intents = {"ReportCreatorIntent", "ReportContentIntent"}
    transport_intents = {
        "AMAZON.NextIntent",
        "AMAZON.SkipIntent",
        "AMAZON.PreviousIntent",
        "AMAZON.PauseIntent",
        "AMAZON.ResumeIntent",
    }
    transport_request_types = {
        "PlaybackController.NextCommandIssued",
        "PlaybackController.PreviousCommandIssued",
        "PlaybackController.PauseCommandIssued",
        "PlaybackController.PlayCommandIssued",
    }

    def should_evaluate(self, handler_input) -> bool:
        request_type = get_request_type(handler_input)
        if request_type.startswith("AudioPlayer."):
            return False
        if request_type == "SessionEndedRequest":
            return False
        if request_type == "IntentRequest" and get_intent_name(handler_input) in {
            "AMAZON.StopIntent",
            "AMAZON.CancelIntent",
        }:
            return False
        return get_store(handler_input).get("onboardingStage") != "ask_town"

    def should_block(self, handler_input) -> bool:
        if not self.should_evaluate(handler_input):
            return False
        request_type = get_request_type(handler_input)
        if request_type in self.transport_request_types:
            return False
        store = get_store(handler_input)
        pending = store.get("pendingFeedback") or {}
        if store.get("awaitingFeedback") and pending.get("completed") is False:
            update_store(handler_input, {
                "pendingFeedback": None,
                "awaitingFeedback": False,
                "activeDialog": None,
            })
            return False
        if not store.get("awaitingFeedback"):
            self.clear_stale_state(handler_input)
            return False
        if request_type != "IntentRequest":
            return True
        intent_name = get_intent_name(handler_input)
        allowed = (
            self.rating_intents
            | self.replay_intents
            | self.report_intents
            | self.transport_intents
            | {"AMAZON.YesIntent", "AMAZON.NoIntent"}
        )
        return intent_name not in allowed

    def clear_stale_state(self, handler_input) -> None:
        if get_request_type(handler_input) != "IntentRequest":
            return
        store = get_store(handler_input)
        intent_name = get_intent_name(handler_input)
        if store.get("awaitingFollow"):
            if intent_name not in self.follow_intents | {"AMAZON.NoIntent"}:
                update_store(handler_input, {
                    "awaitingFollow": False,
                    "pendingFollowSource": None,
                })
            return
        if store.get("awaitingReportDecision"):
            allowed = self.report_intents | {"SkipFeedbackIntent", "AMAZON.NoIntent"}
            if intent_name not in allowed:
                update_store(handler_input, {"awaitingReportDecision": False})

    def pending_response(self, handler_input):
        store = get_store(handler_input)
        pending = store.get("pendingFeedback") or {}
        title = humanize_spoken_title(
            pending.get("title") or store.get("feedbackContentTitle")
        ) or "that track"
        creator_name = (
            pending.get("organizationName")
            or pending.get("creatorName")
            or store.get("feedbackCreator")
        )
        creator = (
            escape_ssml_lite(creator_name)
            if creator_name
            else "the creator"
        )
        user_name = (
            store.get("userName")
            or store.get("givenName")
            or store.get("fullName")
        )
        if pending.get("subjectType") == "publication":
            speech = (
                f"You listened to {escape_ssml_lite(title)}. "
                "Did you enjoy this publication? Say enjoyed, it was okay, "
                "not enjoyed, or skip."
            )
        else:
            speech = LAUNCH_PENDING_FEEDBACK(title, creator, user_name)
        return (
            handler_input.response_builder
            .speak(ssml(speech))
            .reprompt(ssml(FEEDBACK_AWAITING_REPROMPT))
            .with_should_end_session(False)
            .get_response()
        )

    # ---------------------------------------------------------- static helpers

    @staticmethod
    def _safe_int(value, default: int = 0) -> int:
        try:
            return int(value or default)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _feedback_key(state: dict) -> str | None:
        return state.get("contentId")

    @staticmethod
    def _publication_is_last_track(state: dict, store: dict) -> bool:
        track_index = state.get("trackIndex")
        track_count = state.get("trackCount")
        if isinstance(track_index, int) and isinstance(track_count, int) and track_count > 0:
            if track_index + 1 >= track_count:
                return True
        queue = read_playback_queue(store)
        return bool(
            queue
            and queue.get("publicationId") == state.get("publicationId")
            and int(queue.get("currentIndex") or 0) >= len(queue["orderedContentIds"]) - 1
        )

    @staticmethod
    def _publication_coverage(progress: dict) -> tuple[float, int]:
        tracks = progress.get("tracks") or {}
        expected = max(1, FeedbackService._safe_int(
            progress.get("expectedTrackCount"), len(tracks) or 1,
        ))
        meaningful = 0
        listened_total = 0
        for track in tracks.values():
            listened = max(0, FeedbackService._safe_int(track.get("listenedMs")))
            duration = max(0, FeedbackService._safe_int(track.get("durationMs")))
            listened_total += min(listened, duration) if duration else listened
            threshold = duration * 0.5 if duration else 60_000
            if track.get("completed") or listened >= threshold:
                meaningful += 1
        total_duration = max(0, FeedbackService._safe_int(progress.get("expectedDurationMs")))
        coverage = (
            min(1.0, listened_total / total_duration)
            if total_duration > 0
            else min(1.0, meaningful / expected)
        )
        return coverage, meaningful

    @staticmethod
    def update_publication_progress(
        handler_input,
        state: dict,
        *,
        completed: bool = False,
    ) -> dict | None:
        publication_id = state.get("publicationId")
        content_id = state.get("contentId")
        if not publication_id or not content_id:
            return None
        store = get_store(handler_input)
        all_progress = dict(store.get("publicationFeedbackProgress") or {})
        current = dict(all_progress.get(str(publication_id)) or {})
        queue = read_playback_queue(store)
        expected_count = max(
            FeedbackService._safe_int(current.get("expectedTrackCount")),
            FeedbackService._safe_int(state.get("trackCount")),
            FeedbackService._safe_int((queue or {}).get("publicationTrackCount"))
            if (queue or {}).get("publicationId") == publication_id else 0,
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
        tracks[str(content_id)] = {
            "listenedMs": max(
                FeedbackService._safe_int(existing_track.get("listenedMs")),
                FeedbackService._safe_int(state.get("listenedMs")),
            ),
            "durationMs": max(
                FeedbackService._safe_int(existing_track.get("durationMs")),
                FeedbackService._safe_int(state.get("durationMs")),
            ),
            "completed": bool(existing_track.get("completed") or completed),
        }
        tracks = dict(list(tracks.items())[-100:])
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
            candidate for candidate in (store.get("feedbackCandidates") or [])
            if not (
                candidate.get("publicationId") == publication_id
                and candidate.get("subjectType") != "publication"
            )
        ]
        update_store(handler_input, {
            "publicationFeedbackProgress": all_progress,
            "feedbackCandidates": legacy_candidates,
        })
        return progress

    @staticmethod
    def finalize_publication(
        handler_input,
        publication_id: str | None,
    ) -> dict | None:
        if not publication_id:
            return None
        store = get_store(handler_input)
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
            update_store(handler_input, {"publicationFeedbackProgress": all_progress})
            return None
        if not eligible:
            progress["closedAt"] = int(time.time() * 1000)
            progress["coverage"] = coverage
            progress["meaningfulTrackCount"] = meaningful
            all_progress[str(publication_id)] = progress
            update_store(handler_input, {"publicationFeedbackProgress": all_progress})
            return None
        all_progress.pop(str(publication_id), None)
        updates = {"publicationFeedbackProgress": all_progress}
        listened_ms = sum(
            FeedbackService._safe_int(track.get("listenedMs"))
            for track in (progress.get("tracks") or {}).values()
            if isinstance(track, dict)
        )
        candidate = {
            "feedbackKey": key,
            "subjectType": "publication",
            "contentId": progress.get("representativeContentId"),
            "publicationId": str(publication_id),
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
            "completed": True,
            "sessionId": key,
            "createdAt": int(time.time() * 1000),
        }
        existing = [
            item for item in (store.get("feedbackCandidates") or [])
            if item.get("feedbackKey") != key
        ]
        updates["feedbackCandidates"] = (existing + [candidate])[-20:]
        update_store(handler_input, updates)
        return candidate

    @staticmethod
    def finalize_other_publications(handler_input, next_publication_id: str | None) -> bool:
        store = get_store(handler_input)
        progress_ids = list((store.get("publicationFeedbackProgress") or {}).keys())
        created = False
        for publication_id in progress_ids:
            if str(publication_id) != str(next_publication_id or ""):
                created = bool(
                    FeedbackService.finalize_publication(handler_input, publication_id)
                ) or created
        return created

    @staticmethod
    def record_candidate(handler_input, state: dict, *, completed: bool) -> dict | None:
        if not completed:
            return None
        if state.get("publicationId"):
            FeedbackService.update_publication_progress(
                handler_input, state, completed=True,
            )
            if FeedbackService._publication_is_last_track(state, get_store(handler_input)):
                return FeedbackService.finalize_publication(
                    handler_input, str(state["publicationId"]),
                )
            return None
        key = FeedbackService._feedback_key(state)
        listened_ms = max(0, int(state.get("listenedMs") or 0))
        if not key:
            return None
        store = get_store(handler_input)
        if key in (store.get("answeredFeedbackKeys") or []):
            return None
        candidate = {
            "feedbackKey": key,
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
            "completed": bool(completed),
            "sessionId": state.get("sessionId"),
            "createdAt": int(time.time() * 1000),
        }
        existing = [
            value for value in (store.get("feedbackCandidates") or [])
            if value.get("feedbackKey") != key
        ]
        update_store(handler_input, {"feedbackCandidates": (existing + [candidate])[-20:]})
        return candidate

    @staticmethod
    def activate_best(handler_input) -> dict | None:
        store = get_store(handler_input)
        if store.get("awaitingFeedback"):
            return store.get("pendingFeedback")
        candidates = [
            item for item in (store.get("feedbackCandidates") or [])
            if item.get("completed") is True
            if item.get("feedbackKey") not in (store.get("answeredFeedbackKeys") or [])
        ]
        if not candidates:
            return None
        candidates.sort(
            key=lambda item: (
                bool(item.get("completed")),
                int(item.get("listenedMs") or 0),
                int(item.get("createdAt") or 0),
            ),
            reverse=True,
        )
        selected = candidates[0]
        session_id = selected.get("sessionId")
        remaining = [item for item in candidates if item.get("sessionId") != session_id]
        update_store(handler_input, {
            "pendingFeedback": selected,
            "feedbackCandidates": remaining,
            "awaitingFeedback": True,
            "_requiresReliableSave": True,
        })
        activate_dialog(handler_input, "feedback", context=selected)
        return selected

    @staticmethod
    def mark_answered(handler_input) -> dict:
        store = get_store(handler_input)
        pending = store.get("pendingFeedback") or {}
        key = pending.get("feedbackKey")
        answered = list(store.get("answeredFeedbackKeys") or [])
        if key and key not in answered:
            answered.append(key)
        return update_store(handler_input, {
            "answeredFeedbackKeys": answered[-100:],
            "pendingFeedback": None,
            "awaitingFeedback": False,
            "activeDialog": None,
            "_requiresReliableSave": False,
            "deferredIntent": None,
            "pendingFollowSource": None,
        })

    @staticmethod
    async def submit(handler_input, value: str) -> dict:
        store = get_store(handler_input)
        pending = dict(store.get("pendingFeedback") or {})
        history = list(store.get("feedbackHistory") or [])
        history.append({
            "feedbackKey": pending.get("feedbackKey"),
            "subjectType": pending.get("subjectType") or "content",
            "value": str(value),
            "contentId": pending.get("contentId"),
            "publicationId": pending.get("publicationId"),
            "title": pending.get("title"),
            "creatorId": pending.get("creatorId"),
            "organizationId": pending.get("organizationId"),
            "coverage": pending.get("coverage"),
            "recordedAt": int(time.time() * 1000),
        })
        update_store(handler_input, {"feedbackHistory": history[-100:]})
        return FeedbackService.mark_answered(handler_input)

    @staticmethod
    async def clear(handler_input) -> dict:
        try:
            await cancel_feedback_reminder(handler_input)
        except Exception:
            pass
        return update_store(handler_input, {
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
            "pendingFollowSource": None,
        })

    @staticmethod
    def dismiss(handler_input) -> dict:
        return update_store(handler_input, {
            "awaitingFeedback": False,
            "pendingFeedback": None,
            "feedbackPromptText": None,
            "feedbackAskedForToken": None,
            "feedbackReminderAlertToken": None,
            "deferredIntent": None,
        })


feedback_service = FeedbackService()

record_feedback_candidate = feedback_service.record_candidate
activate_best_feedback_candidate = feedback_service.activate_best
mark_pending_feedback_answered = feedback_service.mark_answered
submit_feedback = feedback_service.submit
clear_feedback = feedback_service.clear
dismiss_feedback_prompt = feedback_service.dismiss
update_publication_feedback_progress = feedback_service.update_publication_progress
finalize_publication_feedback = feedback_service.finalize_publication
finalize_other_publication_feedback = feedback_service.finalize_other_publications
