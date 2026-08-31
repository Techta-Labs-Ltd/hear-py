from __future__ import annotations

import time
from copy import deepcopy

from config import settings
from src.constants.persistence import PersistenceConstants
from src.constants.state import StateSchema


class UserStateNormalizer:
    @staticmethod
    def value(value, depth: int = 0):
        if depth >= 8:
            return None
        if isinstance(value, str):
            return value[: max(settings.HEAR_PERSISTED_TEXT_LIMIT, 1)]
        if isinstance(value, list):
            limit = max(settings.HEAR_PERSISTED_COLLECTION_LIMIT, 1)
            return [UserStateNormalizer.value(item, depth + 1) for item in value[:limit]]
        if isinstance(value, dict):
            limit = max(settings.HEAR_PERSISTED_COLLECTION_LIMIT, 1)
            return {
                str(key): UserStateNormalizer.value(item, depth + 1)
                for key, item in list(value.items())[:limit]
            }
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return str(value)[: max(settings.HEAR_PERSISTED_TEXT_LIMIT, 1)]

    @staticmethod
    def snapshot(store: dict) -> dict:
        normalized = {
            key: UserStateNormalizer.value(value)
            for key, value in store.items()
            if key in PersistenceConstants.PERSISTED_FIELDS
        }
        queue = normalized.get("playbackQueue")
        if isinstance(queue, dict) and isinstance(queue.get("orderedContentIds"), list):
            queue["orderedContentIds"] = queue["orderedContentIds"][
                : max(settings.HEAR_PERSISTED_COLLECTION_LIMIT, 1)
            ]
            queue["currentIndex"] = min(
                max(0, int(queue.get("currentIndex") or 0)),
                max(len(queue["orderedContentIds"]) - 1, 0),
            )
        return normalized

    @staticmethod
    def followed_creators(value) -> list:
        if not isinstance(value, list):
            return []
        normalized = []
        seen = set()
        for item in value:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            source_type = "organization" if item.get("type") == "organization" else "creator"
            key = (source_type, str(item["id"]))
            if key in seen:
                continue
            seen.add(key)
            normalized.append(
                {"id": str(item["id"]), "name": item.get("name"), "type": source_type}
            )
        return normalized[-50:]

    @staticmethod
    def publication_progress(value) -> dict:
        if not isinstance(value, dict):
            return {}
        capped = {}
        ordered = sorted(
            value.items(), key=lambda pair: int((pair[1] or {}).get("updatedAt") or 0)
        )[-5:]
        for publication_id, progress in ordered:
            if not isinstance(progress, dict):
                continue
            tracks = progress.get("tracks") or {}
            if isinstance(tracks, dict):
                tracks = dict(list(tracks.items())[-100:])
            capped[str(publication_id)] = {**progress, "tracks": tracks}
        return capped

    @staticmethod
    def history(value) -> list:
        return (
            [item for item in value if isinstance(item, dict)][-100:]
            if isinstance(value, list)
            else []
        )

    @staticmethod
    def feedback(store: dict) -> None:
        pending = store.get("pendingFeedback")
        if (
            not isinstance(pending, dict)
            or not pending.get("publicationId")
            or pending.get("subjectType") == "publication"
        ):
            return
        store["pendingFeedback"] = None
        store["awaitingFeedback"] = False
        dialog = store.get("activeDialog") or {}
        if (dialog.get("type") or dialog.get("kind")) == "feedback":
            store["activeDialog"] = None


class User:
    __slots__ = ()

    @staticmethod
    def snapshot(handler_input) -> dict:
        attrs = handler_input.attributes_manager.request_attributes
        return dict(attrs.get("_store") or StateSchema.DEFAULT_STORE)

    @staticmethod
    def update(handler_input, updates: dict) -> dict:
        attrs = handler_input.attributes_manager.request_attributes
        store = {**(attrs.get("_store") or StateSchema.DEFAULT_STORE), **updates}
        changed_fields = set(attrs.get("_changedFields") or ())
        changed_fields.update(
            key for key in updates if key in PersistenceConstants.PERSISTED_FIELDS
        )
        attrs["_store"] = store
        attrs["_dirty"] = True
        attrs["_changedFields"] = tuple(sorted(changed_fields))
        handler_input.attributes_manager.request_attributes = attrs
        return store

    @staticmethod
    def hydrate(handler_input, stored: dict | None, *, persistence_available: bool = True) -> dict:
        document = dict(stored) if isinstance(stored, dict) else {}
        version = max(0, int(document.pop("_persistenceVersion", 0) or 0))
        store = User.merge_persisted(document)
        handler_input.attributes_manager.request_attributes = {
            "_store": store,
            "_dirty": False,
            "_changedFields": (),
            "_persistenceAvailable": persistence_available,
            "_persistenceBaseline": deepcopy(User.persisted_snapshot(store)),
            "_persistenceVersion": version,
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
        return tuple(field for field in fields if field in PersistenceConstants.PERSISTED_FIELDS)

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
            "_persistenceVersion": max(0, int(attrs.get("_persistenceVersion") or 0)),
            "_persistenceChangedFields": list(changed_fields),
            "_persistenceOriginal": {
                field: deepcopy(baseline.get(field)) for field in changed_fields
            },
        }
        handler_input.attributes_manager.persistent_attributes = payload
        await handler_input.attributes_manager.save_persistent_attributes()

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
        merged = {
            **StateSchema.DEFAULT_STORE,
            **(stored if isinstance(stored, dict) else {}),
        }
        merged["recentTrackListens"] = User.normalize_recent_track_listens(
            merged.get("recentTrackListens")
        )
        merged = User.migrate_playback(merged)
        merged = User.migrate_dialog(merged)
        merged = {
            key: value
            for key, value in merged.items()
            if key in PersistenceConstants.PERSISTED_FIELDS
        }
        pattern = merged.get("listeningPattern")
        if isinstance(pattern, dict):
            merged["listeningPattern"] = dict(list(pattern.items())[:40])
        merged["followedCreators"] = UserStateNormalizer.followed_creators(
            merged.get("followedCreators")
        )
        merged["publicationFeedbackProgress"] = UserStateNormalizer.publication_progress(
            merged.get("publicationFeedbackProgress")
        )
        for history_key in ("feedbackHistory", "reportHistory"):
            merged[history_key] = UserStateNormalizer.history(merged.get(history_key))
        UserStateNormalizer.feedback(merged)
        return merged

    @staticmethod
    def persisted_snapshot(store: dict) -> dict:
        if not isinstance(store, dict):
            return {}
        return UserStateNormalizer.snapshot(store)

    @staticmethod
    def requires_reliable_save(handler_input) -> bool:
        return bool(User.snapshot(handler_input).get("_requiresReliableSave"))

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
            expires_at = int(active.get("expiresAt") or 0)
            if active.get("type") != "onboarding" and (
                not expires_at or expires_at >= int(time.time())
            ):
                return active
        candidates = (
            (
                state.get("awaitingSearchConfirmation") and state.get("pendingResolution"),
                "search_confirmation",
                state.get("pendingResolution"),
            ),
            (state.get("pendingAmbiguity"), "ambiguity", state.get("pendingAmbiguity")),
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
            (state.get("awaitingResume"), "resume", state.get("activePlayback") or {}),
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
        active = User.active_dialog({**store, "activeDialog": store.get("activeDialog")})
        store["activeDialog"] = deepcopy(active) if active else None
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
