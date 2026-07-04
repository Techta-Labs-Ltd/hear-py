from __future__ import annotations
from src.utils.publication_tracks import get_publication_track_total


def get_normalized_type(item: dict) -> str:
    """Normalize the content type to one of single/group/publication."""
    if not isinstance(item, dict):
        return "single"
    t = str(item.get("type") or "").lower()
    if t in ("single", "group", "publication"):
        return t
    return "single"


def _get_playback_parent_id(item: dict) -> str | None:
    if not isinstance(item, dict):
        return None
    return item.get("id") or None


def is_multi_track_item(item: dict) -> bool:
    """Check whether a content item has multiple tracks."""
    t = get_normalized_type(item)
    if t not in ("group", "publication"):
        return False
    return isinstance(item.get("tracks"), list) and len(item["tracks"]) > 0


def _get_collection_display_title(item: dict) -> str:
    if not isinstance(item, dict):
        return ""
    return item.get("title") or ""


def _effective_category_for_track(item: dict, track: dict | None) -> str | None:
    """Determine the effective category for a track."""
    if track and track.get("category"):
        return track["category"]
    if item.get("category"):
        return item["category"]
    cats = item.get("categories")
    if isinstance(cats, list) and cats:
        return cats[0]
    return None


def resolve_playback_at_track_index(item: dict, track_index: int = 0) -> dict | None:
    """Resolve playback details for a specific track index within a content item."""
    if not isinstance(item, dict):
        return None
    content_type = get_normalized_type(item)
    if is_multi_track_item(item):
        tracks = item["tracks"]
        idx_raw = track_index if isinstance(track_index, int) and track_index == track_index else int(track_index)
        idx = max(0, min(idx_raw, len(tracks) - 1))
        track = tracks[idx]
        parent_id = _get_playback_parent_id(item)
        token = track.get("id") or f"{parent_id}:{idx}"
        track_id = track.get("id") or token
        return {
            "audioUrl": track.get("audioUrl"),
            "token": token,
            "trackTitle": track.get("title") or None,
            "trackId": track_id,
            "totalTracks": len(tracks),
            "trackIndex": idx,
            "effectiveCategory": _effective_category_for_track(item, track),
            "playbackParentId": parent_id,
            "isMultiTrack": True,
            "contentType": content_type,
            "collectionTitle": _get_collection_display_title(item),
        }
    parent_id = _get_playback_parent_id(item)
    tid = item.get("id")
    token = tid or parent_id or ""
    return {
        "audioUrl": item.get("audioUrl"),
        "token": token,
        "trackTitle": None,
        "trackId": tid or None,
        "totalTracks": 1,
        "trackIndex": 0,
        "effectiveCategory": _effective_category_for_track(item, None),
        "playbackParentId": parent_id,
        "isMultiTrack": False,
        "contentType": content_type,
        "collectionTitle": item.get("title") or "",
    }


def has_queued_tracks(store: dict) -> bool:
    """Check whether there are queued tracks from a multi-track publication."""
    if not store:
        return False
    parent = store.get("playbackParentId") or store.get("currentPublicationId")
    if not parent:
        return False
    return get_publication_track_total(store) > 0


def is_finished_token_last_in_session(store: dict, finished_token: str) -> bool:
    """Check whether a finished token is the last track in a multi-track session."""
    if not finished_token or not isinstance(finished_token, str):
        return True
    if not has_queued_tracks(store):
        return True
    tracks = store.get("currentTracks") or []
    total = get_publication_track_total(store)
    parent = store.get("playbackParentId") or store.get("currentPublicationId")
    for i, t in enumerate(tracks):
        synthesized = f"{parent}:{i}" if parent is not None else str(i)
        tid = t.get("id") or synthesized
        if finished_token in (t.get("id"), tid):
            return i >= total - 1
    idx = store.get("currentTrackIndex") or 0
    return idx >= total - 1


def queue_parent_for_token_fallback(store: dict) -> str | None:
    """Get the parent ID for token fallback when queuing content."""
    if not store:
        return None
    return store.get("playbackParentId") or store.get("currentPublicationId") or None


def resolve_track_index_for_token(item: dict, token: str) -> int:
    """Resolve the track index for a given token within a multi-track item."""
    if not item or not token or not is_multi_track_item(item):
        return 0
    parent_id = _get_playback_parent_id(item)
    tracks = item["tracks"]
    for i, t in enumerate(tracks):
        synthesized = f"{parent_id}:{i}"
        if t.get("id") == token or synthesized == token:
            return i
    return 0
