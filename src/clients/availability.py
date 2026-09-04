from __future__ import annotations

from src.constants.discovery import DiscoveryConstants


class AvailabilityResponse:
    SOURCE_FILTER_KEYS = ("creatorId", "organizationId")
    LOCATION_FILTER_KEYS = ("city", "countryCode", "latitude", "longitude")

    @staticmethod
    def log_filter(value: dict) -> dict:
        location = value.get("location")
        if isinstance(location, dict):
            return {
                "location": {
                    "city": location.get("city"),
                    "countryCode": location.get("countryCode"),
                    "latitude": location.get("latitude"),
                    "longitude": location.get("longitude"),
                }
            }
        return {
            key: value[key]
            for key in AvailabilityResponse.SOURCE_FILTER_KEYS
            if value.get(key)
        }

    @staticmethod
    def normalize_filter(value: object) -> dict | None:
        """Accept one availability scope: one source, or one location."""
        if not isinstance(value, dict) or len(value) != 1:
            return None
        key, raw_value = next(iter(value.items()))
        if key in AvailabilityResponse.SOURCE_FILTER_KEYS:
            source_id = str(raw_value or "").strip()
            return {key: source_id} if source_id else None
        if key != "location" or not isinstance(raw_value, dict):
            return None
        if not raw_value or any(
            item not in AvailabilityResponse.LOCATION_FILTER_KEYS for item in raw_value
        ):
            return None
        location = {
            item: raw_value[item]
            for item in AvailabilityResponse.LOCATION_FILTER_KEYS
            if raw_value.get(item) is not None and str(raw_value.get(item)).strip()
        }
        return {"location": location} if location else None

    @staticmethod
    def integer(value, default: int = 0, minimum: int = 0) -> int:
        try:
            return max(minimum, int(value if value is not None else default))
        except (TypeError, ValueError):
            return max(minimum, int(default))

    @staticmethod
    def items(data: dict, key: str, item_type: str) -> list[dict]:
        items = []
        for item in data.get(key) or []:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id") or item.get(f"{item_type}Id") or "").strip()
            name = str(item.get("name") or item.get("title") or "").strip()
            if item_id and name:
                items.append({"type": item_type, "id": item_id, "name": name})
        return items

    @staticmethod
    def publications(data: dict) -> list[dict]:
        items = []
        for item in data.get("publications") or []:
            if not isinstance(item, dict):
                continue
            publication_id = str(item.get("publicationId") or item.get("id") or "").strip()
            title = str(item.get("title") or item.get("name") or "").strip()
            if publication_id and title:
                items.append(
                    {
                        "type": "publication",
                        "id": publication_id,
                        "name": title,
                        "trackCount": AvailabilityResponse.integer(item.get("trackCount")),
                        "publishedAt": item.get("publishedAt"),
                        "updatedAt": item.get("updatedAt"),
                    }
                )
        return items

    @staticmethod
    def normalize(data: dict, payload: dict) -> dict:
        publications = AvailabilityResponse.publications(data)
        publication_count = AvailabilityResponse.integer(
            data.get("publicationCount"), len(publications)
        )
        page = AvailabilityResponse.integer(data.get("page"))
        total_pages = AvailabilityResponse.integer(data.get("totalPages"))
        remaining = AvailabilityResponse.integer(data.get("remaining"))
        return {
            "page": page,
            "limit": AvailabilityResponse.integer(
                data.get("limit"),
                payload.get("limit") or DiscoveryConstants.CHOICE_PAGE_SIZE,
                1,
            ),
            "total": AvailabilityResponse.integer(data.get("total")),
            "total_pages": total_pages,
            "remaining": remaining,
            "has_more": bool(
                data.get("hasMore")
                or data.get("nextPage") is not None
                or remaining > 0
                or total_pages > 0
                and page + 1 < total_pages
            ),
            "next_page": data.get("nextPage"),
            "organizations": AvailabilityResponse.items(data, "organizations", "organization"),
            "creators": AvailabilityResponse.items(data, "creators", "creator"),
            "publications": publications,
            "publication_count": publication_count,
            "standalone_track_count": AvailabilityResponse.integer(
                data.get("standaloneTrackCount")
            ),
            "failed": False,
            "_availability_payload": dict(payload),
        }

    @staticmethod
    def failed(payload: dict) -> dict:
        return {
            "page": 0,
            "limit": AvailabilityResponse.integer(
                payload.get("limit"), DiscoveryConstants.CHOICE_PAGE_SIZE, 1
            ),
            "total": 0,
            "total_pages": 0,
            "remaining": 0,
            "has_more": False,
            "next_page": None,
            "organizations": [],
            "creators": [],
            "publications": [],
            "publication_count": 0,
            "standalone_track_count": 0,
            "failed": True,
            "_availability_payload": dict(payload),
        }
