from __future__ import annotations

STRONG_CONFIDENCE = 85

INTENT_PRIORITY = [
    {"role": "creator", "field": "creator", "intent": "creator", "slot": "creatorQuery"},
    {"role": "organisation", "field": "organisation", "intent": "organization", "slot": "organizationQuery"},
    {"role": "category", "field": "category", "intent": "category", "slot": "category"},
    {"role": "location", "field": "location", "intent": "local", "slot": "city"},
]


def _populated(entity) -> bool:
    """Check whether a gRPC entity has a non-empty name."""
    if entity is None:
        return False
    name = getattr(entity, "name", None)
    return bool(name and str(name).strip())


def _confidence_of(entity) -> float:
    """Get the confidence value from a gRPC entity."""
    if entity is None:
        return 0.0
    val = getattr(entity, "confidence", None)
    if isinstance(val, (int, float)):
        return float(val)
    return 0.0


def _name(entity) -> str:
    """Get the name string from a gRPC entity."""
    return str(entity.name).strip()


def _to_ten_scale(pct: float | None) -> int:
    """Convert a 0-100 confidence to a 0-10 integer scale."""
    return max(0, min(10, round((pct or 0) / 10)))


def map_resolve_reply(reply) -> dict | None:
    """Map a gRPC resolve reply to the NLP result format."""
    if reply is None:
        return None

    slots: dict = {}

    if _populated(reply.creator):
        slots["creatorQuery"] = _name(reply.creator)
    if _populated(reply.organisation):
        slots["organizationQuery"] = _name(reply.organisation)
    if _populated(reply.category):
        slots["category"] = _name(reply.category)
    if _populated(reply.location):
        loc = reply.location
        loc_name = (
            str(loc.city).strip() if getattr(loc, "city", None) and str(loc.city).strip()
            else _name(loc)
        )
        slots["city"] = loc_name
        slots["placeName"] = loc_name
        if getattr(loc, "lat", None) and getattr(loc, "lng", None):
            slots["lat"] = str(loc.lat)
            slots["lng"] = str(loc.lng)

    tags = getattr(reply, "tags", None) or []
    if tags:
        tag_names = [_name(t) for t in tags if _populated(t)]
        if tag_names:
            slots["tags"] = tag_names

    temporal = getattr(reply, "temporal", None)
    if temporal is not None and (getattr(temporal, "type", None) or getattr(temporal, "value", None)):
        t_type = getattr(temporal, "type", "") or ""
        t_value = getattr(temporal, "value", "") or ""
        if t_type == "recency" or any(w in str(t_value).lower() for w in ("latest", "recent", "newest", "new")):
            slots["latest"] = True
        slots["temporal"] = {
            "type": t_type,
            "value": t_value,
            "date": getattr(temporal, "date", "") or "",
        }

    freetext = str(reply.freetext).strip() if getattr(reply, "freetext", None) else ""
    if freetext:
        slots["topic"] = freetext
        slots["residualQuery"] = freetext

    primary = None
    for p in INTENT_PRIORITY:
        if _populated(getattr(reply, p["field"], None)):
            primary = p
            break

    if primary is not None:
        intent = primary["intent"]
    elif freetext:
        intent = "general"
    else:
        intent = "unclear"

    top_confidence = _confidence_of(getattr(reply, primary["field"], None)) if primary is not None else 0.0
    if primary is None and freetext:
        confidence = "high"
    elif top_confidence >= STRONG_CONFIDENCE:
        confidence = "high"
    else:
        confidence = "low"

    alternatives: list[dict] = []
    for p in INTENT_PRIORITY:
        if primary is not None and p["field"] == primary["field"]:
            continue
        if p["role"] == "category":
            continue
        entity = getattr(reply, p["field"], None)
        if _populated(entity):
            alternatives.append({
                "intent": p["intent"],
                "query": _name(entity),
                "display": _name(entity),
                "displayText": _name(entity),
                "confidence": _to_ten_scale(_confidence_of(entity)),
            })

    candidates = getattr(reply, "candidates", None) or []
    for c in candidates:
        if _populated(c):
            alternatives.append({
                "intent": "general",
                "query": _name(c),
                "display": _name(c),
                "displayText": _name(c),
                "confidence": _to_ten_scale(_confidence_of(c)),
            })

    cache_hit = bool(getattr(reply, "cache_hit", False))
    resolved_in_ms = getattr(reply, "resolved_in_ms", None)
    resolved_in_ms = float(resolved_in_ms) if isinstance(resolved_in_ms, (int, float)) else 0.0

    return {
        "intent": intent,
        "confidence": confidence,
        "slots": slots,
        "alternatives": alternatives,
        "cacheHit": cache_hit,
        "resolvedInMs": resolved_in_ms,
    }
