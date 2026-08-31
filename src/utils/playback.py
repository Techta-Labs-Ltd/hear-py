from __future__ import annotations

import re
import time

from config import settings
from src.utils.content import ContentIdentity


class PlaybackUtils:
    SPEED_ALIASES = {
        "first": 0.5,
        "first speed": 0.5,
        "half": 0.5,
        "half speed": 0.5,
        "second": 0.75,
        "second speed": 0.75,
        "three quarter speed": 0.75,
        "third": 1.0,
        "third speed": 1.0,
        "normal": 1.0,
        "normal speed": 1.0,
        "regular speed": 1.0,
        "reset speed": 1.0,
        "fourth": 1.25,
        "fourth speed": 1.25,
        "fifth": 1.5,
        "fifth speed": 1.5,
        "one and a half": 1.5,
        "sixth": 2.0,
        "sixth speed": 2.0,
        "double": 2.0,
        "double speed": 2.0,
    }

    @staticmethod
    def normalise_speed(requested) -> float | None:
        raw = str(requested).strip().casefold() if requested is not None else ""
        if raw in PlaybackUtils.SPEED_ALIASES:
            return PlaybackUtils.SPEED_ALIASES[raw]
        try:
            speed = float(raw.removesuffix("x").strip())
        except (TypeError, ValueError):
            return None
        return next((value for value in settings.speeds if abs(value - speed) < 0.001), None)

    @staticmethod
    def find_speed_url(speeds: list | None, target_speed: float) -> str | None:
        if not isinstance(speeds, list) or not speeds:
            return None
        matches = [(abs(entry["speed"] - target_speed), entry.get("audioUrl")) for entry in speeds]
        difference, url = min(matches, default=(float("inf"), None))
        return url if difference < 0.15 else None

    @staticmethod
    def get_next_speed(speeds: list | None, current_speed: float, direction: str) -> dict | None:
        if not isinstance(speeds, list) or not speeds:
            return None
        ordered = sorted(speeds, key=lambda entry: entry["speed"])
        candidates = (
            (entry for entry in ordered if entry["speed"] > current_speed + 0.01)
            if direction == "up"
            else (entry for entry in reversed(ordered) if entry["speed"] < current_speed - 0.01)
        )
        return next(candidates, None)

    @staticmethod
    def strip_speed_from_url(url: str | None) -> str | None:
        if not url or not isinstance(url, str):
            return url
        parameter = settings.HEAR_AUDIO_SPEED_PARAM or "speed"
        pattern = re.compile(f"([?&]){re.escape(parameter)}=[^&]*")
        cleaned = pattern.sub(lambda match: "?" if match.group(1) == "?" else "", url)
        return re.sub("\\?$", "", re.sub("\\?&", "?", cleaned))

    @staticmethod
    def resolve_effective_speed(speed, variants: list | None) -> float:
        numeric = float(speed) if speed is not None else None
        if numeric is None or numeric != numeric or numeric == settings.default_speed:
            return settings.default_speed
        if not isinstance(variants, list) or not variants:
            return settings.default_speed
        return (
            numeric if PlaybackUtils.find_speed_url(variants, numeric) else settings.default_speed
        )

    @staticmethod
    def resolve_audio_url(base_url: str | None, speed, variants: list | None) -> str | None:
        if not base_url or not isinstance(base_url, str):
            return base_url
        effective = PlaybackUtils.resolve_effective_speed(speed, variants)
        if effective == settings.default_speed:
            return PlaybackUtils.strip_speed_from_url(base_url)
        return PlaybackUtils.find_speed_url(
            variants, effective
        ) or PlaybackUtils.strip_speed_from_url(base_url)

    @staticmethod
    def parse_duration_ms(duration: str | None) -> int | None:
        match = re.match("PT(?:(\\d+)H)?(?:(\\d+)M)?(?:(\\d+)S)?", duration or "")
        if not match:
            return None
        hours, minutes, seconds = (int(value or 0) for value in match.groups())
        return (hours * 3600 + minutes * 60 + seconds) * 1000

    @staticmethod
    def hours(milliseconds) -> float:
        return round(max(0, int(milliseconds or 0)) / 3600000, 6)

    @staticmethod
    def playback_observation(
        state: dict,
        *,
        offset_ms: int,
        observed_at_ms: int,
        event_type: str,
        status: str,
    ) -> dict:
        current_offset = max(0, int(offset_ms or 0))
        previous_offset = max(
            0,
            int(
                state.get("observationOffsetMs")
                if state.get("observationOffsetMs") is not None
                else state.get("offsetMs")
                or 0
            ),
        )
        previous_timestamp = max(0, int(state.get("observationTimestampMs") or 0))
        offset_advance = max(0, current_offset - previous_offset)
        elapsed = max(0, int(observed_at_ms or 0) - previous_timestamp)
        countable = state.get("status") in {"starting", "playing"} and event_type != "started"
        if not countable or offset_advance <= 0:
            delta = 0
        elif previous_timestamp > 0 and elapsed > 0:
            delta = elapsed
        else:
            delta = offset_advance
        time_spent = max(0, int(state.get("timeSpentMs") or 0)) + delta
        return {
            "status": status,
            "offsetMs": current_offset,
            "listenedMs": max(int(state.get("listenedMs") or 0), current_offset),
            "timeSpentMs": time_spent,
            "timeSpentHours": PlaybackUtils.hours(time_spent),
            "lastListeningDeltaMs": delta,
            "observationOffsetMs": current_offset,
            "observationTimestampMs": max(0, int(observed_at_ms or 0)),
        }

    @staticmethod
    def read_playback_queue(store: dict) -> dict | None:
        queue = store.get("playbackQueue") if isinstance(store, dict) else None
        if not isinstance(queue, dict) or not isinstance(queue.get("orderedContentIds"), list):
            return None
        return queue

    @staticmethod
    def _timestamp_ms(value=None) -> int:
        if isinstance(value, (int, float)):
            return int(value)
        return int(time.time() * 1000)

    @staticmethod
    def build_playback_event(data: dict) -> dict:
        timestamp = PlaybackUtils._timestamp_ms(data.get("timestampMs"))
        duration = max(0, int(data.get("durationMs") or 0))
        listened = max(0, int(data.get("listenedMs") or 0))
        session_id = str(data["sessionId"])
        event_type = str(data["eventType"])
        publication_id = ContentIdentity.publication_id(data)
        content_id = ContentIdentity.content_id(data)
        subject_type = "publication" if publication_id else "content"
        subject_id = publication_id or content_id
        event = {
            "subjectType": subject_type,
            "subjectId": str(subject_id),
            "creatorId": data.get("creatorId"),
            "queueId": data.get("queueId"),
            "sessionId": session_id,
            "subjectSessionId": data.get("subjectSessionId") or session_id,
            "eventType": event_type,
            "positionMs": max(0, int(data.get("positionMs") or 0)),
            "durationMs": duration,
            "listenedMs": listened,
            "timeSpentMs": max(0, int(data.get("timeSpentMs") or 0)),
            "timeSpentHours": PlaybackUtils.hours(data.get("timeSpentMs")),
            "completionPercentage": min(100, round(listened / duration * 100))
            if duration > 0
            else None,
            "timestampMs": timestamp,
            "clientEventId": (
                f"{data.get('subjectSessionId') or session_id}:{event_type}:{timestamp}"
            ),
        }
        if publication_id:
            event["publicationId"] = publication_id
            event["trackContentId"] = content_id
            event["trackIndex"] = data.get("trackIndex")
            event["trackCount"] = data.get("trackCount")
            event["publicationTimeSpentMs"] = data.get("publicationTimeSpentMs")
            event["publicationTimeSpentHours"] = data.get("publicationTimeSpentHours")
            event["trackListening"] = data.get("trackListening")
        else:
            event["contentId"] = content_id
        return event

    @staticmethod
    def normalize_playback_event(event: dict) -> dict:
        if not isinstance(event, dict):
            return {}
        normalized = dict(event)
        normalized["timestampMs"] = PlaybackUtils._timestamp_ms(event.get("timestampMs"))
        normalized.setdefault(
            "clientEventId",
            f"{event.get('sessionId')}:{event.get('eventType')}:{normalized['timestampMs']}",
        )
        return normalized
