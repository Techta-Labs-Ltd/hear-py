from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from src.constants.discovery import DiscoveryConstants
from src.constants.search import SearchConstants
from src.utils.filters import SearchFilters, SearchFilterUtils


class SearchPayload:
    @staticmethod
    def _spoken_date(value: datetime, include_year: bool = True) -> str:
        label = f"{value.day} {value.strftime('%B')}"
        return f"{label} {value.year}" if include_year else label

    @staticmethod
    def _published_range(start: datetime, end: datetime) -> str:
        if end <= start:
            return ""
        if end - start <= timedelta(days=1):
            return f"on {SearchPayload._spoken_date(start)}"
        next_month = (
            start.replace(year=start.year + 1, month=1)
            if start.month == 12
            else start.replace(month=start.month + 1)
        )
        if start.day == 1 and end.day == 1 and end == next_month:
            return f"in {start.strftime('%B %Y')}"
        last_day = end - timedelta(days=1)
        if start.year == last_day.year:
            start_label = SearchPayload._spoken_date(start, include_year=False)
            return f"from {start_label} to {SearchPayload._spoken_date(last_day)}"
        return f"from {SearchPayload._spoken_date(start)} to {SearchPayload._spoken_date(last_day)}"

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
        search_plan_candidate = slots.get("searchPlan")
        search_plan: dict = (
            search_plan_candidate if isinstance(search_plan_candidate, dict) else {}
        )
        filters_candidate = search_plan.get("filter")
        filters: dict = filters_candidate if isinstance(filters_candidate, dict) else {}
        start_value = filters.get("publishedFrom", search_plan.get("publishedFrom"))
        end_value = filters.get("publishedTo", search_plan.get("publishedTo"))
        if not isinstance(start_value, (int, float)) or not isinstance(end_value, (int, float)):
            return ""
        try:
            start = datetime.fromtimestamp(start_value, timezone.utc)
            end = datetime.fromtimestamp(end_value, timezone.utc)
        except (OSError, OverflowError, ValueError):
            return ""
        return SearchPayload._published_range(start, end)

    @staticmethod
    def _request_facets(slots: dict) -> tuple[list[str], str, str]:
        category = str(slots.get("category") or "").strip()
        tags = [
            str(tag).strip().replace("-", " ")
            for tag in slots.get("tags") or []
            if str(tag or "").strip()
        ]
        facets = list(dict.fromkeys(([category.replace("-", " ")] if category else []) + tags))
        residual = SearchFilterUtils.residual_without_conflicting_source(slots)
        if residual:
            facets.append(residual)
        return facets, category, residual

    @staticmethod
    def resolved_request_label(slots: dict, source_name: str | None = None) -> str:
        facets, category, residual = SearchPayload._request_facets(slots)
        if category and residual:
            subject = f"{' and '.join(facets[:-1])} {residual}"
        else:
            subject = " and ".join(facets) or (
                "publication" if slots.get("isPublication") else "content"
            )
        if slots.get("latest"):
            subject = f"the latest {subject}"
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
        if publication:
            generic = {"content", "the latest content", "publication", "the latest publication"}
            if not facets and subject in generic:
                subject = f"the latest {publication}" if slots.get("latest") else publication
            else:
                subject = f"{subject} from {publication}"
        city = str(slots.get("city") or slots.get("placeName") or "").strip()
        if city:
            subject = f"{subject} in {city}"
        elif slots.get("isLocal"):
            subject = f"{subject} from your community"
        published_period = SearchPayload._published_period_label(slots)
        return f"{subject} published {published_period}" if published_period else subject

    @staticmethod
    def discovery_context(
        source: object,
        payload: dict | None,
        label: object,
        items: list | None = None,
    ) -> dict:
        source_name = str(source or "search").strip()
        lowered = source_name.casefold()
        filter_candidate = payload.get("filter") if isinstance(payload, dict) else None
        filters: dict = filter_candidate if isinstance(filter_candidate, dict) else {}
        kind = (
            "publication"
            if "publication" in lowered or filters.get("publicationIds")
            else "organization"
            if "organization" in lowered or filters.get("organizationIds")
            else "creator"
            if "creator" in lowered or filters.get("creatorIds")
            else "location"
            if "local" in lowered
            or filters.get("city")
            or filters.get("latitude") is not None
            or filters.get("longitude") is not None
            or filters.get("isLocal")
            else "topic"
        )
        first: dict = next((item for item in items or [] if isinstance(item, dict)), {})
        raw_label = " ".join(str(label or "").strip().split())
        if kind == "publication":
            name = first.get("publicationTitle") or raw_label
        elif kind == "organization":
            name = first.get("organizationName") or raw_label
        elif kind == "creator":
            name = first.get("creatorName") or raw_label
        elif kind == "location":
            name = str(filters.get("city") or raw_label).strip()
        else:
            name = raw_label or str((payload or {}).get("query") or "").strip()
            if not name:
                values = filters.get("categorySlugs") or filters.get("tags") or []
                values = values if isinstance(values, list) else [values]
                name = " and ".join(
                    str(value).strip().replace("-", " ")
                    for value in values
                    if str(value or "").strip()
                )
            if not name:
                name = str(filters.get("city") or "").strip()
                kind = "location" if name else kind
        return {
            "kind": kind,
            "name": str(name or "content").strip(),
            "source": source_name,
            "searchPayload": dict(payload or {}),
        }

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
        selected = {
            "query": "",
            "filter": {"publicationIds": values},
            "limit": normalized["limit"],
            "page": 0,
        }
        if normalized.get("resolutionId"):
            selected["resolutionId"] = normalized["resolutionId"]
        return selected

    @classmethod
    def from_resolution(cls, resolution: dict, default_limit: int) -> dict:
        payload = cls.with_pagination(resolution.get("searchPayload"), default_limit)
        payload["limit"] = max(1, int(default_limit))
        if resolution.get("intent") != "publication":
            return payload
        filter_candidate = payload.get("filter")
        filters: dict = filter_candidate if isinstance(filter_candidate, dict) else {}
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
        if slots.get("isLocal"):
            filters["isLocal"] = True
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
        return {
            key: value
            for key, value in SearchFilters.clean(nlp_filter).items()
            # These flags are opt-in search constraints.  Sending ``false`` is
            # not equivalent to leaving the constraint out on /search.
            if not (key in {"isPublication", "isLocal"} and value is False)
        }

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
            "limit": options.get("limit", DiscoveryConstants.CHOICE_PAGE_SIZE),
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
