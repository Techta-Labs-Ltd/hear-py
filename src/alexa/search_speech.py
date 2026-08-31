from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from src.alexa.speech import Speech


class SearchSpeech:
    @staticmethod
    def search_no_match(query) -> str:
        safe = Speech.escape_ssml_lite(query)
        return (
            f"I couldn't find anything matching {safe}. Try another topic."
            if safe
            else "I couldn't find anything matching that. Try another topic."
        )

    @staticmethod
    def unresolved_reference_message(phrase: str, expected_types: list[str]) -> str:
        safe = Speech.escape_ssml_lite(str(phrase).strip())
        labels = {
            "creator": "creator",
            "organization": "organisation",
            "publication": "publication",
            "location": "place",
        }
        expected = [labels[value] for value in expected_types if value in labels]
        if len(expected) > 1:
            kind = f"{', '.join(expected[:-1])} or {expected[-1]}"
        else:
            kind = expected[0] if expected else "name"
        return (
            f"I couldn't find a {kind} named {safe}. Please try the full name, "
            "or ask for a different one."
        )

    @staticmethod
    def _candidate_names(candidates: list[dict]) -> tuple[list[str], list[str]]:
        raw = [str(item.get("name") or "").strip() for item in candidates if item.get("name")]
        spoken = list(dict.fromkeys(Speech.escape_ssml_lite(name) for name in raw))
        return raw[:3], spoken[:3]

    @staticmethod
    def _common_name_prefix(names: list[str]) -> str:
        common = []
        for words in zip(*(name.split() for name in names)):
            if len({word.casefold() for word in words}) != 1:
                break
            common.append(words[0])
        return " ".join(common)

    @staticmethod
    def ambiguous_reference_message(phrase: str, candidates: list[dict]) -> str:
        raw_names, names = SearchSpeech._candidate_names(candidates)
        if not names:
            return SearchSpeech.unresolved_reference_message(phrase, [])
        prefix = SearchSpeech._common_name_prefix(raw_names)
        if prefix and len(raw_names) > 1:
            suffixes = [name[len(prefix) :].strip(" ,-Ã¢â‚¬â€œâ€”") for name in raw_names]
            suffixes = [Speech.escape_ssml_lite(value) for value in suffixes if value]
            if len(suffixes) == len(raw_names):
                choices = f"{', '.join(suffixes[:-1])}, or {suffixes[-1]}"
                safe_prefix = Speech.escape_ssml_lite(prefix)
                return (
                    f"I found several matches beginning {safe_prefix}. "
                    f"Please say the distinguishing part: {choices}."
                )
        choices = names[0] if len(names) == 1 else f"{', '.join(names[:-1])}, or {names[-1]}"
        return f"I found more than one match for that name. Did you mean {choices}?"

    @staticmethod
    def ambiguity_retry_message(candidates: list[dict]) -> str:
        choices = SearchSpeech.ambiguous_reference_message("that name", candidates)
        return f"That did not match the available choices. {choices} You can also say show more."

    @staticmethod
    def ambiguity_exhausted_message(candidates: list[dict]) -> str:
        choices = SearchSpeech.ambiguous_reference_message("that name", candidates)
        return f"Those are all the matches I found. {choices}"

    @staticmethod
    def trending_intro(count, title=None, credit=None) -> str:
        total = max(0, int(count or 0))
        noun = "story" if total == 1 else "stories"
        intro = f"I found {total} trending {noun}."
        safe_title = Speech.escape_ssml_lite(str(title).strip()) if title else ""
        safe_credit = Speech.escape_ssml_lite(str(credit).strip()) if credit else ""
        if safe_title and safe_credit:
            return f"{intro} Now playing {safe_title}, by {safe_credit}."
        if safe_title:
            return f"{intro} Now playing {safe_title}."
        return f"{intro} Now playing the first one."

    @staticmethod
    def talking_newspaper_not_recognized(name) -> str:
        safe = Speech.escape_ssml_lite(name or "that name")
        return f"I couldn't match {safe} to a talking newspaper. Please say the full name."

    @staticmethod
    def _spoken_date(value: datetime, include_year: bool = True) -> str:
        label = f"{value.day} {value.strftime('%B')}"
        return f"{label} {value.year}" if include_year else label

    @staticmethod
    def _published_range(start: datetime, end: datetime) -> str:
        if end <= start:
            return ""
        if end - start <= timedelta(days=1):
            return f"on {SearchSpeech._spoken_date(start)}"
        next_month = (
            start.replace(year=start.year + 1, month=1)
            if start.month == 12
            else start.replace(month=start.month + 1)
        )
        if start.day == 1 and end.day == 1 and end == next_month:
            return f"in {start.strftime('%B %Y')}"
        last_day = end - timedelta(days=1)
        if start.year == last_day.year:
            start_label = SearchSpeech._spoken_date(start, include_year=False)
            return f"from {start_label} to {SearchSpeech._spoken_date(last_day)}"
        return f"from {SearchSpeech._spoken_date(start)} to {SearchSpeech._spoken_date(last_day)}"

    @staticmethod
    def _published_period_label(slots: dict) -> str:
        original = str(slots.get("temporalOriginal") or "").strip()
        if original:
            if re.match("^(?:on|from|since)\\b", original, re.I):
                return original
            return (
                f"on {original}"
                if re.match("^\\d{1,2}\\s+[A-Za-z]+\\s+\\d{4}$", original)
                else original
            )
        search_plan = slots.get("searchPlan") or {}
        filters = search_plan.get("filter") or {}
        start_value = filters.get("publishedFrom", search_plan.get("publishedFrom"))
        end_value = filters.get("publishedTo", search_plan.get("publishedTo"))
        if not isinstance(start_value, (int, float)) or not isinstance(end_value, (int, float)):
            return ""
        try:
            start = datetime.fromtimestamp(start_value, timezone.utc)
            end = datetime.fromtimestamp(end_value, timezone.utc)
        except (OSError, OverflowError, ValueError):
            return ""
        return SearchSpeech._published_range(start, end)

    @staticmethod
    def _facets(slots: dict) -> tuple[list[str], str, str]:
        category = str(slots.get("category") or "").strip()
        tags = [
            str(tag).strip().replace("-", " ")
            for tag in slots.get("tags") or []
            if str(tag or "").strip()
        ]
        facets = list(dict.fromkeys(([category.replace("-", " ")] if category else []) + tags))
        residual = str(slots.get("residualQuery") or "").strip()
        if residual:
            facets.append(residual)
        return facets, category, residual

    @staticmethod
    def _subject(slots: dict, facets: list[str], category: str, residual: str) -> str:
        if category and residual:
            subject = f"{' and '.join(facets[:-1])} {residual}"
        else:
            subject = " and ".join(facets) or (
                "publication" if slots.get("isPublication") else "content"
            )
        return f"the latest {subject}" if slots.get("latest") else subject

    @staticmethod
    def _append_sources(
        subject: str, slots: dict, source_name: str | None, facets: list[str]
    ) -> str:
        source = str(
            slots.get("organizationName")
            or slots.get("creatorName")
            or (source_name if slots.get("creatorIds") or slots.get("organizationIds") else "")
            or ""
        ).strip()
        if source:
            subject = f"{subject} from {source}"
        publication = str(
            slots.get("publicationName")
            or (source_name if slots.get("publicationIds") and not source else "")
            or ""
        ).strip()
        if not publication:
            return subject
        generic = {"content", "the latest content", "publication", "the latest publication"}
        if not facets and subject in generic:
            return f"the latest {publication}" if slots.get("latest") else publication
        return f"{subject} from {publication}"

    @staticmethod
    def resolved_search_request_label(slots: dict, source_name: str | None = None) -> str:
        facets, category, residual = SearchSpeech._facets(slots)
        subject = SearchSpeech._subject(slots, facets, category, residual)
        subject = SearchSpeech._append_sources(subject, slots, source_name, facets)
        city = str(slots.get("city") or slots.get("placeName") or "").strip()
        if city:
            subject = f"{subject} in {city}"
        elif slots.get("isLocal"):
            subject = f"{subject} from your community"
        published_period = SearchSpeech._published_period_label(slots)
        return f"{subject} published {published_period}" if published_period else subject

    @staticmethod
    def confirm_resolved_search(label) -> str:
        return f"Did you want me to play {Speech.escape_ssml_lite(label or 'that')}?"
