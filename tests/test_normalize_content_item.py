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
