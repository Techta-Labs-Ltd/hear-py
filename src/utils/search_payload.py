from __future__ import annotations

from src.constants.search import SearchConstants
from src.utils.filters import SearchFilters, SearchFilterUtils


class SearchPayload:
    @staticmethod
    def selected_resolution(nlp: dict | None) -> dict:
        source = nlp if isinstance(nlp, dict) else {}
        payload = source.get("searchPayload")
        return (
            dict(payload)
            if source.get("ambiguityResolution") and isinstance(payload, dict)
            else {}
        )

    @classmethod
    def for_publication(
        cls, payload: dict | None, publication_ids: object, default_limit: int
    ) -> dict:
        normalized = cls.with_pagination(payload, default_limit)
        candidates = (
            publication_ids
            if isinstance(publication_ids, (list, tuple, set))
            else [publication_ids]
        )
        values = [
            str(value).strip()
            for value in candidates
            if str(value or "").strip()
        ]
        if len(values) != 1:
            return normalized
        return {
            "query": "",
            "filter": {"publicationIds": values},
            "limit": normalized["limit"],
            "page": 0,
        }

    @classmethod
    def from_resolution(cls, resolution: dict, default_limit: int) -> dict:
        payload = cls.with_pagination(resolution.get("searchPayload"), default_limit)
        if resolution.get("intent") != "publication":
            return payload
        filters = payload.get("filter") if isinstance(payload.get("filter"), dict) else {}
        return cls.for_publication(payload, filters.get("publicationIds"), default_limit)

    @staticmethod
    def with_pagination(payload: dict | None, default_limit: int) -> dict:
        normalized = SearchFilterUtils.normalize_search_payload(payload)
        try:
            limit = int(normalized.get("limit") or default_limit)
        except (TypeError, ValueError):
            limit = int(default_limit)
        try:
            page = int(normalized.get("page") or 0)
        except (TypeError, ValueError):
            page = 0
        normalized.update({"limit": max(1, limit), "page": max(0, page)})
        return normalized

    @staticmethod
    def resolution_filter(
        slots: dict, option_filter: dict | None = None, is_publication: bool = False
    ) -> dict:
        filters = SearchFilters.clean(option_filter)
        filters.update(
            {
                key: list(slots[key])
                for key in ("creatorIds", "organizationIds", "publicationIds", "tags")
                if isinstance(slots.get(key), list) and slots[key]
            }
        )
        categories = slots.get("categorySlugs")
        if isinstance(categories, list) and categories:
            filters["categorySlugs"] = [
                str(value).strip() for value in categories if str(value).strip()
            ]
        elif slots.get("category"):
            filters["categorySlugs"] = [str(slots["category"]).strip()]
        city = slots.get("city") or slots.get("placeName")
        if city:
            filters["city"] = str(city).strip()
        filters.update(
            {key: slots[key] for key in ("latitude", "longitude") if slots.get(key) is not None}
        )
        filters["isLocal"] = bool(slots.get("isLocal"))
        filters["isRecommended"] = bool(slots.get("isRecommended"))
        search_plan = slots.get("searchPlan") or {}
        search_plan_filter = search_plan.get("filter") or {}
        if slots.get("isPublication") or search_plan_filter.get("isPublication") or is_publication:
            filters["isPublication"] = True
        filters.update(
            {
                key: value
                for key in ("publishedFrom", "publishedTo")
                if (value := search_plan_filter.get(key, search_plan.get(key))) is not None
            }
        )
        return filters

    @staticmethod
    def request_label(slots: dict, query: str) -> str | None:
        category = str(slots.get("category") or "").strip().replace("-", " ")
        tags = [
            str(value).strip().replace("-", " ")
            for value in slots.get("tags") or []
            if str(value).strip()
        ]
        facet = category or " and ".join(tags)
        source = str(
            slots.get("organizationName")
            or slots.get("creatorName")
            or slots.get("publicationName")
            or ""
        ).strip()
        if facet and source:
            return f"{facet} from {source}"
        return facet or source or query or None

    @staticmethod
    def _filter_object(nlp_filter: dict | None) -> dict:
        return SearchFilters.clean(nlp_filter)

    @classmethod
    def to_dict(cls, alexa_user_id: str | None, store: dict | None, options: dict) -> dict:
        nlp_filter = options.get("nlp_filter")
        filter_obj = cls._filter_object(nlp_filter)
        is_local = bool((nlp_filter or {}).get("isLocal"))
        if is_local:
            requested_city = str(filter_obj.get("city") or "").strip()
            saved_city = str(
                (store or {}).get("userCity") or (store or {}).get("locality") or ""
            ).strip()
            if not requested_city and saved_city:
                requested_city = saved_city
                filter_obj["city"] = saved_city
            uses_saved_location = not requested_city or (
                saved_city and requested_city.casefold() == saved_city.casefold()
            )
            if uses_saved_location:
                for key in ("latitude", "longitude"):
                    if filter_obj.get(key) is None and (store or {}).get(key) is not None:
                        filter_obj[key] = (store or {})[key]
        payload = {
            "alexaUserId": alexa_user_id,
            "query": SearchFilterUtils.normalize_search_query(options.get("q", "")),
            "isLocal": is_local,
            "isRecommended": bool((nlp_filter or {}).get("isRecommended")),
            "limit": options.get("limit", 5),
            "page": options.get("page", 0),
        }
        if (store or {}).get("listenerId"):
            payload["listenerId"] = (store or {})["listenerId"]
        sort = options.get("sort")
        if sort in SearchConstants.ALLOWED_SEARCH_SORTS:
            payload["sort"] = sort
        elif is_local:
            payload["sort"] = "nearest"
        if filter_obj:
            payload["filter"] = filter_obj
        return payload

    @classmethod
    def build(cls, alexa_user_id: str | None, store: dict | None = None, **kwargs) -> dict:
        return cls.to_dict(alexa_user_id, store, kwargs)

    @staticmethod
    def with_identity(
        payload: dict,
        *,
        alexa_user_id: str | None,
        listener_id: str | None,
    ) -> dict:
        identified = dict(payload)
        if alexa_user_id:
            identified["alexaUserId"] = alexa_user_id
        if listener_id:
            identified["listenerId"] = listener_id
        return identified
