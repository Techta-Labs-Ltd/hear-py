from __future__ import annotations

from urllib.parse import urlparse

from src.utils.content import ContentIdentity, ContentUtils


class ContentNormalizer:
    @staticmethod
    def publication_choices(items: object) -> list[dict]:
        if not isinstance(items, list):
            return []
        choices = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            tracks = item.get("tracks")
            is_publication = bool(
                item.get("isPublication")
                or item.get("type") == "publication"
                or (item.get("publicationId") and isinstance(tracks, list))
            )
            publication_id = ContentUtils.nullable_string(item.get("publicationId"))
            title = ContentUtils.repair_mojibake(
                item.get("publicationTitle") or item.get("title")
            )
            key = str(publication_id or "").casefold()
            if not is_publication or not publication_id or not title or key in seen:
                continue
            seen.add(key)
            choices.append(
                {"type": "publication", "id": publication_id, "name": str(title).strip()}
            )
        return choices

    @staticmethod
    def _pick_playback_speeds(item: dict) -> list | None:
        if isinstance(item.get("playbackSpeeds"), list) and item["playbackSpeeds"]:
            return item["playbackSpeeds"]
        if isinstance(item.get("playback_speed"), list) and item["playback_speed"]:
            return item["playback_speed"]
        if isinstance(item.get("playbackSpeed"), list) and item["playbackSpeed"]:
            return item["playbackSpeed"]
        return None

    @staticmethod
    def _pick_duration_secs(source: dict) -> int | None:
        if not isinstance(source, dict):
            return None
        for key in ("durationSecs", "duration_secs"):
            v = source.get(key)
            if isinstance(v, (int, float)) and v > 0:
                return int(v)
        return None

    @staticmethod
    def _extract_named_entity(item: dict, key: str) -> tuple[str | None, str | None]:
        value = item.get(key)
        if isinstance(value, dict):
            return (
                ContentUtils.nullable_string(value.get("id")),
                ContentUtils.nullable_string(value.get("name")),
            )
        return (
            ContentUtils.nullable_string(item.get(f"{key}Id")),
            ContentUtils.nullable_string(value)
            or ContentUtils.nullable_string(item.get(f"{key}Name")),
        )

    @staticmethod
    def _category_value(item: dict):
        category = item.get("category")
        if category:
            return category
        categories = item.get("categories")
        return categories[0] if isinstance(categories, list) and categories else None

    @staticmethod
    def _is_https_url(value: object) -> bool:
        if not isinstance(value, str) or not value.strip():
            return False
        parsed = urlparse(value.strip())
        return parsed.scheme == "https" and bool(parsed.netloc)

    @staticmethod
    def normalize_content_item(item: dict) -> dict:
        if not isinstance(item, dict):
            return item
        content_id = ContentUtils.nullable_string(item.get("contentId"))
        creator_id, creator_name = ContentNormalizer._extract_named_entity(item, "creator")
        organization_id, organization_name = ContentNormalizer._extract_named_entity(
            item, "organization"
        )
        publication_id, publication_title = ContentNormalizer._extract_named_entity(
            item, "publication"
        )
        is_publication = bool(
            publication_id
            or item.get("isPublication")
            or item.get("type") == "publication"
        )
        publication_id = (
            ContentUtils.nullable_string(item.get("publicationId"))
            or publication_id
            or (content_id if is_publication else None)
        )
        publication_title = (
            ContentUtils.repair_mojibake(item.get("publicationTitle"))
            or publication_title
            or (
                ContentUtils.repair_mojibake(item.get("title"))
                if is_publication and publication_id == content_id
                else None
            )
        )
        duration_secs = ContentNormalizer._pick_duration_secs(item)
        normalized = {
            "contentId": content_id,
            "title": ContentUtils.repair_mojibake(item.get("title")),
            "displayTitle": ContentUtils.repair_mojibake(ContentUtils._pick_display_title(item)),
            "spokenTitle": ContentUtils.repair_mojibake(ContentUtils.pick_spoken_title(item)),
            "summary": ContentUtils.pick_summary(item),
            "creatorId": creator_id,
            "creatorName": creator_name,
            "creator": creator_name,
            "organizationId": organization_id,
            "organizationName": organization_name,
            "publicationId": publication_id,
            "publicationTitle": publication_title,
            "type": item.get("type"),
            "isPublication": is_publication,
            "trackIndex": item.get("trackIndex"),
            "trackCount": item.get("trackCount"),
            "category": ContentNormalizer._category_value(item),
            "tags": item.get("tags") if isinstance(item.get("tags"), list) else [],
            "audioUrl": ContentUtils.nullable_string(item.get("audioUrl")),
            "playbackSpeeds": ContentNormalizer._pick_playback_speeds(item) or [],
            "durationMs": duration_secs * 1000 if duration_secs else None,
            "publishedAt": item.get("publishedAt"),
        }
        normalized["subjectType"] = ContentIdentity.subject_type(normalized)
        normalized["subjectId"] = ContentIdentity.subject_id(normalized)
        return normalized

    @staticmethod
    def is_playable_content_item(item: dict) -> bool:
        """Return whether an item has a content ID and Alexa-compatible audio."""
        return bool(
            isinstance(item, dict)
            and item.get("contentId")
            and ContentNormalizer._is_https_url(item.get("audioUrl"))
        )

    @staticmethod
    def normalize_content_items(items) -> list:
        """Normalize a list of raw content items, dropping any that are not
        playable (e.g. a publication that came back with no tracks)."""
        if not isinstance(items, list):
            return []
        expanded = []
        for item in items:
            if not isinstance(item, dict):
                continue
            tracks = item.get("tracks")
            is_publication = bool(
                item.get("isPublication")
                or item.get("type") == "publication"
                or (item.get("publicationId") and isinstance(tracks, list))
            )
            if not is_publication or not isinstance(tracks, list) or (not tracks):
                expanded.append(item)
                continue
            publication_id = ContentUtils.nullable_string(
                item.get("publicationId")
            ) or ContentUtils.nullable_string(item.get("contentId"))
            publication_title = ContentUtils.repair_mojibake(item.get("title"))
            track_count = int(item.get("trackCount") or len(tracks))
            for index, track in enumerate(tracks):
                if not isinstance(track, dict):
                    continue
                merged = dict(item)
                merged.pop("tracks", None)
                merged.pop("durationSecs", None)
                merged.pop("duration_secs", None)
                merged.update(track)
                merged.update(
                    {
                        "publicationId": publication_id,
                        "publicationTitle": publication_title,
                        "type": "publication_track",
                        "isPublication": True,
                        "trackIndex": index,
                        "trackCount": track_count,
                    }
                )
                expanded.append(merged)
        normalized = (ContentNormalizer.normalize_content_item(item) for item in expanded)
        return [i for i in normalized if ContentNormalizer.is_playable_content_item(i)]

    @staticmethod
    def apply_search_context(
        items: list,
        search_payload: dict | None,
        response_data: dict | None = None,
    ) -> list:
        payload = search_payload if isinstance(search_payload, dict) else {}
        filters = payload.get("filter") if isinstance(payload.get("filter"), dict) else {}
        response = response_data if isinstance(response_data, dict) else {}
        raw_publication_ids = filters.get("publicationIds") or []
        if isinstance(raw_publication_ids, str):
            raw_publication_ids = [raw_publication_ids]
        publication_ids = [
            str(value).strip()
            for value in raw_publication_ids
            if str(value or "").strip()
        ]
        publication_only = bool(filters.get("isPublication"))
        total = response.get("total")
        total = int(total) if isinstance(total, (int, float)) and total > 0 else None
        page = max(0, int(response.get("page") or payload.get("page") or 0))
        limit = max(
            1,
            int(response.get("limit") or payload.get("limit") or len(items or []) or 1),
        )
        contextualized = []
        for index, item in enumerate(items or []):
            if not isinstance(item, dict):
                continue
            content = dict(item)
            if len(publication_ids) == 1:
                content["publicationId"] = content.get("publicationId") or publication_ids[0]
                content["isPublication"] = True
                content["type"] = content.get("type") or "publication_track"
                content["trackIndex"] = content.get("trackIndex")
                if content["trackIndex"] is None:
                    content["trackIndex"] = page * limit + index
                content["trackCount"] = content.get("trackCount") or total
            elif content.get("contentId") in publication_ids:
                content["publicationId"] = content.get("publicationId") or content.get(
                    "contentId"
                )
                content["isPublication"] = True
            elif publication_only:
                content["publicationId"] = content.get("publicationId") or content.get("contentId")
                content["isPublication"] = True
            if (
                content.get("isPublication")
                and not content.get("publicationTitle")
                and content.get("publicationId") == content.get("contentId")
            ):
                content["publicationTitle"] = content.get("title")
            contextualized.append(content)
        return contextualized
