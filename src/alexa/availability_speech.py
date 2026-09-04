from __future__ import annotations

from src.alexa.speech import Speech
from src.constants.discovery import DiscoveryConstants


class AvailabilitySpeech:
    @staticmethod
    def _count_label(value: int) -> str:
        words = (
            "zero",
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
            "ten",
            "eleven",
            "twelve",
            "thirteen",
            "fourteen",
            "fifteen",
            "sixteen",
            "seventeen",
            "eighteen",
            "nineteen",
            "twenty",
        )
        count = max(0, int(value or 0))
        return words[count] if count < len(words) else str(count)

    @staticmethod
    def _numbered_choices(candidates: list[dict]) -> str:
        ordinals = tuple(value.title() for value in DiscoveryConstants.CHOICE_ORDINALS)
        spoken = []
        for index, candidate in enumerate(candidates[: DiscoveryConstants.CHOICE_PAGE_SIZE]):
            name = Speech.escape_ssml_lite(str(candidate.get("name") or "").strip())
            if name:
                spoken.append(f"{ordinals[index]}, {name}.")
        return " ".join(spoken)

    @staticmethod
    def _choice_instruction(count: int, noun: str, has_more: bool) -> str:
        ordinals = ("first", "first or second", "first, second, or third")
        choice = ordinals[max(0, min(count, DiscoveryConstants.CHOICE_PAGE_SIZE) - 1)]
        if has_more:
            choice = choice.replace(", or ", ", ")
            return (
                f"You can say {choice}, show more, or next. "
                f"You can also say previous. {Speech.CHOICE_EXIT_INSTRUCTION}"
            )
        return f"You can say {choice} or previous. {Speech.CHOICE_EXIT_INSTRUCTION}"

    @staticmethod
    def choice_reprompt(kind: str, count: int, has_more: bool) -> str:
        nouns = {
            "source": ("source", "sources"),
            "publication": ("publication", "publications"),
            "track": ("track", "tracks"),
        }
        singular, plural = nouns.get(kind, ("choice", "choices"))
        ordinals = ("first", "first or second", "first, second, or third")
        choices = ordinals[max(0, min(count, DiscoveryConstants.CHOICE_PAGE_SIZE) - 1)]
        if has_more:
            choices = choices.replace(", or ", ", ") + ", show more, or next"
        return (
            f"Say the {singular} name, or say {choices}. "
            f"You can also say previous. {Speech.CHOICE_EXIT_INSTRUCTION}"
        )

    @staticmethod
    def _position_opening(
        candidates: list[dict], position: str, noun: str, default: str, has_more: bool
    ) -> str:
        count = len(candidates)
        label = AvailabilitySpeech._count_label(count)
        verb = "is" if count == 1 else "are"
        singular = noun.removesuffix("s") if count == 1 else noun
        if position == "more":
            return f"Here {verb} the next {label} {singular}."
        if position == "previous":
            return f"Here {verb} the previous {singular}."
        if has_more:
            return f"Here {verb} the first {label} {singular}."
        return default

    @staticmethod
    def local_source_choices(
        candidates: list[dict],
        *,
        position: str = "initial",
        has_more: bool = False,
        requested_city: str | None = None,
    ) -> str:
        if not candidates:
            return "I couldn't find any local sources just now. What would you like to hear?"
        if requested_city and position == "initial":
            safe_city = Speech.escape_ssml_lite(requested_city)
            opening = f"Here are the sources I found in {safe_city}."
        else:
            opening = AvailabilitySpeech._position_opening(
                candidates,
                position,
                "local sources" if not requested_city else "sources",
                "Here are the local sources I found.",
                has_more,
            )
        choices = AvailabilitySpeech._numbered_choices(candidates)
        instruction = AvailabilitySpeech._choice_instruction(len(candidates), "sources", has_more)
        return f"{opening} {choices} {instruction}"

    @staticmethod
    def one_local_source(source_name: str, *, requested_city: str | None = None) -> str:
        safe = Speech.escape_ssml_lite(source_name)
        if requested_city:
            safe_city = Speech.escape_ssml_lite(requested_city)
            return f"I found content in {safe_city} from {safe}. Would you like to listen?"
        return f"I found content near you from {safe}. Would you like to listen?"

    @staticmethod
    def source_content_question(
        source_name: str,
        publication_count: int,
        track_count: int,
        publication_name: str | None = None,
    ) -> str:
        safe_source = Speech.escape_ssml_lite(source_name)
        publications = AvailabilitySpeech._count_label(publication_count)
        tracks = AvailabilitySpeech._count_label(track_count)
        publication_noun = "publication" if publication_count == 1 else "publications"
        track_noun = "track" if track_count == 1 else "tracks"
        summary = f"{safe_source} has {publications} {publication_noun} and {tracks} {track_noun}."
        if publication_count == 1 and publication_name:
            safe_publication = Speech.escape_ssml_lite(publication_name)
            return (
                f"{summary} The publication is {safe_publication}. "
                "Would you like to hear it, or choose a track?"
            )
        if track_count == 1:
            return f"{summary} Would you like to choose a publication, or hear the track?"
        return f"{summary} Would you like to hear a publication, or choose a track?"

    @staticmethod
    def content_type_reprompt(publication_count: int, track_count: int) -> str:
        if publication_count == 1:
            return "Say publication to hear it, or say tracks to choose a track."
        if track_count == 1:
            return "Say publications to choose one, or say track to hear it."
        return "Say publications, or say tracks."

    @staticmethod
    def publication_choices(
        candidates: list[dict],
        *,
        source_name: str | None = None,
        publication_count: int | None = None,
        position: str = "initial",
        has_more: bool = False,
    ) -> str:
        if not candidates:
            return "I couldn't load the publication choices just now. Please try again."
        prefix = ""
        if source_name and publication_count:
            count = AvailabilitySpeech._count_label(publication_count)
            noun = "publication" if publication_count == 1 else "publications"
            prefix = f"{Speech.escape_ssml_lite(source_name)} has {count} {noun}. "
        opening = AvailabilitySpeech._position_opening(
            candidates,
            position,
            "publications",
            "Here are the available publications.",
            has_more,
        )
        choices = AvailabilitySpeech._numbered_choices(candidates)
        instruction = AvailabilitySpeech._choice_instruction(
            len(candidates), "publications", has_more
        )
        return f"{prefix}{opening} {choices} {instruction}"

    @staticmethod
    def track_choices(
        candidates: list[dict], *, position: str = "initial", has_more: bool = False
    ) -> str:
        if not candidates:
            return "I couldn't load the track choices just now. Please try again."
        opening = AvailabilitySpeech._position_opening(
            candidates,
            position,
            "tracks",
            "Here are the available tracks.",
            has_more,
        )
        choices = AvailabilitySpeech._numbered_choices(candidates)
        instruction = AvailabilitySpeech._choice_instruction(len(candidates), "tracks", has_more)
        return f"{opening} {choices} {instruction}"

    @staticmethod
    def choice_retry(kind: str, candidates: list[dict], *, has_more: bool = False) -> str:
        noun = "source" if kind == "source" else kind
        choices = AvailabilitySpeech._numbered_choices(candidates)
        instruction = AvailabilitySpeech._choice_instruction(len(candidates), f"{noun}s", has_more)
        return f"I didn't match that to one of the {noun} choices. {choices} {instruction}"

    @staticmethod
    def page_unavailable(kind: str, candidates: list[dict]) -> str:
        noun = "source" if kind == "source" else kind
        choices = AvailabilitySpeech._numbered_choices(candidates)
        instruction = AvailabilitySpeech._choice_instruction(len(candidates), f"{noun}s", True)
        return f"I couldn't load the next {noun} choices just now. {choices} {instruction}"

    @staticmethod
    def playing_choice(title: str, source_name: str | None = None) -> str:
        safe_title = Speech.escape_ssml_lite(title)
        safe_source = Speech.escape_ssml_lite(source_name or "")
        return (
            f"Playing {safe_title}, from {safe_source}."
            if safe_source
            else f"Playing {safe_title}."
        )
