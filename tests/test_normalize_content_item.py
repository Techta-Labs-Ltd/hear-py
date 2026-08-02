from __future__ import annotations

from src.utils.normalize_content_item import normalize_content_items


def test_normalizes_current_alexa_search_contract():
    content_id = "12380e9d-b1df-4dc1-b842-032b7a4f7b22"
    raw = {
        "contentId": content_id,
        "title": "0002_Good_Morning",
        "shortDescription": (
            "Monthly roundup of extra features from the Shetland Times newspaper."
        ),
        "creator": {
            "id": "creator-1",
            "name": "Shetland Life",
        },
        "organization": {
            "id": "organization-1",
            "name": "Shetland Life",
        },
        "category": {
            "slug": "monthly-update",
            "name": "Monthly Update",
        },
        "audioUrl": f"https://cdn.hear.media/audio/{content_id}.mp3",
        "durationSecs": 0,
        "playbackSpeed": [
            {
                "speed": 1,
                "audioUrl": f"https://cdn.hear.media/speed/{content_id}/x1_0.mp3",
                "audioFormat": "mp3",
            },
            {
                "speed": 1.5,
                "audioUrl": f"https://cdn.hear.media/speed/{content_id}/x1_5.mp3",
                "audioFormat": "mp3",
            },
        ],
        "publishedAt": 1785303950,
    }

    items = normalize_content_items([raw])

    assert len(items) == 1
    item = items[0]
    assert item["contentId"] == content_id
    assert item["creator"] == "Shetland Life"
    assert item["creatorId"] == "creator-1"
    assert item["spokenTitle"] == raw["shortDescription"]
    assert item["category"]["slug"] == "monthly-update"
    assert item["playbackSpeeds"] == raw["playbackSpeed"]
    assert item["audioUrl"] == raw["audioUrl"]
    assert item["durationMs"] is None
    assert item["publishedAt"] == 1785303950


def test_content_id_without_audio_is_still_rejected():
    assert normalize_content_items([{"contentId": "content-1"}]) == []


def test_publication_tracks_are_flattened_with_parent_metadata():
    raw = {
        "contentId": "publication-1",
        "publicationId": "publication-1",
        "type": "publication",
        "isPublication": True,
        "title": "Weekly publication",
        "creator": {"id": "creator-1", "name": "Reader One"},
        "organization": {"id": "org-1", "name": "York Talking News"},
        "tracks": [
            {
                "contentId": "track-1",
                "title": "First track",
                "audioUrl": "https://cdn.hear.media/track-1.mp3",
                "durationSecs": 120,
                "playbackSpeed": [{"speed": 1.5, "audioUrl": "https://cdn.hear.media/track-1-15.mp3"}],
            },
            {
                "contentId": "track-2",
                "title": "Second track",
                "audioUrl": "https://cdn.hear.media/track-2.mp3",
            },
        ],
        "trackCount": 2,
        "durationSecs": 1200,
        "publishedAt": 1785691920,
    }

    items = normalize_content_items([raw])

    assert [item["contentId"] for item in items] == ["track-1", "track-2"]
    assert all(item["publicationId"] == "publication-1" for item in items)
    assert all(item["publicationTitle"] == "Weekly publication" for item in items)
    assert all(item["creatorId"] == "creator-1" for item in items)
    assert all(item["organizationId"] == "org-1" for item in items)
    assert all(item["isPublication"] is True for item in items)
    assert [item["trackIndex"] for item in items] == [0, 1]
    assert all(item["trackCount"] == 2 for item in items)
    assert items[0]["durationMs"] == 120000
    assert items[1]["durationMs"] is None
    assert items[0]["playbackSpeeds"] == raw["tracks"][0]["playbackSpeed"]
    assert all(item["publishedAt"] == 1785691920 for item in items)

    renormalized = normalize_content_items(items)
    assert renormalized[0]["creatorName"] == "Reader One"
    assert renormalized[0]["organizationName"] == "York Talking News"
    assert renormalized[0]["publicationId"] == "publication-1"
