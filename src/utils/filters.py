from __future__ import annotations

import re
from difflib import SequenceMatcher
from numbers import Real

from src.constants.creator import CreatorConstants
from src.constants.discovery import DiscoveryConstants
from src.constants.organization import OrganizationConstants
from src.constants.search import SearchConstants


class SearchFilterUtils:
    SOURCE_DESCRIPTOR_WORDS = frozenset(
        {
            "a",
            "an",
            "and",
            "audio",
            "by",
            "creator",
            "from",
            "magazine",
            "news",
            "newspaper",
            "of",
            "organisation",
            "organization",
            "paper",
            "publication",
            "talking",
            "the",
        }
    )
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
    def source_name_signature(value: object) -> str:
        tokens = re.findall("[a-z0-9]+", SearchFilterUtils.normalize_discovery_phrase(value))
        distinctive = [
            token for token in tokens if token not in SearchFilterUtils.SOURCE_DESCRIPTOR_WORDS
        ]
        return " ".join(distinctive or tokens)

    @staticmethod
    def is_plausible_source_match(requested: object, canonical: object) -> bool:
        requested_name = SearchFilterUtils.source_name_signature(requested)
        canonical_name = SearchFilterUtils.source_name_signature(canonical)
        if not requested_name or not canonical_name:
            return False
        if requested_name == canonical_name:
            return True
        if requested_name in canonical_name or canonical_name in requested_name:
            return True
        requested_tokens = set(requested_name.split())
        canonical_tokens = set(canonical_name.split())
        overlap = len(requested_tokens & canonical_tokens) / max(
            1, min(len(requested_tokens), len(canonical_tokens))
        )
        if overlap >= 0.67:
            return True
        return SequenceMatcher(None, requested_name, canonical_name).ratio() >= 0.72

    @staticmethod
    def residual_without_conflicting_source(slots: dict) -> str:
        residual = str(slots.get("residualQuery") or "").strip()
        canonical = next(
            (
                str(slots.get(name) or "").strip()
                for name in ("organizationName", "creatorName", "publicationName")
                if str(slots.get(name) or "").strip()
            ),
            "",
        )
        requested = next(
            (
                str(slots.get(name) or "").strip()
                for name in ("organizationQuery", "creatorQuery", "publicationSourceQuery")
                if str(slots.get(name) or "").strip()
            ),
            "",
        )
        requested_signature = SearchFilterUtils.source_name_signature(requested)
        residual_signature = SearchFilterUtils.source_name_signature(residual)
        conflicting = canonical and requested and not SearchFilterUtils.is_plausible_source_match(
            requested, canonical
        )
        duplicated = requested_signature and requested_signature in residual_signature
        return "" if residual and (conflicting or duplicated) else residual

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
            and not SearchFilterUtils.is_generic_creator_request(normalized)
        )

    @staticmethod
    def is_generic_creator_request(value: object) -> bool:
        normalized = SearchFilterUtils.normalize_discovery_phrase(value)
        if normalized in CreatorConstants.SOURCE_PLACEHOLDERS:
            return True
        tokens = re.findall("[a-z]+", normalized)
        has_creator_role = any(
            token in CreatorConstants.ROLE_WORDS for token in tokens
        )
        has_creator_asr = any(
            left == "create" and right == "a"
            for left, right in zip(tokens, tokens[1:])
        )
        return bool(
            tokens
            and (has_creator_role or has_creator_asr)
            and all(token in CreatorConstants.GENERIC_WORDS for token in tokens)
        )

    @staticmethod
    def extract_creator_city(value: object) -> str | None:
        if not value:
            return None
        text = SearchFilterUtils.normalize_discovery_phrase(value)
        match = re.search(r"\bcreators?\s+(?:in|from|near|around)\s+(.+)$", text)
        if not match:
            return None
        city = re.sub(r"^(?:the\s+(?:city|town)\s+of\s+|(?:city|town)\s+of\s+)", "", match.group(1).strip()).strip()
        return city or None

    @staticmethod
    def is_meaningful_organization_source(value: object) -> bool:
        return (
            SearchFilterUtils.organization_request_kind(value, organization_intent=True)
            == "specific"
        )

    @staticmethod
    def organization_request_kind(
        value: object, *, organization_intent: bool = False
    ) -> str:
        normalized = SearchFilterUtils.normalize_discovery_phrase(value)
        repair_phrase = re.sub(
            "^(?:play\\s+)?(?:something\\s+)?from\\s+(?:a\\s+|an\\s+|the\\s+)?",
            "",
            normalized,
        ).strip()
        if repair_phrase in OrganizationConstants.ASR_REPAIR_PHRASES:
            return "repair"
        if (
            normalized in OrganizationConstants.SOURCE_PLACEHOLDERS
            or repair_phrase in OrganizationConstants.SOURCE_PLACEHOLDERS
        ):
            return "generic"
        tokens = re.findall("[a-z]+", normalized)
        has_talking_newspaper = any(
            prefix in tokens for prefix in ("talking", "audio", "spoken")
        ) and any(
            word in tokens for word in ("news", "newspaper", "newspapers", "paper", "papers")
        )
        generic_talking_newspaper = bool(
            has_talking_newspaper
            and tokens
            and all((token in OrganizationConstants.GENERIC_WORDS for token in tokens))
        )
        under_specified = bool(
            organization_intent
            and (
                not tokens
                or all((token in OrganizationConstants.GENERIC_WORDS for token in tokens))
            )
        )
        return "generic" if generic_talking_newspaper or under_specified else "specific"

    @staticmethod
    def is_generic_organization_request(value: object) -> bool:
        return SearchFilterUtils.organization_request_kind(value) == "generic"


class SearchFilters:
    _LIST_KEYS = frozenset(
        {
            "contentIds",
            "creatorIds",
            "organizationIds",
            "publicationIds",
            "categorySlugs",
            "tags",
        }
    )
    _TEXT_KEYS = frozenset({"city", "countryCode"})
    _DATE_KEYS = frozenset({"publishedFrom", "publishedTo"})
    _NUMBER_KEYS = frozenset({"latitude", "longitude"})
    _BOOLEAN_KEYS = frozenset({"isPublication"})
    _AVAILABILITY_SOURCE_KEYS = ("creatorId", "organizationId")
    _AVAILABILITY_TAXONOMY_KEYS = ("categorySlugs", "tags")
    _AVAILABILITY_BOOLEAN_KEYS = ("isCreator",)
    _AVAILABILITY_LOCATION_KEYS = ("city", "countryCode", "latitude", "longitude")

    @staticmethod
    def _text_values(value: object) -> list[str]:
        candidates = value if isinstance(value, (list, tuple, set)) else [value]
        values: list[str] = []
        for candidate in candidates:
            text = str(candidate or "").strip()
            if text and text not in values:
                values.append(text)
        return values

    @staticmethod
    def clean(values: dict | None) -> dict:
        source = values if isinstance(values, dict) else {}
        normalized: dict[str, object] = {}
        for key in SearchConstants.SEARCH_FILTER_KEYS:
            value = source.get(key)
            if value is None:
                continue
            if key in SearchFilters._LIST_KEYS:
                items = SearchFilters._text_values(value)
                if items:
                    normalized[key] = items
            elif key in SearchFilters._TEXT_KEYS:
                text = str(value).strip()
                if text:
                    normalized[key] = text
            elif key in SearchFilters._DATE_KEYS:
                if isinstance(value, Real) and not isinstance(value, bool):
                    normalized[key] = value
                else:
                    text = str(value).strip()
                    if text:
                        normalized[key] = text
            elif key in SearchFilters._NUMBER_KEYS:
                if isinstance(value, Real) and not isinstance(value, bool):
                    normalized[key] = value
            elif key in SearchFilters._BOOLEAN_KEYS and isinstance(value, bool):
                normalized[key] = value
        return normalized

    @staticmethod
    def availability(values: object) -> dict | None:
        """Validate the availability endpoint's distinct filter contract."""
        if not isinstance(values, dict) or not values:
            return None
        allowed = (
            set(SearchFilters._AVAILABILITY_SOURCE_KEYS)
            | set(SearchFilters._AVAILABILITY_TAXONOMY_KEYS)
            | set(SearchFilters._AVAILABILITY_BOOLEAN_KEYS)
            | {"location"}
        )
        if any(key not in allowed for key in values):
            return None
        output: dict[str, object] = {}
        for key in SearchFilters._AVAILABILITY_SOURCE_KEYS:
            if key not in values:
                continue
            value = str(values.get(key) or "").strip()
            if not value:
                return None
            output[key] = value
        for key in SearchFilters._AVAILABILITY_TAXONOMY_KEYS:
            if key not in values:
                continue
            entries = list(
                dict.fromkeys(
                    entry.casefold()
                    for entry in SearchFilters._text_values(values[key])
                )
            )
            if not entries:
                return None
            output[key] = entries
        for key in SearchFilters._AVAILABILITY_BOOLEAN_KEYS:
            if key in values:
                if not isinstance(values[key], bool):
                    return None
                output[key] = values[key]
        if "location" in values:
            location = values["location"]
            if not isinstance(location, dict) or not location:
                return None
            if any(key not in SearchFilters._AVAILABILITY_LOCATION_KEYS for key in location):
                return None
            normalized_location: dict[str, object] = {}
            for key in SearchFilters._AVAILABILITY_LOCATION_KEYS:
                location_value: object = location.get(key)
                if location_value is None:
                    continue
                if key in {"latitude", "longitude"}:
                    if not isinstance(location_value, Real) or isinstance(location_value, bool):
                        return None
                    normalized_location[key] = location_value
                else:
                    text = str(location_value).strip()
                    if text:
                        normalized_location[key] = text
            if not normalized_location:
                return None
            output["location"] = normalized_location
        return output or None

    @staticmethod
    def content(content_id: object) -> dict:
        value = str(content_id or "").strip()
        return {"contentIds": [value]} if value else {}

    @staticmethod
    def content_ids(content_ids: object) -> dict:
        candidates = content_ids if isinstance(content_ids, (list, tuple, set)) else []
        values = [
            str(content_id).strip()
            for content_id in candidates
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
