from unittest.mock import AsyncMock

import pytest

from src.constants.state import StateSchema
from src.container import ApplicationContainer
from src.middleware.persistence import SavePersistenceInterceptor
from src.models.browse import Browse
from src.models.playback import Playback
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
            {"playCount": 2, "userCity": "London", "_persistenceVersion": 7},
        )
        User.update(mock_handler_input, {"playCount": 3, "_requiresReliableSave": True})
        attrs = mock_handler_input.attributes_manager.request_attributes
        assert attrs["_persistenceVersion"] == 7
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
        store = Playback.add_to_history(mock_handler_input, "content_001")
        assert any((h["id"] == "content_001" for h in store["playHistory"]))

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
