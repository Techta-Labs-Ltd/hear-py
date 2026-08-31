from __future__ import annotations

import re

from src.constants.discovery import DiscoveryConstants
from src.constants.search import SearchConstants


class SearchFilterUtils:
    STRIP_PATTERNS = [
        re.compile(p, re.I)
        for p in [
            "^do\\s+(?:you|we)\\s+have\\s+(?:anything\\s+)?(?:on|about|from|by)\\s+",
            "^anything\\s+(?:on|about|from|by)\\s+",
            "^something\\s+(?:on|about|from|by)\\s+",
            "^anything\\s+(?:on|about|from|by)\\s*$",
            "^something\\s+(?:on|about|from|by)\\s*$",
            "^content\\s+(?:on|about|from|by)\\s+",
            "^content\\s+(?:on|about|from|by)\\s*$",
            "^recordings\\s+(?:on|about|from|by)\\s+",
            "^(?:some|the)\\s+(?:content|recordings|audio)\\s+(?:on|about|from|by)\\s+",
            "^find\\s+(?:me\\s+)?(?:something\\s+)?(?:on|about|from|by)\\s+",
            "^find\\s+(?:me\\s+)?(?:content|recordings|audio)\\s+(?:on|about)\\s+",
            "^do\\s+(?:you|we)\\s+have\\s+",
            "^(?:can|could)\\s+(?:you|we)\\s+(?:find|show|tell|get|play|read)\\s+(?:me\\s+)?(?:something\\s+)?(?:on|about|from|by)\\s+",
            "^(?:can|could)\\s+(?:you|we)\\s+(?:find|show|tell|get|play|read)\\s+(?:me\\s+)?",
            "^tell\\s+(?:me|us)\\s+(?:something\\s+)?(?:on|about|from|by)\\s+",
            "^tell\\s+(?:me|us)\\s+",
            "^(?:i\\s+)?want\\s+(?:to\\s+)?(?:hear|listen\\s+to|find|play|get|know|learn)\\s+(?:something\\s+)?(?:on|about|from|by)\\s+",
            "^(?:i\\s+)?want\\s+(?:to\\s+)?(?:hear|listen\\s+to|find|play|get|know|learn)\\s+",
            "^(?:i\\s+)?want\\s+(?:something\\s+)?(?:on|about|from|by)\\s+",
            "^(?:i\\s+)?want\\s+",
            "^(?:i\\s+wanted|id\\s+like|i'd\\s+like|i\\s+would\\s+like)\\s+(?:to\\s+)?(?:hear|listen\\s+to|find|play|get)\\s+(?:something\\s+)?(?:on|about|from|by)\\s+",
            "^(?:i\\s+wanted|id\\s+like|i'd\\s+like|i\\s+would\\s+like)\\s+(?:to\\s+)?(?:hear|listen\\s+to|find|play|get)\\s+",
            "^(?:i\\s+wanted|id\\s+like|i'd\\s+like|i\\s+would\\s+like)\\s+(?:to\\s+)?",
            "^play\\s+(?:me\\s+)?(?:the\\s+)?(?:latest|newest|most\\s+recent|recent)\\s+",
            "^play\\s+(?:me\\s+)?(?:some\\s+)?(?:on|about|from|by)\\s+",
            "^play\\s+(?:me\\s+)?",
            "^give\\s+(?:me|us)\\s+(?:something\\s+)?(?:on|about|from|by)\\s+",
            "^give\\s+(?:me|us)\\s+",
            "^(?:read|show|get)\\s+(?:me|us)\\s+(?:something\\s+)?(?:on|about|from|by)\\s+",
            "^(?:read|show|get)\\s+(?:me|us)\\s+",
            "^(?:let\\s+)?me\\s+(?:hear|listen\\s+to|find|discover|get)\\s+(?:something\\s+)?(?:on|about|from|by)\\s+",
            "^(?:let\\s+)?me\\s+(?:hear|listen\\s+to|find|discover|get)\\s+",
            "^what\\s+(?:do|can|about)\\s+(?:you|we)\\s+(?:have|got|find|show|tell|play)\\s+(?:on|about|from|by)\\s+",
            "^what\\s+(?:do|can)\\s+(?:you|we)\\s+(?:have|got|find|show|tell)\\s+",
            "^what\\s+(?:else\\s+)?(?:do|can)\\s+(?:you|we)\\s+have\\s+",
            "^i\\s+(?:need|love)\\s+(?:to\\s+)?",
            "^start\\s+(?:playing\\s+|my\\s+daily\\s+listen\\s+|something\\s+)?",
            "^listen\\s+",
            "^from\\s+",
        ]
    ]

    @staticmethod
    def normalize_search_query(value: object) -> str:
        return "" if value is None else str(value)

    @staticmethod
    def normalize_search_payload(payload: dict | None) -> dict:
        normalized = dict(payload) if isinstance(payload, dict) else {}
        query = normalized.get("query")
        normalized["query"] = SearchFilterUtils.normalize_search_query(
            query if query is not None else normalized.get("q")
        )
        normalized.pop("q", None)
        if normalized.get("sort") not in SearchConstants.ALLOWED_SEARCH_SORTS:
            normalized.pop("sort", None)
        if isinstance(normalized.get("filter"), dict):
            normalized["filter"] = SearchFilters.clean(normalized["filter"])
        return normalized

    @staticmethod
    def strip_conversational_topic_prefix(raw) -> str:
        q = str(raw or "").strip()
        if not q:
            return ""
        for pattern in SearchFilterUtils.STRIP_PATTERNS:
            stripped = pattern.sub("", q).strip()
            if stripped == "":
                return ""
            if stripped != q:
                return stripped
        return q

    @staticmethod
    def strip_search_sort_prefix(raw: object) -> str:
        return re.sub(
            "^(?:the\\s+)?(?:latest|newest|most\\s+recent|recent)\\s+",
            "",
            str(raw or "").strip(),
            flags=re.I,
        ).strip()

    @staticmethod
    def _normalize_search_query_for_creator(raw) -> str:
        q = str(raw or "").strip()
        if not q:
            return ""
        q = re.sub("^(the\\s+)?", "", q, flags=re.I)
        q = re.sub(
            "^(latest|newest|most\\s+recent)\\s+(recording|recordings|episode|episodes|podcast|podcasts|show|shows|audio|clip|clips|content)\\s+(from|by)\\s+",
            "",
            q,
            flags=re.I,
        )
        q = re.sub("^(latest|newest|most\\s+recent)\\s+(from|by)\\s+", "", q, flags=re.I)
        q = re.sub(
            "^(a\\s+)?(recording|recordings|episode|episodes|podcast|podcasts|show|shows|audio|clip|clips|content)\\s+(from|by)\\s+",
            "",
            q,
            flags=re.I,
        )
        q = re.sub("\\s+(latest|newest|most\\s+recent)$", "", q, flags=re.I)
        return q.strip() or str(raw).strip()

    @staticmethod
    def parse_topic_for_search(raw: str) -> dict:
        q = SearchFilterUtils.strip_conversational_topic_prefix(raw)
        if not q:
            return {"q": "", "tags": None}
        m = re.match("^(?:about|on|regarding)\\s+(.+)$", q, re.I)
        if m:
            topic = m.group(1).strip()
            return {"q": topic, "tags": [topic] if topic else None}
        return {"q": q, "tags": None}

    @staticmethod
    def wants_latest_playback(raw_query: str) -> bool:
        return bool(
            re.search("\\b(latest|newest|most\\s+recent|last)\\b", str(raw_query or ""), re.I)
        )

    @staticmethod
    def wants_local_community_content(
        search_q: str = "", topic: str = "", category: str = ""
    ) -> bool:
        q = str(search_q or topic or "").lower().strip()
        cat = str(category or "").lower().strip()
        if cat == "community":
            return True
        return bool(
            re.search(
                "\\b(near me|nearby|local|community|my area|from my area|my city|from my city|my town|from my town|around me)\\b",
                q,
            )
        )

    @staticmethod
    def wants_play_from_followed_creators(text: str = "") -> bool:
        text = str(text or "").lower().strip()
        if not text:
            return False
        if re.search("\\bplay\\s+(something\\s+)?from\\s+(my\\s+)?followed\\b", text):
            return True
        if re.search("\\bplay\\s+from\\s+(my\\s+)?followed\\s+creators?\\b", text):
            return True
        if re.search("\\bhear\\s+from\\s+(my\\s+)?followed\\b", text):
            return True
        if re.search("\\blisten\\s+to\\s+(my\\s+)?followed\\b", text):
            return True
        return bool(
            re.search("\\bfollowed\\s+creators?\\b", text)
            and re.search("\\b(play|listen|hear|something|from)\\b", text)
        )

    @staticmethod
    def normalize_discovery_phrase(value: object) -> str:
        return re.sub("\\s+", " ", str(value or "").casefold()).strip()

    @staticmethod
    def is_reserved_discovery_phrase(value: object) -> bool:
        return (
            SearchFilterUtils.normalize_discovery_phrase(value)
            in DiscoveryConstants.RESERVED_DISCOVERY_PHRASES
        )

    @staticmethod
    def is_meaningful_publication_source(value: object) -> bool:
        normalized = SearchFilterUtils.normalize_discovery_phrase(value)
        return bool(
            normalized
            and normalized not in DiscoveryConstants.RESERVED_DISCOVERY_PHRASES
            and (normalized not in DiscoveryConstants.PUBLICATION_SOURCE_PLACEHOLDERS)
        )

    @staticmethod
    def is_meaningful_creator_source(value: object) -> bool:
        normalized = SearchFilterUtils.normalize_discovery_phrase(value)
        return bool(
            normalized
            and normalized not in DiscoveryConstants.RESERVED_DISCOVERY_PHRASES
            and (normalized not in DiscoveryConstants.CREATOR_SOURCE_PLACEHOLDERS)
        )

    @staticmethod
    def is_meaningful_organization_source(value: object) -> bool:
        normalized = SearchFilterUtils.normalize_discovery_phrase(value)
        return bool(
            normalized
            and normalized not in DiscoveryConstants.RESERVED_DISCOVERY_PHRASES
            and (not SearchFilterUtils.is_generic_organization_request(normalized))
        )

    @staticmethod
    def is_generic_organization_request(value: object) -> bool:
        normalized = SearchFilterUtils.normalize_discovery_phrase(value)
        if normalized in DiscoveryConstants.ORGANIZATION_SOURCE_PLACEHOLDERS:
            return True
        tokens = re.findall("[a-z]+", normalized)
        has_talking_newspaper = "talking" in tokens and (
            "newspaper" in tokens or ("news" in tokens and "paper" in tokens)
        )
        return bool(
            has_talking_newspaper
            and tokens
            and all((token in DiscoveryConstants.GENERIC_ORGANIZATION_WORDS for token in tokens))
        )


class SearchFilters:
    @staticmethod
    def clean(values: dict | None) -> dict:
        source = values if isinstance(values, dict) else {}
        return {
            key: list(value) if key == "tags" and isinstance(value, list) else value
            for key in SearchConstants.SEARCH_FILTER_KEYS
            if (value := source.get(key)) is not None and value != "" and (value != [])
        }

    @staticmethod
    def content(content_id: object) -> dict:
        value = str(content_id or "").strip()
        return {"contentIds": [value]} if value else {}

    @staticmethod
    def content_ids(content_ids: object) -> dict:
        values = [
            str(content_id).strip()
            for content_id in content_ids or []
            if str(content_id or "").strip()
        ]
        return {"contentIds": list(dict.fromkeys(values))} if values else {}

    @staticmethod
    def source(entity_type: str, entity_id: object) -> dict:
        key = SearchConstants.SEARCH_SOURCE_FILTERS.get(str(entity_type or "").strip().casefold())
        value = str(entity_id or "").strip()
        return {key: [value]} if key and value else {}

    @classmethod
    def replace_source(cls, values: dict | None, entity_type: str, entity_id: object) -> dict:
        filters = cls.clean(values)
        for key in SearchConstants.SEARCH_SOURCE_FILTERS.values():
            filters.pop(key, None)
        filters.update(cls.source(entity_type, entity_id))
        return filters

    @classmethod
    def without(cls, values: dict | None, *keys: str) -> dict:
        filters = cls.clean(values)
        for key in keys:
            filters.pop(key, None)
        return filters
