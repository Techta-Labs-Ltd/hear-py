from unittest.mock import AsyncMock

import pytest

from src.constants.state import StateSchema
from src.container import ApplicationContainer
from src.middleware.persistence import SavePersistenceInterceptor
from src.models.browse import Browse
from src.models.playback_history import PlaybackHistory
from src.models.playback_state import PlaybackQueue
from src.models.social import FollowingManager
from src.models.user import User


class TestPersistence:
    def test_default_store_has_key_fields(self):
        assert "lastToken" in StateSchema.DEFAULT_STORE
        assert "locality" in StateSchema.DEFAULT_STORE
        assert "playbackSpeed" in StateSchema.DEFAULT_STORE
        assert "playbackQueue" in StateSchema.DEFAULT_STORE
        assert "activePlayback" in StateSchema.DEFAULT_STORE
        assert "followedCreators" in StateSchema.DEFAULT_STORE

    def test_merge_initial_store_preserves_defaults(self):
        merged = User.merge_persisted({})
        assert merged["playbackSpeed"] == 1.0
        assert merged["playbackQueue"] is None

    def test_merge_initial_store_overrides(self):
        merged = User.merge_persisted({"playbackSpeed": 2.0, "userCity": "London"})
        assert merged["playbackSpeed"] == 2.0
        assert merged["userCity"] == "London"

    def test_default_state_serializes_to_an_empty_sparse_document(self):
        assert User.persisted_snapshot(dict(StateSchema.DEFAULT_STORE)) == {}

    def test_backend_owned_history_and_profile_pii_are_not_persisted(self):
        snapshot = User.persisted_snapshot(
            {
                **StateSchema.DEFAULT_STORE,
                "listenerId": "listener-1",
                "userEmail": "listener@example.com",
                "userName": "Listener",
                "feedbackHistory": [{"value": "enjoyed"}],
                "reportHistory": [{"subjectId": "content-1"}],
                "playHistory": [
                    {
                        "contentId": "content-1",
                        "timeSpentMs": 1000,
                        "sessions": {"session-1": {"timeSpentMs": 1000}},
                    }
                ],
            }
        )

        assert "listenerId" not in snapshot
        assert "userEmail" not in snapshot
        assert "userName" not in snapshot
        assert "feedbackHistory" not in snapshot
        assert "reportHistory" not in snapshot
        assert "sessions" not in snapshot["playHistory"][0]

    def test_merge_initial_store_clears_legacy_publication_track_feedback(self):
        merged = User.merge_persisted(
            {
                "awaitingFeedback": True,
                "pendingFeedback": {
                    "feedbackKey": "track-1",
                    "contentId": "track-1",
                    "publicationId": "publication-1",
                },
                "activeDialog": {"type": "feedback"},
            }
        )
        assert merged["awaitingFeedback"] is False
        assert merged["pendingFeedback"] is None
        assert merged["activeDialog"] is None

    def test_get_store_returns_copy(self, mock_handler_input):
        mock_handler_input.attributes_manager.request_attributes["_store"] = {"playCount": 5}
        store = User.snapshot(mock_handler_input)
        assert store["playCount"] == 5
        store["playCount"] = 10
        store2 = User.snapshot(mock_handler_input)
        assert store2["playCount"] == 5

    def test_update_store_mutates_and_marks_dirty(self, mock_handler_input):
        mock_handler_input.attributes_manager.request_attributes["_store"] = dict(
            StateSchema.DEFAULT_STORE
        )
        updated = User.update(mock_handler_input, {"playCount": 1})
        assert updated["playCount"] == 1
        assert mock_handler_input.attributes_manager.request_attributes["_dirty"] is True

    def test_hydration_retains_version_and_tracks_only_changed_fields(self, mock_handler_input):
        User.hydrate(
            mock_handler_input,
            {"playCount": 2, "userCity": "London"},
        )
        User.update(mock_handler_input, {"playCount": 3, "_requiresReliableSave": True})
        attrs = mock_handler_input.attributes_manager.request_attributes
        assert User.changed_fields(mock_handler_input) == ("playCount",)
        assert attrs["_persistenceBaseline"]["playCount"] == 2

    def test_unavailable_hydration_disables_persistence(self, mock_handler_input):
        User.hydrate_unavailable(mock_handler_input)
        User.update(mock_handler_input, {"playCount": 1})
        assert User.persistence_available(mock_handler_input) is False

    def test_persisted_snapshot_bounds_external_payloads(self, monkeypatch):
        monkeypatch.setattr("src.models.user.settings.HEAR_PERSISTED_COLLECTION_LIMIT", 2)
        monkeypatch.setattr("src.models.user.settings.HEAR_PERSISTED_TEXT_LIMIT", 8)
        snapshot = User.persisted_snapshot(
            {
                "pendingResolution": {"label": "abcdefghijklmnop", "items": [1, 2, 3]},
                "playbackQueue": {
                    "orderedContentIds": ["one", "two", "three"],
                    "currentIndex": 9,
                },
            }
        )
        assert snapshot["pendingResolution"] == {"label": "abcdefgh", "items": [1, 2]}
        assert snapshot["playbackQueue"]["orderedContentIds"] == ["one", "two"]
        assert snapshot["playbackQueue"]["currentIndex"] == 1

    @pytest.mark.asyncio
    async def test_degraded_load_never_overwrites_persisted_state(
        self, monkeypatch, mock_handler_input
    ):
        User.hydrate_unavailable(mock_handler_input)
        User.update(mock_handler_input, {"playCount": 1})
        writer = AsyncMock()
        monkeypatch.setattr(User, "write_persisted", writer)
        await SavePersistenceInterceptor().process(mock_handler_input)
        writer.assert_not_awaited()

    def test_add_to_history(self, mock_handler_input):
        mock_handler_input.attributes_manager.request_attributes["_store"] = dict(
            StateSchema.DEFAULT_STORE
        )
        store = PlaybackHistory.add(mock_handler_input, "content_001")
        assert any((h["id"] == "content_001" for h in store["playHistory"]))

    def test_publication_history_is_one_subject_with_latest_track_cursor(
        self, mock_handler_input
    ):
        mock_handler_input.attributes_manager.request_attributes["_store"] = dict(
            StateSchema.DEFAULT_STORE
        )
        first = {
            "contentId": "track-1",
            "publicationId": "publication-1",
            "publicationTitle": "Weekly publication",
            "audioUrl": "https://cdn.hear.media/track-1.mp3",
            "trackIndex": 0,
            "trackCount": 2,
        }
        second = {
            **first,
            "contentId": "track-2",
            "audioUrl": "https://cdn.hear.media/track-2.mp3",
            "trackIndex": 1,
        }

        PlaybackHistory.add(mock_handler_input, first)
        store = PlaybackHistory.add(mock_handler_input, second)

        assert len(store["playHistory"]) == 1
        entry = store["playHistory"][0]
        assert entry["id"] == "publication-1"
        assert entry["subjectType"] == "publication"
        assert entry["subjectId"] == "publication-1"
        assert entry["trackContentId"] == "track-2"
        assert "contentId" not in entry

    def test_standalone_history_remains_individual_content(self, mock_handler_input):
        mock_handler_input.attributes_manager.request_attributes["_store"] = dict(
            StateSchema.DEFAULT_STORE
        )
        PlaybackHistory.add(
            mock_handler_input,
            {
                "contentId": "track-1",
                "audioUrl": "https://cdn.hear.media/track-1.mp3",
            },
        )
        store = PlaybackHistory.add(
            mock_handler_input,
            {
                "contentId": "track-2",
                "audioUrl": "https://cdn.hear.media/track-2.mp3",
            },
        )

        assert [entry["subjectId"] for entry in store["playHistory"]] == [
            "track-2",
            "track-1",
        ]
        assert all(entry["subjectType"] == "content" for entry in store["playHistory"])

    def test_publication_history_sums_track_sessions_and_keeps_track_breakdown(
        self, mock_handler_input
    ):
        mock_handler_input.attributes_manager.request_attributes["_store"] = dict(
            StateSchema.DEFAULT_STORE
        )
        first = {
            "contentId": "track-1",
            "publicationId": "publication-1",
            "publicationTitle": "Weekly publication",
            "sessionId": "session-1",
            "trackIndex": 0,
            "trackCount": 2,
            "offsetMs": 1800000,
            "listenedMs": 1800000,
            "timeSpentMs": 1800000,
        }
        second = {
            **first,
            "contentId": "track-2",
            "sessionId": "session-2",
            "trackIndex": 1,
            "offsetMs": 900000,
            "listenedMs": 900000,
            "timeSpentMs": 900000,
        }

        PlaybackHistory.update(mock_handler_input, first)
        store = PlaybackHistory.update(mock_handler_input, second)
        history = store["playHistory"][0]

        assert history["subjectId"] == "publication-1"
        assert history["tracks"]["track-1"]["timeSpentMs"] == 1800000
        assert history["tracks"]["track-2"]["timeSpentMs"] == 900000
        assert history["timeSpentMs"] == 2700000
        assert history["timeSpentHours"] == 0.75

    def test_publication_track_transition_keeps_subject_session_and_updates_cursor(
        self, mock_handler_input
    ):
        mock_handler_input.attributes_manager.request_attributes["_store"] = dict(
            StateSchema.DEFAULT_STORE
        )
        tracks = [
            {
                "contentId": "track-1",
                "publicationId": "publication-1",
                "publicationTitle": "Weekly publication",
                "audioUrl": "https://cdn.hear.media/track-1.mp3",
                "trackIndex": 0,
                "trackCount": 2,
            },
            {
                "contentId": "track-2",
                "publicationId": "publication-1",
                "publicationTitle": "Weekly publication",
                "audioUrl": "https://cdn.hear.media/track-2.mp3",
                "trackIndex": 1,
                "trackCount": 2,
            },
        ]
        playback = ApplicationContainer().playback

        first = playback.start_session(
            mock_handler_input,
            tracks[0],
            queue_id="queue-1",
            queue_index=0,
        )
        second = playback.start_session(
            mock_handler_input,
            tracks[1],
            queue_id="queue-1",
            queue_index=1,
        )

        assert first["sessionId"] != second["sessionId"]
        assert first["subjectSessionId"] == second["subjectSessionId"]
        assert second["subjectId"] == "publication-1"
        assert second["trackContentId"] == "track-2"
        history = User.snapshot(mock_handler_input)["playHistory"]
        assert len(history) == 1
        assert history[0]["subjectId"] == "publication-1"
        assert history[0]["trackContentId"] == "track-2"

    def test_queue_restores_publication_identity_to_individually_fetched_track(
        self, mock_handler_input
    ):
        store = {
            **StateSchema.DEFAULT_STORE,
            "playbackQueue": {
                "queueId": "queue-1",
                "source": "publication",
                "publicationId": "publication-1",
                "publicationTitle": None,
                "publicationTrackCount": 5,
                "orderedContentIds": ["track-1", "track-2", "track-3"],
                "currentIndex": 1,
            },
        }
        fetched = {
            "contentId": "track-3",
            "title": "Third track",
            "audioUrl": "https://cdn.hear.media/track-3.mp3",
            "subjectType": "content",
            "subjectId": "track-3",
        }

        content = PlaybackQueue.apply_publication_context(store, fetched)

        assert content["publicationId"] == "publication-1"
        assert content["publicationTitle"] is None
        assert content["subjectType"] == "publication"
        assert content["subjectId"] == "publication-1"
        assert content["trackContentId"] == "track-3"
        assert content["trackIndex"] == 2
        assert content["trackCount"] == 5

    def test_add_followed_creator(self, mock_handler_input):
        mock_handler_input.attributes_manager.request_attributes["_store"] = dict(
            StateSchema.DEFAULT_STORE
        )
        store = FollowingManager.add(mock_handler_input, "creator_1", "Test Creator")
        assert FollowingManager.is_following(store, "creator_1")

    def test_recent_content_ids(self, mock_handler_input):
        store = dict(StateSchema.DEFAULT_STORE)
        store["currentContentId"] = "content_001"
        store["feedbackContentId"] = "content_002"
        ids = PlaybackQueue.recent_content_ids(store)
        assert "content_001" in ids
        assert "content_002" in ids

    def test_clear_queue(self, mock_handler_input):
        mock_handler_input.attributes_manager.request_attributes["_store"] = dict(
            StateSchema.DEFAULT_STORE
        )
        queues = PlaybackQueue(User())
        store = queues.initialize(mock_handler_input, [{"contentId": "1"}, {"contentId": "2"}])
        assert store["playbackQueue"]["orderedContentIds"] == ["1", "2"]
        store = queues.clear(mock_handler_input)
        assert store["playbackQueue"] is None

    def test_publication_queue_preserves_parent_and_track_metadata(self, mock_handler_input):
        mock_handler_input.attributes_manager.request_attributes["_store"] = dict(
            StateSchema.DEFAULT_STORE
        )
        tracks = [
            {
                "contentId": "track-1",
                "publicationId": "publication-1",
                "publicationTitle": "Weekly publication",
                "isPublication": True,
                "trackIndex": 0,
                "trackCount": 2,
                "audioUrl": "https://cdn.hear.media/track-1.mp3",
            },
            {
                "contentId": "track-2",
                "publicationId": "publication-1",
                "publicationTitle": "Weekly publication",
                "isPublication": True,
                "trackIndex": 1,
                "trackCount": 2,
                "audioUrl": "https://cdn.hear.media/track-2.mp3",
            },
        ]
        store = PlaybackQueue(User()).initialize(mock_handler_input, tracks)
        assert store["playbackQueue"]["orderedContentIds"] == ["track-1", "track-2"]
        assert store["playbackQueue"]["publicationId"] == "publication-1"
        assert store["playbackQueue"]["publicationTitle"] == "Weekly publication"
        store = Browse(deps=ApplicationContainer()).set_catalog(
            mock_handler_input, {"items": tracks}
        )
        cached = store["browseQueueItems"][1]
        assert cached["publicationId"] == "publication-1"
        assert cached["trackIndex"] == 1
        assert cached["trackCount"] == 2

    def test_browse_queue_cache_preserves_canonical_playback_fields(self, mock_handler_input):
        mock_handler_input.attributes_manager.request_attributes["_store"] = dict(
            StateSchema.DEFAULT_STORE
        )
        content = {
            "contentId": "content-2",
            "title": "Second bulletin",
            "spokenTitle": "Second bulletin",
            "creatorId": "creator-1",
            "creatorName": "York Talking News",
            "audioUrl": "https://cdn.hear.media/content-2.mp3",
            "durationMs": 180000,
            "playbackSpeeds": [],
        }
        store = Browse(deps=ApplicationContainer()).set_catalog(
            mock_handler_input, {"items": [content]}
        )
        cached = store["browseQueueItems"][0]
        assert cached["contentId"] == "content-2"
        assert cached["audioUrl"] == content["audioUrl"]
        assert cached["durationMs"] == 180000
