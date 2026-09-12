from __future__ import annotations

from src.alexa.availability_speech import AvailabilitySpeech
from src.alexa.request import AlexaRequest
from src.alexa.response import AlexaResponse
from src.alexa.speech import Speech
from src.constants.availability import AvailabilityConstants
from src.constants.dialog import DialogConstants
from src.constants.discovery import DiscoveryConstants
from src.models.availability_data import AvailabilityData
from src.models.dialog import DialogSelection, DialogStateManager


class AvailabilityDialog:
    __slots__ = ("_availability", "_deps")

    def __init__(self, availability, *, deps: object) -> None:
        self._availability = availability
        self._deps = deps

    @staticmethod
    def _request_text(handler_input) -> str:
        values = []
        for slot in DialogSelection.request_slots(handler_input).values():
            value = AlexaRequest.get_resolved_slot_value(slot)
            if value:
                values.append(value)
        raw = " ".join(values).strip()
        if raw:
            return raw
        if AlexaRequest.get_intent_name(handler_input) == "PlayPublicationIntent":
            return "publication"
        return ""

    async def _select_source(self, handler_input, context: dict, candidate: dict):
        DialogStateManager.clear(handler_input, AvailabilityConstants.DIALOG_TYPE)
        await self._deps.progressive.send(handler_input, Speech.SEARCH_PROGRESSIVE)
        return await self._availability._begin_source(
            handler_input,
            candidate,
            dict(context.get("baseSearchPayload") or {}),
        )

    async def _select_format(self, handler_input, context: dict, candidate: dict):
        if candidate.get("id") == "track":
            return await self._availability._begin_tracks(handler_input, context)
        publications = list(context.get("publicationCandidates") or [])
        publication_context = {
            **context,
            "kind": AvailabilityConstants.PUBLICATION_KIND,
            "candidates": publications,
            "offset": 0,
        }
        if len(publications) == 1 and int(context.get("publicationCount") or 0) == 1:
            return await self._availability._play_selected(
                handler_input, publications[0], dict(context.get("source") or {})
            )
        return self._availability._choice_response(handler_input, publication_context)

    async def _select(self, handler_input, context: dict, candidate: dict):
        kind = context.get("kind")
        if kind == AvailabilityConstants.SOURCE_KIND:
            return await self._select_source(handler_input, context, candidate)
        if kind == AvailabilityConstants.FORMAT_KIND:
            return await self._select_format(handler_input, context, candidate)
        return await self._availability._play_selected(
            handler_input, candidate, dict(context.get("source") or {})
        )

    async def _load_remote_page(
        self,
        handler_input,
        context: dict,
        requested_page: int | None = None,
    ) -> dict:
        next_page = (
            max(0, int(requested_page))
            if requested_page is not None
            else max(0, int(context.get("apiPage") or 0)) + 1
        )
        if context.get("kind") == AvailabilityConstants.TRACK_KIND:
            result = await self._availability._search_source(
                handler_input,
                dict(context.get("source") or {}),
                dict(context.get("baseSearchPayload") or {}),
                next_page,
            )
            incoming = AvailabilityData.track_candidates(result)
            context["totalPages"] = AvailabilityData.search_total_pages(result)
            context["hasMore"] = bool(
                context["totalPages"] and next_page + 1 < context["totalPages"]
            )
        else:
            result = await self._availability._availability(
                handler_input,
                dict(context.get("availabilityFilter") or {}),
                next_page,
                dict(context.get("availabilityDiscovery") or {}),
            )
            incoming = (
                AvailabilityData.source_candidates(result, context.get("sourceType"))
                if context.get("kind") == AvailabilityConstants.SOURCE_KIND
                else AvailabilityData.publication_candidates(result)
            )
            if context.get("sourceType") == "creator":
                incoming = incoming[: DiscoveryConstants.CHOICE_PAGE_SIZE]
            context["totalPages"] = int(result.get("total_pages") or 0)
            context["hasMore"] = bool(result.get("has_more"))
        if result.get("failed"):
            context["pageLoadFailed"] = True
            return context
        if context.get("sourceType") == "creator":
            context.update(
                {
                    "candidates": incoming,
                    "offset": 0,
                    "apiPage": next_page,
                    "pageLoadFailed": False,
                }
            )
            return context
        existing = list(context.get("candidates") or [])
        seen = {(str(item.get("type")), str(item.get("id"))) for item in existing}
        existing.extend(
            item
            for item in incoming
            if (str(item.get("type")), str(item.get("id"))) not in seen
        )
        context.update(
            {
                "candidates": existing,
                "apiPage": next_page,
                "pageLoadFailed": False,
            }
        )
        return context

    async def _more(self, handler_input, context: dict):
        current_offset = max(0, int(context.get("offset") or 0))
        next_offset = current_offset + len(AvailabilityData.displayed(context))
        creator_page = context.get("sourceType") == "creator"
        if next_offset >= len(context.get("candidates") or []) and AvailabilityData.remote_more(
            context
        ):
            await self._deps.progressive.send(handler_input, Speech.SEARCH_PROGRESSIVE)
            context = await self._load_remote_page(handler_input, context)
            if creator_page and not context.get("pageLoadFailed"):
                return self._availability._choice_response(handler_input, context, "more")
        if context.get("pageLoadFailed"):
            context["offset"] = current_offset
            displayed = AvailabilityData.displayed(context)
            kind = str(context.get("kind") or "choice")
            has_previous = current_offset > 0 or bool(
                creator_page and int(context.get("apiPage") or 0) > 0
            )
            self._availability._activate(handler_input, context)
            return self._availability._response(
                handler_input,
                AvailabilitySpeech.page_unavailable(
                    kind, displayed, has_previous=has_previous
                ),
                "Say one of the names, or ask for more choices to try again.",
                displayed,
            )
        if next_offset >= len(context.get("candidates") or []):
            context["offset"] = current_offset
            displayed = AvailabilityData.displayed(context)
            kind = str(context.get("kind") or "choice")
            speech = f"Those are all the {kind} choices. " + AvailabilitySpeech.choice_retry(
                kind,
                displayed,
                has_more=False,
                has_previous=current_offset > 0
                or bool(creator_page and int(context.get("apiPage") or 0) > 0),
            )
            self._availability._activate(handler_input, context)
            return self._availability._response(
                handler_input,
                speech,
                "Say one of the names, or say first, second, or third.",
                displayed,
            )
        context["offset"] = next_offset
        return self._availability._choice_response(handler_input, context, "more")

    async def _previous(self, handler_input, context: dict):
        if context.get("sourceType") == "creator":
            current_page = max(0, int(context.get("apiPage") or 0))
            if current_page == 0:
                return self._availability._choice_response(
                    handler_input, context, "initial"
                )
            await self._deps.progressive.send(handler_input, Speech.SEARCH_PROGRESSIVE)
            context = await self._load_remote_page(
                handler_input,
                context,
                current_page - 1,
            )
            if context.get("pageLoadFailed"):
                context["pageLoadFailed"] = False
                return self._availability._choice_response(
                    handler_input, context, "initial"
                )
            return self._availability._choice_response(handler_input, context, "previous")
        current_offset = max(0, int(context.get("offset") or 0))
        context["offset"] = max(0, current_offset - DiscoveryConstants.CHOICE_PAGE_SIZE)
        position = "previous" if current_offset else "initial"
        return self._availability._choice_response(handler_input, context, position)

    async def handle(self, handler_input):
        active = DialogStateManager.get_active(handler_input) or {}
        context = dict(active.get("context") or {})
        if active.get("type") != AvailabilityConstants.DIALOG_TYPE or not context:
            return None
        intent_name = AlexaRequest.get_intent_name(handler_input) or ""
        if intent_name in DialogConstants.CHOICE_DISMISS_INTENTS:
            DialogStateManager.clear(handler_input, AvailabilityConstants.DIALOG_TYPE)
            return AlexaResponse.present_idle_next(
                handler_input,
                Speech.CHOICES_DISMISSED,
                Speech.WELCOME_REPROMPT,
            )
        if intent_name in AvailabilityConstants.MORE_INTENTS:
            return await self._more(handler_input, context)
        if intent_name in AvailabilityConstants.PREVIOUS_INTENTS:
            return await self._previous(handler_input, context)
        if intent_name == "AMAZON.NoIntent" and context.get("singleChoice"):
            DialogStateManager.clear(handler_input, AvailabilityConstants.DIALOG_TYPE)
            return AlexaResponse.present_idle_next(
                handler_input,
                "Ok. What would you like to listen to instead?",
                Speech.WELCOME_REPROMPT,
            )
        if intent_name == "AMAZON.YesIntent" and context.get("singleChoice"):
            return await self._select(
                handler_input, context, list(context.get("candidates") or [])[0]
            )
        binary_format_choice = bool(
            intent_name in {"AMAZON.YesIntent", "AMAZON.NoIntent"}
            and context.get("kind") == AvailabilityConstants.FORMAT_KIND
        )
        if binary_format_choice:
            publications = list(context.get("publicationCandidates") or [])
            single_publication_yes = bool(
                intent_name == "AMAZON.YesIntent"
                and int(context.get("publicationCount") or 0) == 1
                and publications
            )
            if single_publication_yes:
                return await self._availability._play_selected(
                    handler_input, publications[0], dict(context.get("source") or {})
                )
            if intent_name == "AMAZON.NoIntent" and int(
                context.get("publicationCount") or 0
            ) == 1:
                return await self._availability._begin_tracks(handler_input, context)
        if intent_name == "AMAZON.NoIntent":
            DialogStateManager.clear(handler_input, AvailabilityConstants.DIALOG_TYPE)
            return AlexaResponse.present_idle_next(
                handler_input,
                Speech.CHOICES_DISMISSED,
                Speech.WELCOME_REPROMPT,
            )
        raw = self._request_text(handler_input)
        candidate = DialogSelection.match_pending_candidate(handler_input, context, raw)
        if candidate:
            return await self._select(handler_input, context, candidate)
        displayed = AvailabilityData.displayed(context)
        has_more = AvailabilityData.has_more(context)
        has_previous = max(0, int(context.get("offset") or 0)) > 0 or bool(
            context.get("sourceType") == "creator"
            and int(context.get("apiPage") or 0) > 0
        )
        kind = str(context.get("kind") or "choice")
        speech = AvailabilitySpeech.choice_retry(
            kind, displayed, has_more=has_more, has_previous=has_previous
        )
        self._availability._activate(handler_input, context)
        return self._availability._response(
            handler_input,
            speech,
            AvailabilitySpeech.choice_reprompt(
                kind, len(displayed), has_more, has_previous
            ),
            displayed,
        )
