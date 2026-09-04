from __future__ import annotations

from datetime import datetime, timezone

from src.constants.availability import AvailabilityConstants
from src.constants.discovery import DiscoveryConstants
from src.constants.search import SearchConstants
from src.models.dialog import DialogSelection
from src.utils.content import ContentIdentity, ContentUtils


class AvailabilityData:
    @staticmethod
    def _has_value(value: object) -> bool:
        if value is None or value is False:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, tuple, set, dict)):
            return bool(value)
        return True

    @staticmethod
    def request_scope(payload: dict) -> str | None:
        source_keys = frozenset(
            SearchConstants.SEARCH_SOURCE_FILTERS[item]
            for item in ("organization", "creator")
        )
        allowed_keys = source_keys | AvailabilityConstants.LOCATION_FILTER_KEYS
        filters = payload.get("filter") if isinstance(payload.get("filter"), dict) else {}
        active_keys = {
            key for key, value in filters.items() if AvailabilityData._has_value(value)
        }
        if active_keys - allowed_keys or str(payload.get("query") or "").strip():
            return None
        source_count = sum(
            len(value if isinstance(value, list) else [value])
            for key in source_keys
            if AvailabilityData._has_value(value := filters.get(key))
        )
        if source_count > 1 or payload.get("isRecommended"):
            return None
        if source_count == 1:
            return None if payload.get("sort") else AvailabilityConstants.SOURCE_KIND
        if active_keys & AvailabilityConstants.LOCATION_FILTER_KEYS or payload.get("isLocal"):
            return AvailabilityConstants.LOCATION_KIND
        return None

    @staticmethod
    def clean_source_name(label: str) -> str:
        value = str(label or "").strip()
        for prefix in (
            "the latest recordings from ",
            "the latest content from ",
            "content from ",
        ):
            if value.casefold().startswith(prefix):
                return value[len(prefix) :].strip()
        return value or "that source"

    @staticmethod
    def source_from_resolution(resolution: dict) -> dict | None:
        payload = resolution.get("searchPayload") or {}
        if AvailabilityData.request_scope(payload) != AvailabilityConstants.SOURCE_KIND:
            return None
        filters = payload.get("filter") if isinstance(payload.get("filter"), dict) else {}
        found = []
        for entity_type in ("organization", "creator"):
            key = SearchConstants.SEARCH_SOURCE_FILTERS[entity_type]
            values = filters.get(key) or []
            values = values if isinstance(values, list) else [values]
            for value in values:
                source_id = str(value or "").strip()
                if source_id:
                    found.append((entity_type, source_id))
        if len(found) != 1:
            return None
        entity_type, source_id = found[0]
        entity = next(
            (
                item
                for item in resolution.get("resolvedEntities") or []
                if str(item.get("type") or item.get("entityType") or "") == entity_type
                and str(item.get("id") or item.get("entityId") or "") == source_id
            ),
            {},
        )
        name = str(
            entity.get("canonicalValue")
            or entity.get("name")
            or AvailabilityData.clean_source_name(resolution.get("confirmationLabel") or "")
        ).strip()
        return {"type": entity_type, "id": source_id, "name": name or "that source"}

    @staticmethod
    def location_from_payload(payload: dict, store: dict) -> dict:
        filters = payload.get("filter") if isinstance(payload.get("filter"), dict) else {}
        requested_city = str(filters.get("city") or "").strip()
        saved_city = str(store.get("userCity") or store.get("locality") or "").strip()
        city = requested_city or saved_city
        uses_saved_location = not requested_city or (
            saved_city and requested_city.casefold() == saved_city.casefold()
        )
        location = {}
        if city:
            location["city"] = city
        country_code = filters.get("countryCode")
        if country_code is not None:
            location["countryCode"] = country_code
        for key in ("latitude", "longitude"):
            value = filters.get(key)
            if value is None and uses_saved_location:
                value = store.get(key)
            if value is not None:
                location[key] = value
        return location

    @staticmethod
    def has_location_payload(payload: dict) -> bool:
        filters = payload.get("filter") if isinstance(payload.get("filter"), dict) else {}
        return bool(
            payload.get("isLocal")
            or filters.get("city")
            or filters.get("latitude") is not None
            or filters.get("longitude") is not None
        )

    @staticmethod
    def source_candidates(result: dict) -> list[dict]:
        combined = list(result.get("organizations") or []) + list(result.get("creators") or [])
        unique = []
        names: set[str] = set()
        for candidate in combined:
            name = str(candidate.get("name") or "").strip()
            key = DialogSelection.normalize(name)
            if not name or key in names:
                continue
            names.add(key)
            unique.append(dict(candidate))
        return unique

    @staticmethod
    def day_label(day: int) -> str:
        labels = (
            "",
            "first",
            "second",
            "third",
            "fourth",
            "fifth",
            "sixth",
            "seventh",
            "eighth",
            "ninth",
            "tenth",
            "eleventh",
            "twelfth",
            "thirteenth",
            "fourteenth",
            "fifteenth",
            "sixteenth",
            "seventeenth",
            "eighteenth",
            "nineteenth",
            "twentieth",
            "twenty-first",
            "twenty-second",
            "twenty-third",
            "twenty-fourth",
            "twenty-fifth",
            "twenty-sixth",
            "twenty-seventh",
            "twenty-eighth",
            "twenty-ninth",
            "thirtieth",
            "thirty-first",
        )
        return labels[day] if 0 < day < len(labels) else str(day)

    @staticmethod
    def publication_candidates(result: dict) -> list[dict]:
        candidates = []
        for item in result.get("publications") or []:
            candidate = dict(item)
            title = str(candidate.get("name") or "").strip()
            try:
                published = datetime.fromtimestamp(
                    float(candidate.get("publishedAt")), timezone.utc
                )
            except (OSError, OverflowError, TypeError, ValueError):
                published = None
            if published and published.strftime("%B").casefold() not in title.casefold():
                title = (
                    f"{title} for the {AvailabilityData.day_label(published.day)} "
                    f"of {published.strftime('%B')}"
                )
            candidate["name"] = title
            candidates.append(candidate)
        return candidates

    @staticmethod
    def track_candidates(result: dict) -> list[dict]:
        candidates = []
        for item in result.get("results") or []:
            content_id = ContentIdentity.content_id(item)
            title = ContentUtils.content_title_for_speech(item)
            if content_id and title:
                candidates.append({"type": "track", "id": content_id, "name": title})
        return DialogSelection.unique_candidates(candidates)

    @staticmethod
    def search_total_pages(result: dict) -> int:
        try:
            supplied = max(0, int(result.get("total_pages") or 0))
            total = max(0, int(result.get("total_hits") or 0))
        except (TypeError, ValueError):
            return 0
        return supplied or (
            (total + DiscoveryConstants.CHOICE_PAGE_SIZE - 1)
            // DiscoveryConstants.CHOICE_PAGE_SIZE
        )

    @staticmethod
    def displayed(context: dict) -> list[dict]:
        candidates = list(context.get("candidates") or [])
        offset = max(0, int(context.get("offset") or 0))
        return candidates[offset : offset + DiscoveryConstants.CHOICE_PAGE_SIZE]

    @staticmethod
    def remote_more(context: dict) -> bool:
        current_page = max(0, int(context.get("apiPage") or 0))
        total_pages = max(0, int(context.get("totalPages") or 0))
        return bool(context.get("hasMore") or (total_pages and current_page + 1 < total_pages))

    @staticmethod
    def has_more(context: dict) -> bool:
        offset = max(0, int(context.get("offset") or 0))
        return bool(
            offset + DiscoveryConstants.CHOICE_PAGE_SIZE < len(context.get("candidates") or [])
            or AvailabilityData.remote_more(context)
        )
