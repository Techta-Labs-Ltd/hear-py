from __future__ import annotations

from src.alexa.request import AlexaRequest
from src.constants.discovery import DiscoveryConstants
from src.models.user import User
from src.utils.filters import SearchFilters
from src.utils.search_payload import SearchPayload


class AvailabilityRequest:
    @staticmethod
    def local_payload(handler_input, nlp: dict) -> dict:
        store = User.snapshot(handler_input)
        slots = nlp.get("slots") if isinstance(nlp.get("slots"), dict) else {}
        existing = nlp.get("searchPayload") or slots.get("searchPlan") or {}
        if existing:
            payload = SearchPayload.with_pagination(
                existing,
                DiscoveryConstants.CHOICE_PAGE_SIZE,
            )
            payload["limit"] = DiscoveryConstants.CHOICE_PAGE_SIZE
            filters = SearchPayload.resolution_filter(slots, payload.get("filter"))
            payload["filter"] = SearchFilters.clean(filters)
            payload["isLocal"] = True
        else:
            filters = SearchPayload.resolution_filter(slots, {"isLocal": True})
            payload = SearchPayload.build(
                AlexaRequest.get_user_id(handler_input),
                store,
                q=str(slots.get("residualQuery") or ""),
                limit=DiscoveryConstants.CHOICE_PAGE_SIZE,
                page=0,
                sort="nearest",
                nlp_filter=filters,
            )
        country_code = str(slots.get("countryCode") or "").strip()
        if country_code:
            payload.setdefault("filter", {})["countryCode"] = country_code
        return SearchPayload.with_identity(
            payload,
            alexa_user_id=AlexaRequest.get_user_id(handler_input),
            listener_id=store.get("listenerId"),
        )
