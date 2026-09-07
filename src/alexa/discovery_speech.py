from __future__ import annotations

from src.alexa.search_speech import SearchSpeech
from src.alexa.speech import Speech


class DiscoverySpeech:
    @staticmethod
    def subject(discovery_context: dict | None) -> str | None:
        context = discovery_context if isinstance(discovery_context, dict) else {}
        kind = str(context.get("kind") or "").strip().casefold()
        relation, subject = SearchSpeech.clean_result_subject(context.get("name"))
        if not subject:
            return None
        if kind in {"organization", "creator", "publication"}:
            return subject
        if kind == "location" or relation == "from":
            return f"content from {subject}"
        return f"content on {subject}"

    @staticmethod
    def playback_intro(
        discovery_context: dict | None,
        fallback_title: object = None,
        *,
        lead: str = "Playing",
    ) -> str:
        subject = DiscoverySpeech.subject(discovery_context)
        if subject:
            return f"{lead} {Speech.escape_ssml_lite(subject)}."
        title = Speech.humanize_spoken_title(fallback_title)
        if title:
            return f"{lead} {title}."
        return f"{lead} the next recording."
