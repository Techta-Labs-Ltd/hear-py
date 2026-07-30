from __future__ import annotations

import re

from src.utils.skill_request import get_intent_name, get_user_id


def to_slug(value) -> str | None:
    """Normalize a string into a URL-safe slug."""
    if not value:
        return None
    slug = str(value).strip().lower()
    slug = re.sub(r"['']", "", slug)
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"^-+|-+$", "", slug)
    return slug or None


def build_user_field(handler_input, store: dict | None = None) -> dict:
    """Build the user metadata object for search API payloads."""
    env = getattr(handler_input, "request_envelope", {}) or {}
    sys = (env.get("context") or {}).get("System") or {}
    store_val = store or {}
    return {
        "alexaUserId": get_user_id(handler_input),
        "deviceId": (sys.get("device") or {}).get("deviceId") or None,
        "apiEndpoint": sys.get("apiEndpoint") or None,
        "locale": (env.get("request") or {}).get("locale") or None,
        "userName": store_val.get("userName") or None,
        "fullName": store_val.get("fullName") or None,
        "givenName": store_val.get("givenName") or None,
        "userEmail": store_val.get("userEmail") or None,
        "address": store_val.get("userAddress") or None,
        "city": store_val.get("userCity") or None,
        "state": store_val.get("userState") or None,
        "country": store_val.get("userCountry") or None,
        "countryCode": store_val.get("deviceCountryCode") or None,
        "postalCode": store_val.get("devicePostalCode") or None,
        "latitude": store_val.get("latitude") if store_val.get("latitude") is not None else None,
        "longitude": store_val.get("longitude") if store_val.get("longitude") is not None else None,
        "locality": store_val.get("locality") or None,
        "clientVersion": "1.0.0",
    }


class SearchPayload:
    _FILTER_KEYS = (
        "contentIds", "creatorIds", "organizationIds", "publicationIds",
        "categorySlugs", "city", "countryCode",
    )

    def __init__(
        self,
        handler_input,
        store: dict | None = None,
        *,
        q: str = "",
        limit: int = 5,
        page: int = 0,
        sort: str | None = None,
        nlp_filter: dict | None = None,
    ):
        self.handler_input = handler_input
        self.store = store
        self.q = q
        self.limit = limit
        self.page = page
        self.sort = sort
        self.nlp_filter = nlp_filter

    def _filter_object(self) -> dict:
        f = self.nlp_filter
        if not isinstance(f, dict):
            return {}
        out: dict = {}
        for key in self._FILTER_KEYS:
            if f.get(key):
                out[key] = f[key]
        if isinstance(f.get("tags"), list) and f["tags"]:
            out["tags"] = list(f["tags"])
        return out

    def to_dict(self) -> dict:
        """Serialize to the search API payload dict.

        The search API doesn't use intent/skillIntent and no longer expects the
        user metadata object, so none of those are included.
        """
        filter_obj = self._filter_object()
        is_local = bool((self.nlp_filter or {}).get("isLocal"))
        if is_local:
            requested_city = str(filter_obj.get("city") or "").strip()
            saved_city = str(
                (self.store or {}).get("userCity")
                or (self.store or {}).get("locality")
                or ""
            ).strip()
            if not requested_city or (
                saved_city and requested_city.casefold() == saved_city.casefold()
            ):
                # Local search uses the registered listener coordinates. An
                # exact city facet can incorrectly empty that radius search.
                filter_obj.pop("city", None)
            else:
                # A different named city is an exact catalogue request, not a
                # radius search around the listener's saved coordinates.
                is_local = False

        payload = {
            "alexaUserId": get_user_id(self.handler_input),
            "query": str(self.q) if self.q is not None else "",
            "isLocal": is_local,
            "isRecommended": bool((self.nlp_filter or {}).get("isRecommended")),
            "limit": self.limit,
            "page": self.page,
        }
        if self.sort:
            payload["sort"] = self.sort
        elif is_local:
            payload["sort"] = "nearest"
        if filter_obj:
            payload["filter"] = filter_obj
        for key in ("publishedFrom", "publishedTo"):
            if isinstance((self.nlp_filter or {}).get(key), (int, float)):
                payload[key] = int(self.nlp_filter[key])
        return payload

    @classmethod
    def build(cls, handler_input, store: dict | None = None, **kwargs) -> dict:
        """Construct and serialize in one call."""
        return cls(handler_input, store, **kwargs).to_dict()


def build_search_filters(handler_input, store: dict | None = None, *, q: str = "", limit: int = 5, page: int = 0, sort: str | None = None, nlp_filter: dict | None = None) -> dict:
    """Thin wrapper around :class:`SearchPayload`; prefer the class in new code."""
    return SearchPayload(
        handler_input, store, q=q,
        limit=limit, page=page, sort=sort, nlp_filter=nlp_filter,
    ).to_dict()


def extract_slot_value(handler_input, slot_name: str) -> str:
    """Extract a slot value from the Alexa request, checking resolutions if needed."""
    try:
        slots = (handler_input.request_envelope.request.intent.get("slots") if handler_input.request_envelope.request.intent else None) or {}
        slot = slots.get(slot_name)
        if slot and slot.value is not None and str(slot.value).strip():
            return str(slot.value).strip()
        if slot:
            resolutions = slot.resolutions
            if resolutions:
                for authority in (resolutions.resolutionsPerAuthority or []):
                    values = authority.values or []
                    if values:
                        name = values[0].value.name if values[0].value else None
                        if name is not None and str(name).strip():
                            return str(name).strip()
    except Exception:
        pass
    return ""


def _extract_topic_slot(handler_input) -> str:
    topic = extract_slot_value(handler_input, "topic")
    if topic:
        return topic
    category = extract_slot_value(handler_input, "category")
    if category:
        return category
    return ""


STRIP_PATTERNS = [
    re.compile(p, re.I) for p in [
        r"^do\s+(?:you|we)\s+have\s+(?:anything\s+)?(?:on|about|from|by)\s+",
        r"^anything\s+(?:on|about|from|by)\s+",
        r"^something\s+(?:on|about|from|by)\s+",
        r"^anything\s+(?:on|about|from|by)\s*$",
        r"^something\s+(?:on|about|from|by)\s*$",
        r"^content\s+(?:on|about|from|by)\s+",
        r"^content\s+(?:on|about|from|by)\s*$",
        r"^recordings\s+(?:on|about|from|by)\s+",
        r"^(?:some|the)\s+(?:content|recordings|audio)\s+(?:on|about|from|by)\s+",
        r"^find\s+(?:me\s+)?(?:something\s+)?(?:on|about|from|by)\s+",
        r"^do\s+(?:you|we)\s+have\s+",
        r"^(?:can|could)\s+(?:you|we)\s+(?:find|show|tell|get|play|read)\s+(?:me\s+)?(?:something\s+)?(?:on|about|from|by)\s+",
        r"^(?:can|could)\s+(?:you|we)\s+(?:find|show|tell|get|play|read)\s+(?:me\s+)?",
        r"^tell\s+(?:me|us)\s+(?:something\s+)?(?:on|about|from|by)\s+",
        r"^tell\s+(?:me|us)\s+",
        r"^(?:i\s+)?want\s+(?:to\s+)?(?:hear|listen\s+to|find|play|get|know|learn)\s+(?:something\s+)?(?:on|about|from|by)\s+",
        r"^(?:i\s+)?want\s+(?:to\s+)?(?:hear|listen\s+to|find|play|get|know|learn)\s+",
        r"^(?:i\s+)?want\s+(?:something\s+)?(?:on|about|from|by)\s+",
        r"^(?:i\s+)?want\s+",
        r"^(?:i\s+wanted|id\s+like|i'd\s+like|i\s+would\s+like)\s+(?:to\s+)?(?:hear|listen\s+to|find|play|get)\s+(?:something\s+)?(?:on|about|from|by)\s+",
        r"^(?:i\s+wanted|id\s+like|i'd\s+like|i\s+would\s+like)\s+(?:to\s+)?(?:hear|listen\s+to|find|play|get)\s+",
        r"^(?:i\s+wanted|id\s+like|i'd\s+like|i\s+would\s+like)\s+(?:to\s+)?",
        r"^play\s+(?:me\s+)?(?:the\s+)?(?:latest|newest|most\s+recent|recent)\s+",
        r"^play\s+(?:me\s+)?(?:some\s+)?(?:on|about|from|by)\s+",
        r"^play\s+(?:me\s+)?",
        r"^give\s+(?:me|us)\s+(?:something\s+)?(?:on|about|from|by)\s+",
        r"^give\s+(?:me|us)\s+",
        r"^(?:read|show|get)\s+(?:me|us)\s+(?:something\s+)?(?:on|about|from|by)\s+",
        r"^(?:read|show|get)\s+(?:me|us)\s+",
        r"^(?:let\s+)?me\s+(?:hear|listen\s+to|find|discover|get)\s+(?:something\s+)?(?:on|about|from|by)\s+",
        r"^(?:let\s+)?me\s+(?:hear|listen\s+to|find|discover|get)\s+",
        r"^what\s+(?:do|can|about)\s+(?:you|we)\s+(?:have|got|find|show|tell|play)\s+(?:on|about|from|by)\s+",
        r"^what\s+(?:do|can)\s+(?:you|we)\s+(?:have|got|find|show|tell)\s+",
        r"^what\s+(?:else\s+)?(?:do|can)\s+(?:you|we)\s+have\s+",
        r"^i\s+(?:need|love)\s+(?:to\s+)?",
        r"^start\s+(?:playing\s+|my\s+daily\s+listen\s+|something\s+)?",
        r"^listen\s+",
        r"^from\s+",
    ]
]


def strip_conversational_topic_prefix(raw) -> str:
    """Remove conversational filler prefixes from a raw search topic string."""
    q = str(raw or "").strip()
    if not q:
        return ""
    for pattern in STRIP_PATTERNS:
        stripped = pattern.sub("", q).strip()
        if stripped == "":
            return ""
        if stripped != q:
            return stripped
    return q


def _normalize_search_query_for_creator(raw) -> str:
    """Normalize a search query specifically for creator/organization lookup."""
    q = str(raw or "").strip()
    if not q:
        return ""
    q = re.sub(r"^(the\s+)?", "", q, flags=re.I)
    q = re.sub(
        r"^(latest|newest|most\s+recent)\s+(recording|recordings|episode|episodes|podcast|podcasts|show|shows|audio|clip|clips|content)\s+(from|by)\s+",
        "", q, flags=re.I,
    )
    q = re.sub(r"^(latest|newest|most\s+recent)\s+(from|by)\s+", "", q, flags=re.I)
    q = re.sub(
        r"^(a\s+)?(recording|recordings|episode|episodes|podcast|podcasts|show|shows|audio|clip|clips|content)\s+(from|by)\s+",
        "", q, flags=re.I,
    )
    q = re.sub(r"\s+(latest|newest|most\s+recent)$", "", q, flags=re.I)
    return q.strip() or str(raw).strip()


def extract_search_query(handler_input) -> str:
    """Extract the user's search query from the Alexa intent and slots."""
    intent_name = get_intent_name(handler_input) or ""
    creator = extract_slot_value(handler_input, "creatorQuery")
    if creator:
        return strip_conversational_topic_prefix(_normalize_search_query_for_creator(creator))
    if intent_name == "PlayByCreatorIntent":
        topic_as_creator = extract_slot_value(handler_input, "topic")
        if topic_as_creator:
            return strip_conversational_topic_prefix(_normalize_search_query_for_creator(topic_as_creator))
    org = extract_slot_value(handler_input, "organizationQuery")
    if org:
        return strip_conversational_topic_prefix(_normalize_search_query_for_creator(org))
    topic = _extract_topic_slot(handler_input)
    if topic:
        parsed = parse_topic_for_search(topic)
        return _normalize_search_query_for_creator(parsed["q"])
    if intent_name == "BrowseByCategoryIntent":
        return _extract_topic_slot(handler_input)
    return ""


def parse_topic_for_search(raw: str) -> dict:
    """Parse a raw topic string into a search query dict with optional tags."""
    q = strip_conversational_topic_prefix(raw)
    if not q:
        return {"q": "", "tags": None}
    m = re.match(r"^(?:about|on|regarding)\s+(.+)$", q, re.I)
    if m:
        topic = m.group(1).strip()
        return {"q": topic, "tags": [topic] if topic else None}
    return {"q": q, "tags": None}


def wants_latest_playback(raw_query: str) -> bool:
    """Check whether the user is requesting the latest content."""
    return bool(re.search(r"\b(latest|newest|most\s+recent|last)\b", str(raw_query or ""), re.I))


def wants_local_community_content(handler_input, search_q: str = "") -> bool:
    """Check whether the user is requesting local/community content."""
    topic = _extract_topic_slot(handler_input)
    q = str(search_q or topic or "").lower().strip()
    category_slot = extract_slot_value(handler_input, "category")
    cat = str(category_slot).lower().strip() if category_slot else ""
    if cat == "community":
        return True
    return bool(re.search(
        r"\b(near me|nearby|local|community|my area|from my area|"
        r"my city|from my city|my town|from my town|around me)\b",
        q,
    ))


def raw_search_phrase(handler_input) -> str:
    """Get the raw search phrase from the intent slots."""
    creator = extract_slot_value(handler_input, "creatorQuery")
    if creator:
        return creator
    return _extract_topic_slot(handler_input)


def wants_play_from_followed_creators(handler_input, text_override: str = "") -> bool:
    """Check whether the user wants to play from followed creators."""
    text = str(
        text_override
        or extract_search_query(handler_input)
        or raw_search_phrase(handler_input)
        or "",
    ).lower().strip()
    if not text:
        return False
    if re.search(r"\bplay\s+(something\s+)?from\s+(my\s+)?followed\b", text):
        return True
    if re.search(r"\bplay\s+from\s+(my\s+)?followed\s+creators?\b", text):
        return True
    if re.search(r"\bhear\s+from\s+(my\s+)?followed\b", text):
        return True
    if re.search(r"\blisten\s+to\s+(my\s+)?followed\b", text):
        return True
    return bool(
        re.search(r"\bfollowed\s+creators?\b", text)
        and re.search(r"\b(play|listen|hear|something|from)\b", text)
    )
