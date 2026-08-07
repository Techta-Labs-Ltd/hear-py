from src.services.browse import set_browse_catalog
from src.services.following import add_followed_creator, is_following
from src.services.persistence import merge_initial_store
from src.services.playback import add_to_history
from src.services.queue import recent_content_ids, clear_queue, init_queue
from src.services.store import DEFAULT_STORE, get_store, update_store



class TestPersistence:
    def test_default_store_has_key_fields(self):
        assert "lastToken" in DEFAULT_STORE
        assert "locality" in DEFAULT_STORE
        assert "playbackSpeed" in DEFAULT_STORE
        assert "playbackQueue" in DEFAULT_STORE
        assert "activePlayback" in DEFAULT_STORE
        assert "followedCreators" in DEFAULT_STORE

    def test_merge_initial_store_preserves_defaults(self):
        merged = merge_initial_store({})
        assert merged["playbackSpeed"] == 1.0
        assert merged["playbackQueue"] is None

    def test_merge_initial_store_overrides(self):
        merged = merge_initial_store({"playbackSpeed": 2.0, "userCity": "London"})
        assert merged["playbackSpeed"] == 2.0
        assert merged["userCity"] == "London"

    def test_get_store_returns_copy(self, mock_handler_input):
        mock_handler_input.attributes_manager.request_attributes["_store"] = {"playCount": 5}
        store = get_store(mock_handler_input)
        assert store["playCount"] == 5
        store["playCount"] = 10
        store2 = get_store(mock_handler_input)
        assert store2["playCount"] == 5

    def test_update_store_mutates_and_marks_dirty(self, mock_handler_input):
        mock_handler_input.attributes_manager.request_attributes["_store"] = dict(DEFAULT_STORE)
        updated = update_store(mock_handler_input, {"playCount": 1})
        assert updated["playCount"] == 1
        assert mock_handler_input.attributes_manager.request_attributes["_dirty"] is True

    def test_add_to_history(self, mock_handler_input):
        mock_handler_input.attributes_manager.request_attributes["_store"] = dict(DEFAULT_STORE)
        store = add_to_history(mock_handler_input, "content_001")
        assert any(h["id"] == "content_001" for h in store["playHistory"])

    def test_add_followed_creator(self, mock_handler_input):
        mock_handler_input.attributes_manager.request_attributes["_store"] = dict(DEFAULT_STORE)
        store = add_followed_creator(mock_handler_input, "creator_1", "Test Creator")
        assert is_following(store, "creator_1")

    def test_recent_content_ids(self, mock_handler_input):
        store = dict(DEFAULT_STORE)
        store["currentContentId"] = "content_001"
        store["feedbackContentId"] = "content_002"
        ids = recent_content_ids(store)
        assert "content_001" in ids
        assert "content_002" in ids

    def test_clear_queue(self, mock_handler_input):
        mock_handler_input.attributes_manager.request_attributes["_store"] = dict(DEFAULT_STORE)
        store = init_queue(mock_handler_input, [{"contentId": "1"}, {"contentId": "2"}])
        assert store["playbackQueue"]["orderedContentIds"] == ["1", "2"]
        store = clear_queue(mock_handler_input)
        assert store["playbackQueue"] is None

    def test_publication_queue_preserves_parent_and_track_metadata(self, mock_handler_input):
        mock_handler_input.attributes_manager.request_attributes["_store"] = dict(DEFAULT_STORE)
        tracks = [{
            "contentId": "track-1",
            "publicationId": "publication-1",
            "publicationTitle": "Weekly publication",
            "isPublication": True,
            "trackIndex": 0,
            "trackCount": 2,
            "audioUrl": "https://cdn.hear.media/track-1.mp3",
        }, {
            "contentId": "track-2",
            "publicationId": "publication-1",
            "publicationTitle": "Weekly publication",
            "isPublication": True,
            "trackIndex": 1,
            "trackCount": 2,
            "audioUrl": "https://cdn.hear.media/track-2.mp3",
        }]

        store = init_queue(mock_handler_input, tracks)
        assert store["playbackQueue"]["orderedContentIds"] == ["track-1", "track-2"]
        assert store["playbackQueue"]["publicationId"] == "publication-1"
        assert store["playbackQueue"]["publicationTitle"] == "Weekly publication"

        store = set_browse_catalog(mock_handler_input, {"items": tracks})
        cached = store["browseQueueItems"][1]
        assert cached["publicationId"] == "publication-1"
        assert cached["trackIndex"] == 1
        assert cached["trackCount"] == 2

    def test_browse_queue_cache_preserves_canonical_playback_fields(self, mock_handler_input):
        mock_handler_input.attributes_manager.request_attributes["_store"] = dict(DEFAULT_STORE)
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

        store = set_browse_catalog(mock_handler_input, {"items": [content]})

        cached = store["browseQueueItems"][0]
        assert cached["contentId"] == "content-2"
        assert cached["audioUrl"] == content["audioUrl"]
        assert cached["durationMs"] == 180000
