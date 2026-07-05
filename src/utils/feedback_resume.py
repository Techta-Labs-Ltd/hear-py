from __future__ import annotations

from src.services.persistence import get_store
from src.utils.audio import build_play_directive, resolve_audio_url_for_speed, resolve_effective_playback_speed
from src.utils.content_playback import has_queued_tracks, queue_parent_for_token_fallback
from src.utils.speech import ssml, RESUMING, NOTHING_TO_RESUME, WELCOME_REPROMPT


def url_at_store_speed(store: dict, audio_url: str | None, track_speed_variants=None) -> str | None:
    """Resolve an audio URL at the speed stored in the session."""
    variants = track_speed_variants if track_speed_variants else store.get("currentPlaybackSpeeds")
    effective_speed = resolve_effective_playback_speed(store.get("playbackSpeed") or 1.0, variants)
    return resolve_audio_url_for_speed(audio_url, effective_speed, variants)


async def resume_current_track(handler_input, *, ack_speech: str | None = None) -> dict:
    """Build a response that resumes the most recently playing track."""
    store = get_store(handler_input)
    if not store.get("lastToken"):
        return handler_input.response_builder \
            .speak(WELCOME_REPROMPT) \
            .reprompt(WELCOME_REPROMPT) \
            .get_response()

    audio_url = None
    metadata: dict = {}
    token = store["lastToken"]
    duration_secs = store.get("currentDurationSecs")

    if has_queued_tracks(store):
        tracks = store.get("currentTracks") or []
        track = tracks[store.get("currentTrackIndex") or 0] if (store.get("currentTrackIndex") or 0) < len(tracks) else None
        if track and track.get("audioUrl"):
            audio_url = track["audioUrl"]
            token = track.get("id") or f"{queue_parent_for_token_fallback(store)}:{store.get('currentTrackIndex')}"
            metadata = {"title": track.get("title") or "Hear", "subtitle": store.get("feedbackContentTitle") or ""}
            duration_secs = track.get("durationSecs") if "durationSecs" in track else duration_secs

    if not audio_url:
        resolved = await _resolve_resume_playback(store)
        if not resolved or not resolved.get("audioUrl"):
            return handler_input.response_builder \
                .speak(ssml(NOTHING_TO_RESUME)) \
                .reprompt(WELCOME_REPROMPT) \
                .get_response()
        audio_url = resolved["audioUrl"]
        token = resolved["token"]
        metadata = resolved.get("metadata") or {}

    tracks = store.get("currentTracks") or []
    track = tracks[store.get("currentTrackIndex") or 0] if (store.get("currentTrackIndex") or 0) < len(tracks) and has_queued_tracks(store) else None
    play_url = url_at_store_speed(store, audio_url, track.get("playback_speed") if track else None)
    offset_ms = store.get("lastOffsetMs") or 0
    spoken = f"{ack_speech} {RESUMING}" if ack_speech else RESUMING

    return handler_input.response_builder \
        .speak(ssml(spoken)) \
        .add_directive(build_play_directive(
            url=play_url, token=token, offset_ms=offset_ms, metadata=metadata,
            progress_report=True, duration_secs=duration_secs, handler_input=handler_input,
        )) \
        .with_should_end_session(True) \
        .get_response()


async def _resolve_resume_playback(store: dict) -> dict | None:
    """Resolve the last-played content item from locally stored data."""
    audio_url = store.get("lastAudioUrl")
    token = store.get("lastToken")
    if audio_url and token:
        return {
            "audioUrl": audio_url,
            "token": token,
            "metadata": {"title": store.get("currentContentTitle") or store.get("feedbackContentTitle") or "Hear", "subtitle": store.get("feedbackContentTitle") or ""},
        }
    return None
