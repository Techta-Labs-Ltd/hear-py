from __future__ import annotations

import time
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum

from config import settings
from src.constants.state import StateSchema
from src.utils.content import ContentIdentity
from src.utils.playback import PlaybackUtils
from src.utils.playback_history import PlaybackHistoryUtils
from src.utils.user_state import UserStateNormalizer


class CommitStatus(StrEnum):
    SAVED = "saved"
    UNCHANGED = "unchanged"
    UNAVAILABLE = "load_unavailable"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class CommitResult:
    status: CommitStatus
    essential: bool = False


class EssentialPersistenceError(RuntimeError):
    def __init__(self, result: CommitResult) -> None:
        self.result = result
        super().__init__(f"Essential persistence commit did not succeed: {result.status}")


@dataclass(frozen=True, slots=True)
class PersistenceReceipt:
    versions: dict[str, int]
    snapshot: dict


class User:
    __slots__ = ()

    @staticmethod
    def snapshot(handler_input) -> dict:
        attrs = handler_input.attributes_manager.request_attributes
        return deepcopy(attrs.get("_store") or StateSchema.DEFAULT_STORE)

    @staticmethod
    def update(handler_input, updates: dict) -> dict:
        attrs = handler_input.attributes_manager.request_attributes
        store = deepcopy({**(attrs.get("_store") or StateSchema.DEFAULT_STORE), **updates})
        changed_fields = set(attrs.get("_changedFields") or ())
        changed_fields.update(key for key in updates if key in StateSchema.PERSISTED_FIELDS)
        attrs["_store"] = store
        attrs["_dirty"] = True
        attrs["_changedFields"] = tuple(sorted(changed_fields))
        handler_input.attributes_manager.request_attributes = attrs
        return deepcopy(store)

    @staticmethod
    def hydrate(handler_input, stored: dict | None, *, persistence_available: bool = True) -> dict:
        document = dict(stored) if isinstance(stored, dict) else {}
        versions = document.pop("_persistenceVersions", {})
        if not isinstance(versions, dict):
            versions = {}
        needs_canonical_copy = bool(document.pop("_persistenceNeedsCanonicalCopy", False))
        store = User.merge_persisted(document)
        transient = {
            key: value
            for key, value in handler_input.attributes_manager.request_attributes.items()
            if key
            not in {
                "_store",
                "_dirty",
                "_changedFields",
                "_persistenceAvailable",
                "_persistenceBaseline",
                "_persistenceVersions",
                "_persistenceNeedsCanonicalCopy",
            }
        }
        handler_input.attributes_manager.request_attributes = {
            **transient,
            "_store": store,
            "_dirty": needs_canonical_copy,
            "_changedFields": tuple(sorted(StateSchema.PERSISTED_FIELDS))
            if needs_canonical_copy
            else (),
            "_persistenceAvailable": persistence_available,
            "_persistenceBaseline": deepcopy(User.persisted_snapshot(store)),
            "_persistenceVersions": {
                scope: max(0, int(versions.get(scope) or 0)) for scope in StateSchema.SCOPES
            },
        }
        return store

    @staticmethod
    def hydrate_unavailable(handler_input) -> dict:
        return User.hydrate(handler_input, {}, persistence_available=False)

    @staticmethod
    def is_dirty(handler_input) -> bool:
        return bool(handler_input.attributes_manager.request_attributes.get("_dirty"))

    @staticmethod
    def persistence_available(handler_input) -> bool:
        return bool(
            handler_input.attributes_manager.request_attributes.get("_persistenceAvailable")
        )

    @staticmethod
    def changed_fields(handler_input) -> tuple[str, ...]:
        fields = handler_input.attributes_manager.request_attributes.get("_changedFields") or ()
        return tuple(field for field in fields if field in StateSchema.PERSISTED_FIELDS)

    @staticmethod
    def stage_outbox_event(handler_input, envelope: dict) -> bool:
        """Stage one immutable outbound envelope for the request commit."""
        if not isinstance(envelope, dict) or not str(envelope.get("eventId") or "").strip():
            return False
        attrs = handler_input.attributes_manager.request_attributes
        staged = list(attrs.get("_outboxEvents") or ())
        event_id = str(envelope["eventId"])
        if any(str(item.get("eventId") or "") == event_id for item in staged if isinstance(item, dict)):
            return True
        staged.append(deepcopy(envelope))
        attrs["_outboxEvents"] = staged
        handler_input.attributes_manager.request_attributes = attrs
        return True

    @staticmethod
    def staged_outbox_events(handler_input) -> tuple[dict, ...]:
        events = handler_input.attributes_manager.request_attributes.get("_outboxEvents") or ()
        return tuple(deepcopy(event) for event in events if isinstance(event, dict))

    @staticmethod
    async def read_persisted(handler_input) -> dict:
        return await handler_input.attributes_manager.persistent_attributes or {}

    @staticmethod
    async def write_persisted(handler_input, snapshot: dict) -> None:
        attrs = handler_input.attributes_manager.request_attributes
        baseline = attrs.get("_persistenceBaseline") or {}
        changed_fields = User.changed_fields(handler_input)
        payload = {
            **snapshot,
            "_persistenceVersions": dict(attrs.get("_persistenceVersions") or {}),
            "_persistenceChangedFields": list(changed_fields),
            "_persistenceOriginal": {
                field: deepcopy(baseline.get(field)) for field in changed_fields
            },
            "_persistenceCoupledCommit": User.requires_reliable_save(handler_input),
            "_persistenceOutboxEvents": list(User.staged_outbox_events(handler_input)),
        }
        handler_input.attributes_manager.persistent_attributes = payload
        receipt = await handler_input.attributes_manager.save_persistent_attributes()
        committed = receipt.snapshot if isinstance(receipt, PersistenceReceipt) else snapshot
        current = User.persisted_snapshot(User.snapshot(handler_input))
        remaining = set(User.changed_fields(handler_input))
        for field in changed_fields:
            baseline[field] = deepcopy(committed.get(field))
            if current.get(field) == snapshot.get(field):
                remaining.discard(field)
        if isinstance(receipt, PersistenceReceipt):
            attrs["_persistenceVersions"] = dict(receipt.versions)
        attrs["_persistenceBaseline"] = deepcopy(baseline)
        attrs["_changedFields"] = tuple(sorted(remaining))
        attrs["_dirty"] = bool(remaining)
        attrs.pop("_outboxEvents", None)

    @staticmethod
    def normalize_recent_track_listens(value: object) -> list:
        if not isinstance(value, list):
            return []
        cap = settings.HEAR_MAX_TRACK_LISTEN_LOG or settings.max_history
        return [entry for entry in value if isinstance(entry, dict) and entry.get("contentId")][
            :cap
        ]

    @staticmethod
    def migrate_playback(store: dict) -> dict:
        if not store.get("activePlayback") and store.get("currentContentId"):
            content_id = str(store["currentContentId"])
            offset_ms = max(0, int(store.get("lastOffsetMs") or 0))
            store["activePlayback"] = {
                "contentId": content_id,
                "token": content_id,
                "title": store.get("currentContentTitle") or store.get("feedbackContentTitle"),
                "creatorId": store.get("currentCreatorId") or store.get("feedbackCreatorId"),
                "creatorName": store.get("currentCreator") or store.get("feedbackCreator"),
                "publicationId": store.get("currentPublicationId"),
                "publicationTitle": None,
                "queueId": None,
                "queueIndex": 0,
                "audioUrl": store.get("currentAudioUrl"),
                "durationMs": int(store["currentDurationSecs"] * 1000)
                if isinstance(store.get("currentDurationSecs"), (int, float))
                else None,
                "offsetMs": offset_ms,
                "listenedMs": offset_ms,
                "sessionId": f"migrated:{content_id}",
                "status": "paused",
                "startedAt": int(time.time() * 1000),
                "updatedAt": int(time.time() * 1000),
            }
        active = store.get("activePlayback")
        if isinstance(active, dict) and active.get("contentId"):
            active.pop("alexaUserId", None)
            active["playbackSpeeds"] = active.get("playbackSpeeds") or store.get(
                "currentPlaybackSpeeds"
            )
            active["token"] = str(active["contentId"])
            active["subjectType"] = ContentIdentity.subject_type(active)
            active["subjectId"] = ContentIdentity.subject_id(active)
            active["subjectTitle"] = ContentIdentity.subject_title(active)
            active["trackContentId"] = (
                active.get("contentId") if ContentIdentity.is_publication(active) else None
            )
            active["subjectSessionId"] = active.get("subjectSessionId") or active.get("sessionId")
            active["timeSpentMs"] = max(
                0,
                int(active.get("timeSpentMs") or active.get("listenedMs") or 0),
            )
            active["timeSpentHours"] = PlaybackUtils.hours(active["timeSpentMs"])
            active["lastListeningDeltaMs"] = max(0, int(active.get("lastListeningDeltaMs") or 0))
            observation_offset = (
                active.get("observationOffsetMs")
                if active.get("observationOffsetMs") is not None
                else active.get("offsetMs")
            )
            active["observationOffsetMs"] = max(
                0, PlaybackUtils.integer(observation_offset)
            )
            active["observationTimestampMs"] = max(
                0,
                int(
                    active.get("observationTimestampMs")
                    or active.get("eventTimestamp")
                    or active.get("updatedAt")
                    or 0
                ),
            )
            store["lastToken"] = str(active["contentId"])
            store["lastOffsetMs"] = max(0, int(active.get("offsetMs") or 0))
            store["currentContentId"] = str(active["contentId"])
            store["currentContentTitle"] = active.get("title")
            store["currentCreator"] = active.get("creatorName")
            store["currentCreatorId"] = active.get("creatorId")
            store["currentCategory"] = active.get("category")
            store["currentPlaybackSpeeds"] = active.get("playbackSpeeds") or store.get(
                "currentPlaybackSpeeds"
            )
        legacy_queue = store.get("upcomingQueue")
        if not store.get("playbackQueue") and isinstance(legacy_queue, list):
            content_ids = [
                str(item.get("contentId") or item.get("id"))
                for item in legacy_queue
                if isinstance(item, dict) and (item.get("contentId") or item.get("id"))
            ]
            if content_ids:
                store["playbackQueue"] = {
                    "queueId": f"migrated:{int(time.time() * 1000)}",
                    "source": "migrated",
                    "publicationId": None,
                    "publicationTitle": None,
                    "orderedContentIds": list(dict.fromkeys(content_ids)),
                    "currentIndex": max(0, int(store.get("queueIndex") or 0)),
                    "createdAt": int(time.time() * 1000),
                }
        for key in (
            "playbackParentId",
            "playbackContentType",
            "playbackContentId",
            "currentPublicationId",
            "currentTrackIndex",
            "currentTotalTracks",
            "currentTracks",
            "upcomingQueue",
            "queueIndex",
            "queueSource",
            "queueLocality",
            "queueCategory",
            "queueItemsCompleted",
            "activeListenSession",
            "playbackSession",
            "recentTrackListens",
        ):
            store.pop(key, None)
        return store

    @staticmethod
    def merge_persisted(stored: dict | None) -> dict:
        accepted_fields = StateSchema.PERSISTED_FIELDS | StateSchema.LEGACY_PLAYBACK_FIELDS
        persisted = {
            key: value
            for key, value in (stored.items() if isinstance(stored, dict) else ())
            if key in accepted_fields
        }
        merged = {
            **StateSchema.defaults(),
            **deepcopy(persisted),
        }
        merged["recentTrackListens"] = User.normalize_recent_track_listens(
            merged.get("recentTrackListens")
        )
        merged = User.migrate_playback(merged)
        merged = User.migrate_dialog(merged)
        merged = {key: value for key, value in merged.items() if key in StateSchema.DEFAULT_STORE}
        pattern = merged.get("listeningPattern")
        if isinstance(pattern, dict):
            merged["listeningPattern"] = dict(list(pattern.items())[:40])
        merged["playHistory"] = [
            normalized
            for item in merged.get("playHistory") or []
            if (normalized := PlaybackHistoryUtils.normalize(item))
        ][: settings.max_history]
        UserStateNormalizer.feedback(merged)
        return merged

    @staticmethod
    def persisted_snapshot(store: dict) -> dict:
        if not isinstance(store, dict):
            return {}
        return UserStateNormalizer.snapshot(store)

    @staticmethod
    def requires_reliable_save(handler_input) -> bool:
        return bool(User.snapshot(handler_input).get("_requiresReliableSave")) or any(
            StateSchema.scope_for(field) in {StateSchema.PLAYBACK_SCOPE, StateSchema.DIALOG_SCOPE}
            for field in User.changed_fields(handler_input)
        )

    @staticmethod
    def _dialog_expiry(value: object) -> int:
        if value is None:
            # A missing legacy expiry is migrated to a bounded TTL by the caller.
            return 0
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            # A malformed stored timestamp must never keep a dialogue alive.
            return -1
        try:
            return int(value)
        except (TypeError, ValueError):
            return -1

    @staticmethod
    def active_dialog(store: dict | None) -> dict | None:
        state = store if isinstance(store, dict) else {}
        active = state.get("activeDialog")
        if isinstance(active, dict) and active.get("type"):
            stage = state.get("onboardingStage")
            if active.get("type") == "onboarding" and stage:
                return {
                    **active,
                    "context": {**dict(active.get("context") or {}), "stage": stage},
                }
            expires_at = User._dialog_expiry(active.get("expiresAt"))
            if active.get("type") != "onboarding" and (
                not expires_at or expires_at >= int(time.time())
            ):
                return active
            if active.get("type") != "onboarding":
                return None
        candidates: tuple[tuple[object, str, object], ...] = (
            (
                state.get("awaitingSearchConfirmation") and state.get("pendingResolution"),
                "search_confirmation",
                state.get("pendingResolution"),
            ),
            (state.get("pendingAmbiguity"), "ambiguity", state.get("pendingAmbiguity")),
            (state.get("awaitingOrganizationName"), "organization_name", {}),
            (state.get("awaitingPublicationSource"), "publication_source", {}),
            (
                state.get("onboardingStage"),
                "onboarding",
                {"stage": state.get("onboardingStage")},
            ),
            (
                state.get("awaitingReportDecision"),
                "report_decision",
                state.get("reportContext") or {},
            ),
            (
                state.get("awaitingFeedback"),
                "feedback",
                state.get("pendingFeedback") or {},
            ),
            (
                state.get("awaitingFeedbackContinuation"),
                "feedback_continuation",
                state.get("feedbackContinuation") or {},
            ),
            (state.get("awaitingResume"), "resume", state.get("activePlayback") or {}),
            (
                state.get("awaitingNotificationChoice"),
                "notification",
                state.get("pendingNotification") or {},
            ),
        )
        return next(
            (
                {"type": kind, "context": deepcopy(context)}
                for condition, kind, context in candidates
                if condition
            ),
            None,
        )

    @staticmethod
    def migrate_dialog(store: dict) -> dict:
        if not isinstance(store, dict):
            return store
        raw_active = store.get("activeDialog")
        if isinstance(raw_active, dict) and raw_active.get("type") == "creator_name":
            store["activeDialog"] = None
        store.pop("awaitingCreatorName", None)
        raw_active = store.get("activeDialog")
        raw_expiry = (
            User._dialog_expiry(raw_active.get("expiresAt"))
            if isinstance(raw_active, dict)
            else 0
        )
        if (
            isinstance(raw_active, dict)
            and raw_active.get("type")
            and raw_active.get("type") != "onboarding"
            and raw_active.get("expiresAt")
            and raw_expiry < int(time.time())
        ):
            # Do not let the legacy projections resurrect an expired canonical
            # dialogue during hydration.  TTL deletion is asynchronous, so an
            # expired Dynamo document is a normal read-time condition.
            store["activeDialog"] = None
            for flag in StateSchema.DIALOG_LEGACY_FLAGS.values():
                store[flag] = False
        active = User.active_dialog({**store, "activeDialog": store.get("activeDialog")})
        if active and not active.get("expiresAt") and active.get("type") != "onboarding":
            now = int(time.time())
            active = {**active, "createdAt": now, "expiresAt": now + 600}
        if active:
            dialog_type = active.get("type")
            fallback_contexts: dict[str, object] = {
                "feedback": store.get("pendingFeedback"),
                "report_decision": store.get("reportContext"),
                "search_confirmation": store.get("pendingResolution"),
                "ambiguity": store.get("pendingAmbiguity"),
                "latest_source": store.get("pendingLatestSource"),
                "notification": store.get("pendingNotification"),
            }
            fallback_context = (
                fallback_contexts.get(dialog_type) if isinstance(dialog_type, str) else None
            )
            if not active.get("context") and isinstance(fallback_context, dict):
                active = {**active, "context": deepcopy(fallback_context)}
        store["activeDialog"] = deepcopy(active) if active else None
        if not active:
            for flag in StateSchema.DIALOG_LEGACY_FLAGS.values():
                store[flag] = False
            store["pendingFeedback"] = None
            store["reportContext"] = None
            store["pendingResolution"] = None
            store["pendingAmbiguity"] = None
            store["pendingLatestSource"] = None
            store["pendingNotification"] = None
            store["feedbackContinuation"] = None
            return store
        dialog_type = active.get("type")
        context = deepcopy(active.get("context") or {})
        for kind, flag in StateSchema.DIALOG_LEGACY_FLAGS.items():
            store[flag] = dialog_type == kind
        if dialog_type == "feedback":
            store["pendingFeedback"] = context
            store["deferredIntent"] = deepcopy(active.get("deferredRequest"))
        elif dialog_type == "report_decision":
            store["reportContext"] = context
            store["deferredIntent"] = deepcopy(active.get("deferredRequest"))
        elif dialog_type == "search_confirmation":
            store["pendingResolution"] = context
        elif dialog_type == "ambiguity":
            store["pendingAmbiguity"] = context
        elif dialog_type == "latest_source":
            store["pendingLatestSource"] = context
        elif dialog_type == "notification":
            store["pendingNotification"] = context
        return store

    @staticmethod
    def persistence_key(request_envelope: dict) -> str:
        if not request_envelope or not isinstance(request_envelope, dict):
            return "__invalid_envelope__"
        context_user = (
            (request_envelope.get("context") or {}).get("System", {}).get("user", {}).get("userId")
        )
        if context_user:
            return context_user
        session = request_envelope.get("session") or {}
        session_user = (session.get("user") or {}).get("userId")
        if session_user:
            return session_user
        if session.get("sessionId"):
            return f"session:{session['sessionId']}"
        return "__no_identity__"

    @staticmethod
    def canonical_persistence_key(listener_id: str) -> str:
        stage = str(settings.STAGE or "development").strip().lower()
        return f"listener:{stage}:{str(listener_id).strip()}"

    @staticmethod
    def configure_persistence_identity(
        handler_input,
        *,
        listener_id: str | None,
        alexa_user_id: str | None,
    ) -> None:
        configure = getattr(
            handler_input.attributes_manager,
            "configure_persistence",
            None,
        )
        if not callable(configure):
            return
        primary = (
            User.canonical_persistence_key(listener_id)
            if listener_id and str(listener_id).strip()
            else alexa_user_id
        )
        configure(primary_key=primary, fallback_key=alexa_user_id if listener_id else None)
