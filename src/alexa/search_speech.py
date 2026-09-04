from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from src.alexa.speech import Speech
from src.constants.discovery import DiscoveryConstants


class SearchSpeech:
    @staticmethod
    def _with_more_options(message: str, has_more: bool) -> str:
        return (
            f"{message} To hear more choices, say show more or next. "
            f"You can also say previous. {Speech.CHOICE_EXIT_INSTRUCTION}"
            if has_more
            else (
                f"{message} You can say previous to go back. "
                f"{Speech.CHOICE_EXIT_INSTRUCTION}"
            )
        )

    @staticmethod
    def search_no_match(query) -> str:
        safe = Speech.escape_ssml_lite(query)
        return (
            f"I couldn't find anything matching {safe}. Try saying play followed by "
            "a different topic, creator, publication, or city."
            if safe
            else "I couldn't find anything matching that. Try saying play followed by "
            "a topic, creator, publication, or city."
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
        page_size = DiscoveryConstants.CHOICE_PAGE_SIZE
        return raw[:page_size], spoken[:page_size]

    @staticmethod
    def _numbered_choices(names: list[str]) -> str:
        return " ".join(
            f"{DiscoveryConstants.CHOICE_ORDINALS[index].title()}, {name}."
            for index, name in enumerate(names[: DiscoveryConstants.CHOICE_PAGE_SIZE])
        )

    @staticmethod
    def _ordinal_choices(count: int) -> str:
        if count <= 1:
            return "first"
        if count == 2:
            return "first or second"
        return "first, second, or third"

    @staticmethod
    def choice_reprompt(
        candidates: list[dict],
        *,
        publication_picker: bool = False,
        has_more: bool = False,
        has_previous: bool = False,
    ) -> str:
        _, names = SearchSpeech._candidate_names(candidates)
        subject = "the publication name" if publication_picker else "a name"
        prompt = f"Say {subject}, or say {SearchSpeech._ordinal_choices(len(names))}"
        if has_more:
            prompt += ", or say show more or next"
        if has_previous:
            prompt += ", or say previous"
        return f"{prompt}. {Speech.CHOICE_EXIT_INSTRUCTION}"

    @staticmethod
    def _common_name_prefix(names: list[str]) -> str:
        common = []
        for words in zip(*(name.split() for name in names)):
            if len({word.casefold() for word in words}) != 1:
                break
            common.append(words[0])
        return " ".join(common)

    @staticmethod
    def ambiguous_reference_message(
        phrase: str,
        candidates: list[dict],
        *,
        has_more: bool = False,
    ) -> str:
        raw_names, names = SearchSpeech._candidate_names(candidates)
        if not names:
            return SearchSpeech.unresolved_reference_message(phrase, [])
        prefix = SearchSpeech._common_name_prefix(raw_names)
        if prefix and len(raw_names) > 1:
            suffixes = [name[len(prefix) :].strip(" ,-Ã¢â‚¬â€œâ€”") for name in raw_names]
            suffixes = [Speech.escape_ssml_lite(value) for value in suffixes if value]
            if len(suffixes) == len(raw_names):
                choices = SearchSpeech._numbered_choices(suffixes)
                ordinals = SearchSpeech._ordinal_choices(len(suffixes))
                safe_prefix = Speech.escape_ssml_lite(prefix)
                message = (
                    f"I found several matches beginning {safe_prefix}. "
                    f"{choices} You can say the distinguishing part, or {ordinals}."
                )
                return SearchSpeech._with_more_options(message, has_more)
        choices = SearchSpeech._numbered_choices(names)
        ordinals = SearchSpeech._ordinal_choices(len(names))
        message = (
            f"I found more than one match for that name. {choices} "
            f"You can say the name, or {ordinals}."
        )
        return SearchSpeech._with_more_options(message, has_more)

    @staticmethod
    def _publication_choice_message(
        candidates: list[dict],
        introduction: str,
        *,
        has_more: bool = False,
    ) -> str:
        _, names = SearchSpeech._candidate_names(candidates)
        if not names:
            return f"{introduction} Which publication would you like?"
        choices = SearchSpeech._numbered_choices(names)
        ordinals = SearchSpeech._ordinal_choices(len(names))
        message = (
            f"{introduction} {choices} "
            f"You can say the publication name, or {ordinals}."
        )
        return SearchSpeech._with_more_options(message, has_more)

    @staticmethod
    def publication_ambiguity_message(
        candidates: list[dict],
        *,
        has_more: bool = False,
    ) -> str:
        return SearchSpeech._publication_choice_message(
            candidates,
            "I found more than one publication.",
            has_more=has_more,
        )

    @staticmethod
    def more_publication_choices_message(
        candidates: list[dict],
        *,
        has_more: bool = False,
    ) -> str:
        return SearchSpeech._publication_choice_message(
            candidates,
            "Here are the next publication choices.",
            has_more=has_more,
        )

    @staticmethod
    def previous_publication_choices_message(
        candidates: list[dict],
        *,
        has_more: bool = False,
    ) -> str:
        return SearchSpeech._publication_choice_message(
            candidates,
            "Here are the previous publication choices.",
            has_more=has_more,
        )

    @staticmethod
    def first_publication_choices_message(
        candidates: list[dict],
        *,
        has_more: bool = False,
    ) -> str:
        return SearchSpeech._publication_choice_message(
            candidates,
            "You are already at the first publication choices.",
            has_more=has_more,
        )

    @staticmethod
    def publication_choices_exhausted_message(candidates: list[dict]) -> str:
        return SearchSpeech._publication_choice_message(
            candidates, "Those are all the publication choices I found."
        )

    @staticmethod
    def publication_choices_unavailable_message() -> str:
        return (
            "I couldn't load the next publication choices right now. Please say one of the names "
            "I already offered, or say show more to try again."
        )

    @staticmethod
    def ambiguity_retry_message(
        candidates: list[dict], *, has_more: bool = False
    ) -> str:
        _, names = SearchSpeech._candidate_names(candidates)
        choices = SearchSpeech._numbered_choices(names)
        ordinals = SearchSpeech._ordinal_choices(len(names))
        message = (
            f"That did not match the available choices. {choices} "
            f"You can say the name, or {ordinals}."
        )
        return SearchSpeech._with_more_options(message, has_more)

    @staticmethod
    def ambiguity_exhausted_message(candidates: list[dict]) -> str:
        _, names = SearchSpeech._candidate_names(candidates)
        choices = SearchSpeech._numbered_choices(names)
        ordinals = SearchSpeech._ordinal_choices(len(names))
        return (
            f"Those are all the matches I found. {choices} "
            f"You can say the name, or {ordinals}."
        )

    @staticmethod
    def trending_intro(count) -> str:
        total = max(0, int(count or 0))
        noun = "story" if total == 1 else "stories"
        count_label = "one" if total == 1 else str(total)
        intro = f"Here {'is' if total == 1 else 'are'} {count_label} trending {noun}."
        return intro if total == 1 else f"{intro} Here's the first one."

    @staticmethod
    def _search_filter(search_payload: dict | None) -> dict:
        payload = search_payload if isinstance(search_payload, dict) else {}
        filters = payload.get("filter")
        return filters if isinstance(filters, dict) else {}

    @staticmethod
    def _has_source_filter(search_payload: dict | None) -> bool:
        payload = search_payload if isinstance(search_payload, dict) else {}
        filters = SearchSpeech._search_filter(payload)
        return any(
            filters.get(key) or payload.get(key)
            for key in ("creatorIds", "organizationIds", "publicationIds")
        )

    @staticmethod
    def _filter_labels(filters: dict) -> list[str]:
        values = []
        for key in ("categorySlugs", "tags"):
            raw = filters.get(key) or []
            raw = raw if isinstance(raw, (list, tuple, set)) else [raw]
            values.extend(
                str(value).strip().replace("-", " ")
                for value in raw
                if str(value or "").strip()
            )
        return list(dict.fromkeys(values))

    @staticmethod
    def _clean_result_subject(value: object) -> tuple[str, str]:
        subject = " ".join(str(value or "").strip().split())
        lowered = subject.casefold()
        for prefix in ("the latest content on ", "content on "):
            if lowered.startswith(prefix):
                return "about", subject[len(prefix) :].strip()
        for prefix in ("the latest content published ", "content published "):
            if lowered.startswith(prefix):
                return "", f"published {subject[len(prefix) :].strip()}"
        for prefix in ("the latest content in ", "content in "):
            if lowered.startswith(prefix):
                return "from", subject[len(prefix) :].strip()
        for prefix in ("the latest content from ", "content from "):
            if lowered.startswith(prefix):
                return "from", subject[len(prefix) :].strip()
        if lowered.startswith("the latest "):
            subject = subject[len("the latest ") :].strip()
        if subject.casefold() in {
            "",
            "anything",
            "content",
            "something",
            "that request",
            "your search",
        }:
            return "", ""
        return "about", subject

    @staticmethod
    def _broad_result_context(
        search_payload: dict | None, request_label: object = None
    ) -> tuple[str, str]:
        payload = search_payload if isinstance(search_payload, dict) else {}
        filters = SearchSpeech._search_filter(payload)
        relation, subject = SearchSpeech._clean_result_subject(request_label)
        labels = SearchSpeech._filter_labels(filters)
        query = str(payload.get("query") or payload.get("q") or "").strip()
        if query and query.casefold() not in {value.casefold() for value in labels}:
            labels.append(query)
        missing = [value for value in labels if value.casefold() not in subject.casefold()]
        if subject and missing:
            subject = f"{subject} and {' and '.join(missing)}"
        elif not subject:
            relation = "about" if labels else ""
            subject = " and ".join(labels)
        city = str(filters.get("city") or payload.get("city") or "").strip()
        if city and city.casefold() not in subject.casefold():
            if subject:
                subject = f"{subject} in {city}"
            else:
                relation, subject = "from", city
        if not subject and (payload.get("isLocal") or filters.get("isLocal")):
            relation, subject = "from", "your community"
        return relation, subject

    @staticmethod
    def search_results_intro(
        count,
        search_payload: dict | None = None,
        request_label: object = None,
        title: object = None,
        credit: object = None,
    ) -> str:
        total = max(0, int(count or 0))
        noun = "story" if total == 1 else "stories"
        count_label = "one" if total == 1 else str(total)
        if SearchSpeech._has_source_filter(search_payload):
            intro = f"I found {count_label} {noun}."
            safe_title = Speech.escape_ssml_lite(str(title).strip()) if title else ""
            safe_credit = Speech.escape_ssml_lite(str(credit).strip()) if credit else ""
            if safe_title and safe_credit:
                return f"{intro} Now playing {safe_title}, by {safe_credit}."
            if safe_title:
                return f"{intro} Now playing {safe_title}."
            return f"{intro} Now playing the first one."
        relation, subject = SearchSpeech._broad_result_context(search_payload, request_label)
        detail = ""
        if subject:
            safe_subject = Speech.escape_ssml_lite(subject)
            detail = f" {relation} {safe_subject}" if relation else f" {safe_subject}"
        intro = f"Here {'is' if total == 1 else 'are'} {count_label} {noun}{detail}."
        return intro if total == 1 else f"{intro} Here's the first one."

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
