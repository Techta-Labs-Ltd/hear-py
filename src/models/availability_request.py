from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from src.constants.discovery import DiscoveryConstants
from src.utils.filters import SearchFilters
from src.utils.search_payload import SearchPayload


@dataclass(frozen=True, slots=True)
class AvailabilityRequest:
    query: str
    filters: Mapping[str, object]
    alexa_user_id: str | None
    listener_id: str | None
    page: int = 0
    limit: int = DiscoveryConstants.CHOICE_PAGE_SIZE
    sort: str | None = None
    is_local: bool = True
    wire_fields: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "query", str(self.query or "").strip())
        object.__setattr__(
            self,
            "filters",
            MappingProxyType(SearchFilters.clean(dict(self.filters))),
        )
        object.__setattr__(
            self,
            "alexa_user_id",
            str(self.alexa_user_id or "").strip() or None,
        )
        object.__setattr__(self, "listener_id", str(self.listener_id or "").strip() or None)
        object.__setattr__(self, "page", max(0, int(self.page or 0)))
        object.__setattr__(self, "limit", max(1, int(self.limit or 1)))
        object.__setattr__(self, "sort", str(self.sort or "").strip() or None)
        object.__setattr__(self, "wire_fields", MappingProxyType(dict(self.wire_fields)))

    @classmethod
    def local(
        cls,
        nlp: dict | None,
        *,
        alexa_user_id: str | None,
        user_state: dict | None,
    ) -> "AvailabilityRequest":
        resolved = dict(nlp) if isinstance(nlp, dict) else {}
        raw_slots = resolved.get("slots")
        slots = dict(raw_slots) if isinstance(raw_slots, dict) else {}
        existing = resolved.get("searchPayload") or slots.get("searchPlan") or {}
        store = dict(user_state) if isinstance(user_state, dict) else {}
        if isinstance(existing, dict) and existing:
            payload = SearchPayload.with_pagination(
                existing,
                DiscoveryConstants.CHOICE_PAGE_SIZE,
            )
            return cls(
                query=payload.get("query") or "",
                filters=SearchPayload.resolution_filter(slots, payload.get("filter")),
                alexa_user_id=alexa_user_id,
                listener_id=store.get("listenerId"),
                page=payload.get("page") or 0,
                limit=DiscoveryConstants.CHOICE_PAGE_SIZE,
                sort=payload.get("sort"),
                wire_fields={
                    key: value
                    for key, value in payload.items()
                    if key
                    not in {
                        "query",
                        "filter",
                        "page",
                        "limit",
                        "sort",
                        "isLocal",
                        "alexaUserId",
                        "listenerId",
                    }
                },
            )
        filters = SearchPayload.resolution_filter(slots, {"isLocal": True})
        country_code = str(slots.get("countryCode") or "").strip()
        if country_code:
            filters["countryCode"] = country_code
        payload = SearchPayload.build(
            alexa_user_id,
            store,
            q=str(slots.get("residualQuery") or ""),
            limit=DiscoveryConstants.CHOICE_PAGE_SIZE,
            page=0,
            nlp_filter=filters,
        )
        return cls(
            query=payload.get("query") or "",
            filters=filters,
            alexa_user_id=alexa_user_id,
            listener_id=store.get("listenerId"),
            page=payload.get("page") or 0,
            limit=DiscoveryConstants.CHOICE_PAGE_SIZE,
            sort=payload.get("sort"),
        )

    def to_search_payload(self) -> dict:
        payload = {
            **self.wire_fields,
            "query": self.query,
            "filter": dict(self.filters),
            "page": self.page,
            "limit": self.limit,
            "isLocal": self.is_local,
        }
        if self.sort:
            payload["sort"] = self.sort
        return SearchPayload.with_identity(
            payload,
            alexa_user_id=self.alexa_user_id,
            listener_id=self.listener_id,
        )
