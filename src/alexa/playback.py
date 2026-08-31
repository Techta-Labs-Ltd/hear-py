from __future__ import annotations

from dataclasses import dataclass

from config import settings
from src.alexa.request import AlexaRequest
from src.utils.content import ContentUtils
from src.utils.playback import PlaybackUtils


@dataclass(frozen=True, slots=True)
class PlayDirective:
    url: str
    token: str
    offset_ms: int = 0
    previous_token: str | None = None
    metadata: dict | None = None
    progress_report: bool = False
    duration_secs: float | None = None


class AlexaPlayback:
    @staticmethod
    def resolve_seek_ms(handler_input) -> int:
        duration = AlexaRequest.get_slot_value(handler_input, "time")
        parsed = PlaybackUtils.parse_duration_ms(duration)
        if parsed:
            return parsed
        number = AlexaRequest.get_slot_value(handler_input, "number")
        try:
            return int(number) * 1000 if number is not None else settings.seek_step_ms
        except (TypeError, ValueError):
            return settings.seek_step_ms

    @staticmethod
    def feedback_trigger_ms(duration_secs) -> int | None:
        if not isinstance(duration_secs, (int, float)) or duration_secs <= 0:
            return None
        threshold = settings.HEAR_FEEDBACK_SHORT_THRESHOLD_SECS or 30
        ratio = (
            settings.HEAR_FEEDBACK_SHORT_RATIO or 0.6
            if duration_secs < threshold
            else settings.HEAR_FEEDBACK_RATIO or 0.7
        )
        return int(duration_secs * 1000 * ratio)

    @staticmethod
    def feedback_progress_report_options(duration_secs) -> dict:
        delay_ms = AlexaPlayback.feedback_trigger_ms(duration_secs)
        if delay_ms is None:
            fallback = settings.feedback_trigger_ms or 90000
            return {
                "progressReportDelayInMilliseconds": fallback,
                "progressReportIntervalInMilliseconds": fallback * 10,
            }
        return {
            "progressReportDelayInMilliseconds": delay_ms,
            "progressReportIntervalInMilliseconds": max(delay_ms * 2, 86400000),
        }

    @staticmethod
    def _normalize_metadata(metadata: dict | None) -> dict | None:
        if not isinstance(metadata, dict):
            return None
        title = metadata.get("title")
        subtitle = metadata.get("subtitle")
        if not isinstance(title, str) or not title.strip():
            return None
        if not isinstance(subtitle, str):
            return None
        return {"title": title.strip(), "subtitle": subtitle}

    @staticmethod
    def build_play_directive(request: PlayDirective) -> dict | None:
        if not request.url or not request.token:
            return None
        stream = {
            "url": request.url,
            "token": request.token,
            "offsetInMilliseconds": request.offset_ms,
        }
        if request.progress_report:
            stream.update(AlexaPlayback.feedback_progress_report_options(request.duration_secs))
        audio_item = {"stream": stream}
        normalized = AlexaPlayback._normalize_metadata(request.metadata)
        if normalized:
            audio_item["metadata"] = normalized
        directive = {
            "type": "AudioPlayer.Play",
            "playBehavior": "ENQUEUE" if request.previous_token else "REPLACE_ALL",
            "audioItem": audio_item,
        }
        if request.previous_token:
            stream["expectedPreviousToken"] = request.previous_token
        return directive

    @staticmethod
    def build_stop_directive() -> dict:
        return {"type": "AudioPlayer.Stop"}

    @staticmethod
    def build_content_metadata(
        content: dict,
        track_title: str | None = None,
        resolved_category: str | None = None,
    ) -> dict:
        category = (
            resolved_category or content.get("category") or (content.get("categories") or [None])[0]
        )
        if isinstance(category, dict):
            category = category.get("name") or category.get("slug")
        locality = content.get("locality")
        if isinstance(locality, dict):
            locality = locality.get("name") or locality.get("slug")
        subtitle = [str(value) for value in (category, locality) if value]
        tags = content.get("tags") or []
        if tags:
            subtitle.append(", ".join((str(tag) for tag in tags)))
        track_candidate = (track_title or "").strip()
        parent_candidate = (content.get("spokenTitle") or content.get("title") or "").strip()
        if track_candidate and (not ContentUtils.is_id_like_label(track_candidate)):
            title = track_candidate
        elif parent_candidate and (not ContentUtils.is_id_like_label(parent_candidate)):
            title = parent_candidate
        else:
            title = parent_candidate or track_candidate or "Hear"
        return {"title": title, "subtitle": " · ".join(subtitle)}
