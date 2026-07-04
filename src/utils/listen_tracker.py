from __future__ import annotations

import time
import uuid

from config import settings
from src.services.persistence import get_store, update_store
from src.services.api import record_playback_events
from src.utils.search_filters import build_user_field
from src.utils.playback_timing import resolve_finished_event_timing
from src.services.listener_config import is_listener_api_enabled
from src.webhooks.dispatch import dispatch

PLAYBACK_EVENT_TYPES = {
    "STARTED": "AUDIO_PLAYER_PLAYBACK_STARTED",
    "STOPPED": "AUDIO_PLAYER_PLAYBACK_STOPPED",
    "FINISHED": "AUDIO_PLAYER_PLAYBACK_FINISHED",
    "NEARLY_FINISHED": "AUDIO_PLAYER_PLAYBACK_NEARLY_FINISHED",
}

FEEDBACK_TOKEN_PREFIX = "FEEDBACK_PROMPT:"


def is_feedback_token(token: str | None) -> bool:
    """Check whether a token represents a feedback prompt rather than real content."""
    return isinstance(token, str) and token.startswith(FEEDBACK_TOKEN_PREFIX)


def content_id_from_feedback_token(token: str) -> str:
    """Extract the content ID from a feedback token."""
    return str(token).replace(FEEDBACK_TOKEN_PREFIX, "")


def _make_session_id(track_id: str) -> str:
    """Generate a unique session ID for a track."""
    return f"{track_id}-{int(time.time() * 1000)}"


def _accumulate_segment_ms(session: dict | None, offset_ms: int) -> int:
    """Compute accumulated listen time for the current segment."""
    if not session:
        return 0
    delta = max(0, offset_ms - (session.get("segmentStartOffsetMs") or 0))
    return (session.get("accumulatedMs") or 0) + delta


def completion_pct(listened_ms, duration_secs) -> int | None:
    """Calculate the completion percentage of a track."""
    if not duration_secs or duration_secs <= 0:
        return None
    return min(100, round((listened_ms / (duration_secs * 1000)) * 100))


def resolve_listen_context(store: dict, overrides: dict | None = None) -> dict | None:
    """Resolve the current listen context from session store."""
    if not isinstance(store, dict):
        return None
    overrides = overrides or {}
    parent_id = store.get("playbackParentId") or store.get("currentPublicationId") or None
    track_id = (
        overrides.get("trackId") or
        store.get("playbackTrackId") or
        store.get("lastToken") or
        store.get("feedbackContentId") or None
    )
    content_id = overrides.get("contentId") or parent_id or track_id
    if not content_id and not track_id:
        return None
    return {
        "contentId": content_id,
        "trackId": track_id,
        "parentId": parent_id,
        "category": store.get("currentCategory") or store.get("feedbackCategory") or None,
        "creatorId": store.get("currentCreatorId") or store.get("feedbackCreatorId") or None,
        "title": store.get("currentContentTitle") or store.get("feedbackContentTitle") or None,
        "durationSecs": overrides.get("durationSecs") if "durationSecs" in overrides else (store.get("currentDurationSecs") if store.get("currentDurationSecs") is not None else None),
        "sourceIntent": store.get("queueSource") or store.get("pendingDiscoveryIntent") or None,
    }


def normalize_recent_track_listens(lst) -> list:
    """Normalize and cap the recent track listens list."""
    if not isinstance(lst, list):
        return []
    cap = settings.HEAR_MAX_TRACK_LISTEN_LOG or settings.max_history
    return [e for e in lst if isinstance(e, dict) and e.get("trackId")][:cap]


def build_playback_event(session: dict, event_type: str, *, position_ms: int = 0, timestamp_ms: int | None = None) -> dict:
    """Build a playback event payload for the listener API."""
    ts = round(timestamp_ms) if timestamp_ms is not None else int(time.time() * 1000)
    track_duration_ms = round(session["durationSecs"] * 1000) if session.get("durationSecs") else 0
    return {
        "trackId": str(session["trackId"]),
        "sessionId": str(session.get("sessionId") or session["trackId"]),
        "eventType": event_type,
        "positionMs": max(0, round(position_ms)),
        "trackDurationMs": track_duration_ms,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts / 1000)) + f".{ts % 1000:03d}Z",
        "timestampMs": ts,
        "clientEventId": str(uuid.uuid4()),
    }


def begin_listen_segment(handler_input, *, token: str | None = None, offset_ms: int = 0, ctx: dict | None = None) -> dict | None:
    """Begin a new listen tracking segment for the current content."""
    if token and is_feedback_token(token):
        return None
    store = get_store(handler_input)
    session_ctx = ctx or resolve_listen_context(store, {"trackId": token} if token else {})
    if not session_ctx or not session_ctx.get("trackId"):
        return None
    active = store.get("activeListenSession")
    if active and active["trackId"] != session_ctx["trackId"]:
        finalize_previous_track_if_any(handler_input, offset_ms=store.get("lastOffsetMs") or 0, reason="track_change")
    same_track_resume = active and active["trackId"] == session_ctx["trackId"]
    session_id = _make_session_id(session_ctx["trackId"])
    accumulated_ms = 0
    started_at = int(time.time() * 1000)
    if same_track_resume:
        accumulated_ms = active.get("accumulatedMs") or 0
        started_at = active.get("startedAt") or started_at
        ps = store.get("playbackSession")
        if ps and ps.get("sessionId") and ps.get("trackId") == session_ctx["trackId"]:
            session_id = ps["sessionId"]
        elif active.get("sessionId"):
            session_id = active["sessionId"]
    session = {
        **session_ctx,
        "sessionId": session_id,
        "segmentStartOffsetMs": offset_ms,
        "accumulatedMs": accumulated_ms,
        "startedAt": started_at,
    }
    update_store(handler_input, {"activeListenSession": session})
    return session


def close_listen_segment(handler_input, *, offset_ms: int = 0) -> int | None:
    """Close the current listen segment and return accumulated ms."""
    store = get_store(handler_input)
    session = store.get("activeListenSession")
    if not session:
        return None
    accumulated = _accumulate_segment_ms(session, offset_ms)
    update_store(handler_input, {
        "activeListenSession": {
            **session,
            "accumulatedMs": accumulated,
            "segmentStartOffsetMs": offset_ms,
        },
    })
    return accumulated


def _session_token_matches(session: dict, token: str | None, store: dict) -> bool:
    if not session.get("trackId"):
        return False
    if not token:
        return True
    if session["trackId"] == token:
        return True
    alt = store.get("playbackTrackId") or store.get("lastToken") or store.get("feedbackContentId")
    return session["trackId"] == alt or token == alt


def _resolve_listen_duration_ms(session: dict, offset_ms: int, store: dict, reason: str) -> int:
    """Determine the total listen duration for a completed segment."""
    listened_ms = _accumulate_segment_ms(session, offset_ms)
    if reason in ("finished", "track_advance"):
        min_ms = settings.HEAR_MIN_TRACK_RECORD_MS or 3000
        duration_ms = round(session["durationSecs"] * 1000) if session.get("durationSecs") else (
            round(store.get("currentDurationSecs") * 1000) if store.get("currentDurationSecs") else 0
        )
        fallback_ms = max(
            max(0, round(offset_ms or 0)),
            store.get("lastOffsetMs") or 0,
            store.get("playbackDurationEstimateMs") or 0,
            duration_ms,
            _estimate_wall_clock_listen_ms(session),
            _estimate_wall_clock_from_store(store, session.get("trackId")),
        )
        if listened_ms <= 0:
            listened_ms = fallback_ms
        elif listened_ms < min_ms and fallback_ms > listened_ms:
            listened_ms = fallback_ms
    return listened_ms


def build_synthetic_playback_state(store: dict, token: str | None) -> dict | None:
    """Build a synthetic playback state from available store fields."""
    track_id = store.get("playbackTrackId") or token or store.get("lastToken") or store.get("feedbackContentId")
    if not track_id:
        return None
    ps = store.get("playbackSession")
    als = store.get("activeListenSession")
    duration_ms = (ps.get("trackDurationMs") if ps and ps.get("trackDurationMs", 0) > 0 else 0) or (
        round(store.get("currentDurationSecs") * 1000) if store.get("currentDurationSecs") else 0
    ) or store.get("playbackDurationEstimateMs") or 0
    return {
        "token": token or track_id,
        "trackId": (ps.get("trackId") if ps else None) or (als.get("trackId") if als else None) or track_id,
        "sessionId": (ps.get("sessionId") if ps else None) or (als.get("sessionId") if als else None) or f"{track_id}-finished",
        "lastKnownOffsetMs": max(
            (ps.get("lastKnownOffsetMs") if ps else 0) or 0,
            store.get("lastOffsetMs") or 0,
            (als.get("accumulatedMs") if als else 0) or 0,
        ),
        "wallStart": (ps.get("wallStart") if ps else None) or (als.get("startedAt") if als else None) or None,
        "startOffsetMs": (ps.get("startOffsetMs") if ps else None) or (als.get("segmentStartOffsetMs") if als else None) or 0,
        "trackDurationMs": duration_ms,
    }


def _append_recent_listen_entry(handler_input, entry: dict) -> bool:
    """Append a completed listen entry to the recent track listens log."""
    if not entry.get("trackId"):
        return False
    min_record = settings.HEAR_MIN_TRACK_RECORD_MS or 3000
    if (entry.get("listenedMs") or 0) < min_record:
        return False
    store = get_store(handler_input)
    log = normalize_recent_track_listens([entry] + (store.get("recentTrackListens") or []))
    update_store(handler_input, {"recentTrackListens": log})
    return True


def snapshot_last_completed_listen(entry: dict) -> dict | None:
    """Create a snapshot of the last completed listen entry."""
    min_record = settings.HEAR_MIN_TRACK_RECORD_MS or 3000
    if not entry.get("trackId") or (entry.get("listenedMs") or 0) < min_record:
        return None
    return {
        "trackId": entry["trackId"],
        "contentId": entry.get("contentId") or entry["trackId"],
        "listenedMs": entry["listenedMs"],
        "durationSecs": entry.get("durationSecs") if entry.get("durationSecs") is not None else None,
        "completionPct": entry.get("completionPct") if "completionPct" in entry else completion_pct(entry["listenedMs"], entry.get("durationSecs")),
        "playedAt": entry.get("playedAt") or int(time.time() * 1000),
    }


def persist_last_completed_listen(handler_input, entry: dict) -> dict | None:
    """Persist the last completed listen snapshot to the session store."""
    snap = snapshot_last_completed_listen(entry)
    if not snap:
        return None
    update_store(handler_input, {"lastCompletedListen": snap})
    return snap


def matches_last_completed_listen(store: dict, token: str | None) -> bool:
    """Check whether a token matches the last completed listen."""
    last = store.get("lastCompletedListen") if store else None
    if not last or not last.get("trackId") or not token:
        return False
    return last["trackId"] == token or last.get("contentId") == token or store.get("playbackTrackId") == last["trackId"]


def build_fallback_finished_entry(handler_input, token: str | None, offset_ms: int) -> dict | None:
    """Build a finished listen entry from available store data when the event-driven path fails."""
    store = get_store(handler_input)
    track_id = store.get("playbackTrackId") or token or store.get("lastToken") or None
    if not track_id or is_feedback_token(track_id):
        return None
    listened_ms = max(0, round(offset_ms or 0), store.get("lastOffsetMs") or 0)
    session = store.get("playbackSession") or store.get("activeListenSession")
    if session:
        if isinstance(session, dict):
            lko = session.get("lastKnownOffsetMs") or 0
            if lko > 0:
                listened_ms = max(listened_ms, lko)
            am = session.get("accumulatedMs") or 0
            if am > 0:
                listened_ms = max(listened_ms, am)
    duration_secs = store.get("currentDurationSecs") or (
        round((session.get("trackDurationMs") / 1000)) if (session and session.get("trackDurationMs")) else None
    )
    if listened_ms <= 0 and duration_secs:
        listened_ms = round(duration_secs * 1000)
    if listened_ms <= 0 and (store.get("playbackDurationEstimateMs") or 0) > 0:
        listened_ms = store["playbackDurationEstimateMs"]
    if listened_ms <= 0:
        listened_ms = max(
            _estimate_wall_clock_listen_ms(session),
            _estimate_wall_clock_from_store(store, token),
        )
    if listened_ms <= 0:
        return None
    entry = {
        "contentId": store.get("currentContentId") or store.get("feedbackContentId") or track_id,
        "trackId": track_id,
        "parentId": store.get("playbackParentId") or store.get("currentPublicationId") or None,
        "sessionId": f"{track_id}-finished",
        "title": store.get("currentContentTitle") or store.get("feedbackContentTitle") or None,
        "category": store.get("currentCategory") or store.get("feedbackCategory") or None,
        "creatorId": store.get("currentCreatorId") or store.get("feedbackCreatorId") or None,
        "listenedMs": listened_ms,
        "durationSecs": duration_secs,
        "completionPct": completion_pct(listened_ms, duration_secs),
        "sourceIntent": store.get("queueSource") or store.get("pendingDiscoveryIntent") or None,
        "playedAt": int(time.time() * 1000),
        "feedback": None,
        "reason": "finished_fallback",
    }
    _append_recent_listen_entry(handler_input, entry)
    return entry


def record_force_finished_listen(handler_input, *, token=None, store=None, duration_secs=None, offset_ms: int = 0) -> dict | None:
    """Record a forcefully-finalized listen entry, estimating missing data."""
    min_record = settings.HEAR_MIN_TRACK_RECORD_MS or 3000
    s = store or get_store(handler_input) if handler_input else {}
    track_id = s.get("playbackTrackId") or token or s.get("lastToken")
    if not track_id or is_feedback_token(track_id):
        return None
    synthetic = build_synthetic_playback_state(s, token)
    timing = resolve_finished_event_timing(synthetic or {}, s, offset_ms)
    listened_ms = max(0, round(timing.get("positionMs") or 0))
    resolved_duration_secs = duration_secs or s.get("currentDurationSecs") or (
        round(timing["trackDurationMs"] / 1000) if timing.get("trackDurationMs", 0) > 0 else None
    )
    if listened_ms < min_record and resolved_duration_secs:
        listened_ms = round(resolved_duration_secs * 1000)
    if listened_ms < min_record:
        listened_ms = max(
            s.get("lastOffsetMs") or 0,
            s.get("playbackDurationEstimateMs") or 0,
            _estimate_wall_clock_listen_ms(s.get("activeListenSession") or s.get("playbackSession") or synthetic),
            _estimate_wall_clock_from_store(s, token),
        )
    if listened_ms < min_record:
        return None
    entry = {
        "contentId": s.get("currentContentId") or s.get("feedbackContentId") or track_id,
        "trackId": track_id,
        "parentId": s.get("playbackParentId") or s.get("currentPublicationId") or None,
        "sessionId": (synthetic or {}).get("sessionId") or f"{track_id}-finished",
        "title": s.get("currentContentTitle") or s.get("feedbackContentTitle") or None,
        "category": s.get("currentCategory") or s.get("feedbackCategory") or None,
        "creatorId": s.get("currentCreatorId") or s.get("feedbackCreatorId") or None,
        "listenedMs": listened_ms,
        "durationSecs": resolved_duration_secs,
        "completionPct": completion_pct(listened_ms, resolved_duration_secs),
        "sourceIntent": s.get("queueSource") or s.get("pendingDiscoveryIntent") or None,
        "playedAt": int(time.time() * 1000),
        "feedback": None,
        "reason": "finished_force",
    }
    _append_recent_listen_entry(handler_input, entry)
    return entry


def _estimate_wall_clock_listen_ms(session) -> int:
    """Estimate listen duration from wall clock timestamps."""
    if not isinstance(session, dict):
        return 0
    now = int(time.time() * 1000)
    if session.get("wallStart"):
        return max(0, round((session.get("startOffsetMs") or 0) + (now - session["wallStart"])))
    if session.get("startedAt"):
        return max(0, round(now - session["startedAt"]))
    return 0


def _estimate_wall_clock_from_store(store: dict, token: str | None) -> int:
    """Estimate listen duration from store-level play-started timestamps."""
    if not store or not store.get("lastPlayStartedAt"):
        return 0
    track_id = store.get("playbackTrackId") or token or store.get("lastToken")
    if not track_id or store.get("lastPlayTrackId") != track_id:
        return 0
    return max(0, round(int(time.time() * 1000) - store["lastPlayStartedAt"]))


def record_finished_listen_from_timing(handler_input, *, token=None, track_id=None, session_id=None, position_ms: int = 0, track_duration_ms: int = 0, store=None) -> dict | None:
    """Record a finished listen entry using explicit timing data."""
    min_record = settings.HEAR_MIN_TRACK_RECORD_MS or 3000
    s = store or get_store(handler_input)
    session = s.get("playbackSession") or s.get("activeListenSession")
    listened_ms = max(0, round(position_ms or 0))
    duration_secs = (track_duration_ms / 1000) if track_duration_ms > 0 else (
        s.get("currentDurationSecs") or (
            round((session.get("trackDurationMs") / 1000)) if (session and session.get("trackDurationMs")) else None
        )
    )
    if listened_ms < min_record and duration_secs:
        listened_ms = round(duration_secs * 1000)
    if listened_ms < min_record:
        listened_ms = _estimate_wall_clock_listen_ms(session)
    if listened_ms < min_record:
        return None
    resolved_track_id = track_id or s.get("playbackTrackId") or token or s.get("lastToken")
    if not resolved_track_id or is_feedback_token(resolved_track_id):
        return None
    entry = {
        "contentId": s.get("currentContentId") or s.get("feedbackContentId") or resolved_track_id,
        "trackId": resolved_track_id,
        "parentId": s.get("playbackParentId") or s.get("currentPublicationId") or None,
        "sessionId": session_id or f"{resolved_track_id}-finished",
        "title": s.get("currentContentTitle") or s.get("feedbackContentTitle") or None,
        "category": s.get("currentCategory") or s.get("feedbackCategory") or None,
        "creatorId": s.get("currentCreatorId") or s.get("feedbackCreatorId") or None,
        "listenedMs": listened_ms,
        "durationSecs": duration_secs,
        "completionPct": completion_pct(listened_ms, duration_secs),
        "sourceIntent": s.get("queueSource") or s.get("pendingDiscoveryIntent") or None,
        "playedAt": int(time.time() * 1000),
        "feedback": None,
        "reason": "finished_event",
    }
    _append_recent_listen_entry(handler_input, entry)
    return entry


def finalize_listen_segment(handler_input, *, offset_ms: int = 0, reason: str = "finished", token: str | None = None) -> dict | None:
    """Finalize the active listen segment, computing total listen duration."""
    store = get_store(handler_input)
    session = store.get("activeListenSession")
    if not session:
        return None
    if token and not _session_token_matches(session, token, store) and reason in ("finished", "track_advance"):
        return None
    listened_ms = _resolve_listen_duration_ms(session, offset_ms, store, reason)
    update_store(handler_input, {"activeListenSession": None})
    min_record = settings.HEAR_MIN_TRACK_RECORD_MS or 3000
    is_terminal = reason in ("finished", "track_advance")
    if listened_ms < min_record and not is_terminal:
        return None
    entry = {
        "contentId": session.get("contentId"),
        "trackId": session["trackId"],
        "parentId": session.get("parentId") or None,
        "sessionId": session.get("sessionId") or None,
        "title": session.get("title") or None,
        "category": session.get("category") or None,
        "creatorId": session.get("creatorId") or None,
        "listenedMs": listened_ms,
        "durationSecs": session.get("durationSecs") if "durationSecs" in session else None,
        "completionPct": completion_pct(listened_ms, session.get("durationSecs")),
        "sourceIntent": session.get("sourceIntent") or None,
        "playedAt": int(time.time() * 1000),
        "feedback": None,
        "reason": reason,
    }
    if listened_ms >= min_record:
        log = normalize_recent_track_listens([entry] + (store.get("recentTrackListens") or []))
        update_store(handler_input, {"recentTrackListens": log})
    return entry


def _find_listen_entry_for_feedback(store: dict, track_id: str | None = None) -> dict | None:
    """Find the listen entry to attach feedback to."""
    tid = track_id or store.get("feedbackContentId") or store.get("lastToken")
    if not tid:
        return None
    active = store.get("activeListenSession")
    if active and active.get("trackId") == tid:
        listened_ms = _accumulate_segment_ms(active, store.get("lastOffsetMs") or 0)
        return {
            "contentId": active.get("contentId"),
            "trackId": active["trackId"],
            "listenedMs": listened_ms,
            "durationSecs": active.get("durationSecs") if "durationSecs" in active else None,
            "completionPct": completion_pct(listened_ms, active.get("durationSecs")),
            "playedAt": active.get("startedAt") or int(time.time() * 1000),
        }
    recent = next((r for r in (store.get("recentTrackListens") or []) if isinstance(r, dict) and r.get("trackId") == tid), None)
    if recent:
        return {
            "contentId": recent.get("contentId"),
            "trackId": recent["trackId"],
            "listenedMs": recent["listenedMs"],
            "durationSecs": recent.get("durationSecs") if "durationSecs" in recent else None,
            "completionPct": recent.get("completionPct") if "completionPct" in recent else None,
            "playedAt": recent.get("playedAt") or int(time.time() * 1000),
        }
    return None


def get_listen_stats_for_feedback(store: dict) -> dict | None:
    """Get listen statistics to accompany a feedback submission."""
    return _find_listen_entry_for_feedback(store)


def attach_feedback_to_last_listen(handler_input, *, track_id=None, feedback=None):
    """Attach feedback data to the most recent listen entry."""
    store = get_store(handler_input)
    tid = track_id or store.get("feedbackContentId") or store.get("lastToken")
    if not tid or feedback is None:
        return None
    active = store.get("activeListenSession")
    if active and active.get("trackId") == tid:
        return update_store(handler_input, {"activeListenSession": {**active, "pendingFeedback": feedback}})
    log = [
        {**entry, "feedback": feedback} if isinstance(entry, dict) and entry.get("trackId") == tid else entry
        for entry in (store.get("recentTrackListens") or [])
    ]
    return update_store(handler_input, {"recentTrackListens": log})


def _get_user_id(handler_input) -> str | None:
    try:
        return handler_input.request_envelope.context.System.user.userId or None
    except Exception:
        return None


def _get_device_id(handler_input) -> str | None:
    try:
        return handler_input.request_envelope.context.System.device.deviceId or None
    except Exception:
        return None


async def schedule_playback_event(handler_input, event_type: str, session: dict, *, position_ms: int = 0):
    """Schedule an async playback event dispatch to the listener API."""
    if not is_listener_api_enabled() or not session.get("trackId"):
        return
    user_id = _get_user_id(handler_input)
    if not user_id:
        return
    event = build_playback_event(session, event_type, position_ms=position_ms)
    try:
        store = get_store(handler_input)
        user = build_user_field(handler_input, store)
        await record_playback_events(user_id, [event], user=user)
    except Exception:
        pass


def schedule_playback_started(handler_input, session: dict):
    """Schedule a playback-started event."""
    return schedule_playback_event(handler_input, PLAYBACK_EVENT_TYPES["STARTED"], session, position_ms=(session.get("segmentStartOffsetMs") or 0))


def schedule_playback_stopped(handler_input, session: dict, offset_ms: int = 0):
    """Schedule a playback-stopped event."""
    return schedule_playback_event(handler_input, PLAYBACK_EVENT_TYPES["STOPPED"], session, position_ms=offset_ms)


def schedule_playback_nearly_finished(handler_input, session: dict, offset_ms: int = 0):
    """Schedule a playback-nearly-finished event."""
    return schedule_playback_event(handler_input, PLAYBACK_EVENT_TYPES["NEARLY_FINISHED"], session, position_ms=offset_ms)


async def schedule_playback_finished(handler_input, entry: dict):
    """Schedule a playback-finished event from a finalized listen entry."""
    if not entry.get("trackId"):
        return
    session = {"trackId": entry["trackId"], "sessionId": entry.get("sessionId") or entry["trackId"], "durationSecs": entry.get("durationSecs") if "durationSecs" in entry else None}
    await schedule_playback_event(handler_input, PLAYBACK_EVENT_TYPES["FINISHED"], session, position_ms=entry.get("listenedMs") or 0)


async def finalize_previous_track_if_any(handler_input, *, offset_ms=None, reason: str = "new_playback"):
    """Finalize and flush the previous track's listen segment."""
    store = get_store(handler_input)
    if not store.get("activeListenSession"):
        return None
    entry = finalize_listen_segment(handler_input, offset_ms=offset_ms if offset_ms is not None else (store.get("lastOffsetMs") or 0), reason=reason)
    if entry:
        return await schedule_playback_finished(handler_input, entry)
    return None


async def save_feedback_with_listen_context(handler_input, feedback_value):
    """Save feedback along with the associated listen context and dispatch webhook."""
    store = get_store(handler_input)
    user_id = _get_user_id(handler_input)
    if not user_id or not store.get("feedbackContentId"):
        return None
    stats = get_listen_stats_for_feedback(store)
    track_id = (stats or {}).get("trackId") or None
    if not track_id:
        return None
    attach_feedback_to_last_listen(handler_input, track_id=track_id, feedback=feedback_value)
    try:
        dispatch("user.feedback_given", {
            "userId": user_id,
            "listenerId": store.get("listenerId") or None,
            "trackId": track_id,
            "contentId": store["feedbackContentId"],
            "feedback": feedback_value,
            "listenedMs": (stats or {}).get("listenedMs") if stats else None,
            "completionPct": (stats or {}).get("completionPct") if stats else None,
            "playedAt": (stats or {}).get("playedAt") if stats else None,
            "timestamp": int(time.time() * 1000),
        })
    except Exception:
        pass
    return stats
