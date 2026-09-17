from __future__ import annotations

from src.alexa.speech import Speech
from src.constants.discovery import DiscoveryConstants


class SearchSpeech:
    @staticmethod
    def _with_navigation_options(
        message: str, has_more: bool, has_previous: bool = False
    ) -> str:
        navigation = ""
        if has_more:
            navigation = " To hear more choices, say show more or next."
        if has_previous:
            navigation += " You can say previous to go back."
        return f"{message}{navigation} {Speech.CHOICE_EXIT_INSTRUCTION}"

    @staticmethod
    def search_no_match(query, *, source_name: str | None = None) -> str:
        if source_name:
            return (
                f"I couldn't find anything from {Speech.escape_ssml_lite(source_name)}. "
                f"{Speech.WELCOME_REPROMPT}"
            )
        safe = Speech.escape_ssml_lite(query)
        subject = safe or "that"
        return f"I couldn't find anything matching {subject}. {Speech.WELCOME_REPROMPT}"

    @staticmethod
    def source_no_match_name(
        search_payload: dict | None,
        request_label: object = None,
        slots: dict | None = None,
    ) -> str | None:
        """Return a source name only when the request has no other constraint."""
        payload = search_payload if isinstance(search_payload, dict) else {}
        filters = SearchSpeech._search_filter(payload)
        source_keys = ("creatorIds", "organizationIds")
        source_count = sum(
            len(value if isinstance(value, (list, tuple, set)) else [value])
            for key in source_keys
            if (value := filters.get(key))
        )
        if source_count != 1 or str(payload.get("query") or payload.get("q") or "").strip():
            return None
        if set(filters) - {"creatorIds", "organizationIds", "isPublication"}:
            return None
        source_type = "creator" if filters.get("creatorIds") else "organization"
        values = slots if isinstance(slots, dict) else {}
        name = str(values.get(f"{source_type}Name") or "").strip()
        if name:
            return name
        relation, subject = SearchSpeech.clean_result_subject(request_label)
        return subject if relation == "from" and subject else None

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
        article = "an" if kind[:1].casefold() in {"a", "e", "i", "o", "u"} else "a"
        return (
            f"I couldn't find {article} {kind} named {safe}. Please try the full name, "
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
        has_previous: bool = False,
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
                return SearchSpeech._with_navigation_options(
                    message, has_more, has_previous
                )
        choices = SearchSpeech._numbered_choices(names)
        ordinals = SearchSpeech._ordinal_choices(len(names))
        message = (
            f"I found more than one match for that name. {choices} "
            f"You can say the name, or {ordinals}."
        )
        return SearchSpeech._with_navigation_options(message, has_more, has_previous)

    @staticmethod
    def _publication_choice_message(
        candidates: list[dict],
        introduction: str,
        *,
        has_more: bool = False,
        has_previous: bool = False,
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
        return SearchSpeech._with_navigation_options(message, has_more, has_previous)

    @staticmethod
    def publication_ambiguity_message(
        candidates: list[dict],
        *,
        has_more: bool = False,
        has_previous: bool = False,
    ) -> str:
        return SearchSpeech._publication_choice_message(
            candidates,
            "I found more than one publication.",
            has_more=has_more,
            has_previous=has_previous,
        )

    @staticmethod
    def more_publication_choices_message(
        candidates: list[dict],
        *,
        has_more: bool = False,
        has_previous: bool = False,
    ) -> str:
        return SearchSpeech._publication_choice_message(
            candidates,
            "Here are the next publication choices.",
            has_more=has_more,
            has_previous=has_previous,
        )

    @staticmethod
    def previous_publication_choices_message(
        candidates: list[dict],
        *,
        has_more: bool = False,
        has_previous: bool = False,
    ) -> str:
        return SearchSpeech._publication_choice_message(
            candidates,
            "Here are the previous publication choices.",
            has_more=has_more,
            has_previous=has_previous,
        )

    @staticmethod
    def first_publication_choices_message(
        candidates: list[dict], *, has_more: bool = False, has_previous: bool = False
    ) -> str:
        intro = "You are already at the first publication choices."
        return SearchSpeech._publication_choice_message(
            candidates, intro, has_more=has_more, has_previous=has_previous
        )

    @staticmethod
    def publication_choices_exhausted_message(
        candidates: list[dict], *, has_previous: bool = False
    ) -> str:
        intro = "Those are all the publication choices I found."
        return SearchSpeech._publication_choice_message(
            candidates, intro, has_previous=has_previous
        )

    @staticmethod
    def publication_choices_unavailable_message() -> str:
        return (
            "I couldn't load the next publication choices right now. Please say one of the names "
            "I already offered, or say show more to try again."
        )

    @staticmethod
    def ambiguity_retry_message(
        candidates: list[dict], *, has_more: bool = False, has_previous: bool = False
    ) -> str:
        raw_names, names = SearchSpeech._candidate_names(candidates)
        prefix = SearchSpeech._common_name_prefix(raw_names)
        if prefix and len(raw_names) > 1:
            suffixes = [
                Speech.escape_ssml_lite(n[len(prefix) :].strip(" ,-–—"))
                for n in raw_names
                if n[len(prefix) :].strip(" ,-–—")
            ]
            if len(suffixes) == len(raw_names):
                choices = SearchSpeech._numbered_choices(suffixes)
                ordinals = SearchSpeech._ordinal_choices(len(suffixes))
                safe_prefix = Speech.escape_ssml_lite(prefix)
                message = (
                    f"That did not match the available choices beginning {safe_prefix}. "
                    f"{choices} You can say the distinguishing part, or {ordinals}."
                )
                return SearchSpeech._with_navigation_options(message, has_more, has_previous)
        choices = SearchSpeech._numbered_choices(names)
        ordinals = SearchSpeech._ordinal_choices(len(names))
        message = f"That did not match the available choices. {choices} You can say the name, or {ordinals}."
        return SearchSpeech._with_navigation_options(message, has_more, has_previous)

    @staticmethod
    def ambiguity_exhausted_message(
        candidates: list[dict], *, has_previous: bool = False
    ) -> str:
        _, names = SearchSpeech._candidate_names(candidates)
        choices = SearchSpeech._numbered_choices(names)
        ordinals = SearchSpeech._ordinal_choices(len(names))
        message = (
            f"Those are all the matches I found. {choices} "
            f"You can say the name, or {ordinals}."
        )
        return SearchSpeech._with_navigation_options(
            message, False, has_previous
        )

    @staticmethod
    def trending_intro(count) -> str:
        return "This is what's trending."

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
        values: list[str] = []
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
    def clean_result_subject(value: object) -> tuple[str, str]:
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
        for prefix in (
            "the latest recordings from ",
            "recordings from ",
            "the latest content by ",
            "content by ",
            "the latest publication from ",
            "publication from ",
        ):
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
        relation, subject = SearchSpeech.clean_result_subject(request_label)
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
        if SearchSpeech._has_source_filter(search_payload):
            _, subject = SearchSpeech.clean_result_subject(request_label)
            source = subject or str(credit or "").strip()
            if source:
                return f"Playing {Speech.escape_ssml_lite(source)}."
            return "Playing the first recording."
        relation, subject = SearchSpeech._broad_result_context(search_payload, request_label)
        if subject:
            safe_subject = Speech.escape_ssml_lite(subject)
            preposition = "from" if relation == "from" else "on"
            return f"Playing content {preposition} {safe_subject}."
        return "Playing content."

    @staticmethod
    def talking_newspaper_not_recognized(name) -> str:
        safe = Speech.escape_ssml_lite(name or "that name")
        return f"I couldn't match {safe} to a talking newspaper. Please say the full name."

    @staticmethod
    def confirm_resolved_search(label) -> str:
        return f"Did you want me to play {Speech.escape_ssml_lite(label or 'that')}?"
