from __future__ import annotations


def get_publication_track_total(store: dict) -> int:
    if not store:
        return 0
    tracks = store.get("currentTracks") or []
    if isinstance(store.get("currentTotalTracks"), (int, float)) and store["currentTotalTracks"] > 0:
        return max(int(store["currentTotalTracks"]), len(tracks))
    return len(tracks)


def has_active_publication(store: dict) -> bool:
    """Check whether a multi-track publication is currently active."""
    if not store:
        return False
    parent = store.get("playbackParentId") or store.get("currentPublicationId")
    return bool(parent and get_publication_track_total(store) > 0)


def has_more_publication_tracks(store: dict) -> bool:
    """Check whether there are more tracks remaining in the active publication."""
    if not has_active_publication(store):
        return False
    total = get_publication_track_total(store)
    idx = store.get("currentTrackIndex") or 0
    return idx + 1 < total


def slim_publication_track(track) -> dict | None:
    """Create a slimmed-down version of a publication track for storage."""
    if not isinstance(track, dict):
        return track
    return {
        "id": track.get("id"),
        "title": track.get("title"),
        "audioUrl": track.get("audioUrl"),
        "category": track.get("category"),
        "playback_speed": track.get("playback_speed"),
        "durationSecs": track.get("durationSecs"),
    }


async def resolve_publication_track_at_index(handler_input, store: dict, track_index: int) -> dict | None:
    """Resolve a publication track at the given index from locally stored data."""
    total = get_publication_track_total(store)
    if track_index < 0 or track_index >= total:
        return None
    tracks = store.get("currentTracks") or []
    track = tracks[track_index] if track_index < len(tracks) else None
    if track and track.get("audioUrl"):
        return {"track": track, "tracks": tracks, "total": total}
    return None
