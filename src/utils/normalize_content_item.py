from __future__ import annotations

import re
from urllib.parse import urlparse


def repair_mojibake(value):
    """Repair the common UTF-8-as-Windows-1252 corruption seen in API text."""
    text = nullable_string(value)
    if not text or not any(marker in text for marker in ("â€", "â€™", "Ã", "Â")):
        return text
    try:
        return text.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def nullable_string(value):
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def is_id_like_label(value) -> bool:
    if not isinstance(value, str):
        return True
    t = value.strip()
    if not t:
        return True
    if re.fullmatch(r"[a-z]?\d+(?:[-_]\d+)*", t, re.I):
        return True
    if re.search(r"\d{3,}[_-]post", t, re.I):
        return True
    if re.search(r"[_-]post\d+", t, re.I):
        return True
    if re.search(r"track\d+", t, re.I) and re.search(r"post|_", t):
        return True
    if re.search(r"\s", t):
        return False
    if len(t) <= 12:
        return False
    if re.search(r"[_/\\\.:]", t):
        return True
    if re.search(r"\d{4,}", t):
        return True
    if re.match(r"^[a-z0-9-]+$", t, re.I) and re.search(r"\d", t) and len(t) > 16:
        return True
    return False


def is_weak_title(value) -> bool:
    """Check whether a title is weak/generic and should not be spoken."""
    if not isinstance(value, str):
        return True
    t = value.strip()
    if not t:
        return True
    if re.match(r"^test\s*\d*$", t, re.I):
        return True
    if re.match(r"^test\s+\d+$", t, re.I):
        return True
    if re.match(r"^untitled$", t, re.I):
        return True
    if re.match(r"^recording\s*\d*$", t, re.I):
        return True
    if _is_breadcrumb_title(t):
        return True
    return False


def _is_breadcrumb_title(value: str) -> bool:
    """Check whether a title is a breadcrumb path (contains >)."""
    if not isinstance(value, str):
        return False
    return ">" in value.strip()


def prefer_readable(*candidates) -> str | None:
    """Pick the most human-readable candidate from a series of values."""
    first_any = None
    first_non_id = None
    for candidate in candidates:
        s = nullable_string(candidate)
        if not s:
            continue
        if first_any is None:
            first_any = s
        if not is_id_like_label(s) and not is_weak_title(s):
            return s
        if first_non_id is None and not is_id_like_label(s):
            first_non_id = s
    return first_non_id or first_any


def derive_locality_string(item: dict) -> str | None:
    return nullable_string(item.get("locality"))


def _first_search_phrase(item: dict) -> str | None:
    """Get the first search phrase from a content item."""
    phrases = item.get("searchPhrases")
    if not isinstance(phrases, list):
        return None
    for p in phrases:
        s = nullable_string(p)
        if s:
            return s
    return None


def _themes_label(item: dict) -> str | None:
    """Build a label from theme tags."""
    themes = item.get("themes")
    if not isinstance(themes, list) or not themes:
        return None
    parts = [nullable_string(t) for t in themes[:2]]
    parts = [p for p in parts if p]
    return ", ".join(parts) if parts else None


def _pick_curated_title(item: dict) -> str | None:
    return prefer_readable(
        nullable_string(item.get("shortDescription")),
        _first_search_phrase(item),
        _themes_label(item),
    )


def _pick_display_title(item: dict) -> str:
    actual = prefer_readable(
        item.get("displayTitle"),
        item.get("spokenTitle"),
        item.get("title"),
    )
    if actual and not is_weak_title(actual) and not is_id_like_label(actual):
        return actual
    curated = _pick_curated_title(item)
    if curated and not is_weak_title(curated) and not is_id_like_label(curated):
        return curated
    return actual or curated or "a local recording"


def pick_spoken_title(item: dict) -> str:
    return _pick_display_title(item)


def is_bad_credit_name(value) -> bool:
    """Check whether a credit name is unusable for spoken output."""
    if not value:
        return True
    raw = str(value).strip()
    if not raw:
        return True
    if is_id_like_label(raw):
        return True
    t = raw.lower()
    if re.match(r"^(super\s+)?admin(istrator)?$", t) or t in ("unknown", "system", "admin"):
        return True
    if len(raw) > 48:
        return True
    words = [w for w in raw.split() if w]
    if len(words) > 5:
        return True
    if len(words) >= 5 and raw == t:
        return True
    if re.match(r"^(really|so|scared)\s+", raw, re.I):
        return True
    if re.match(r"^(really|so|scared)$", raw, re.I):
        return True
    if re.search(r"\b(the force|right help|coming from|so happy to be)\b", t):
        return True
    if len(words) >= 3 and raw == t and re.search(r"\b(from|coming|happy|force|help|right)\b", t):
        return True
    return False


def _is_independent_org(name) -> bool:
    n = str(name or "").strip().lower()
    return n in ("independent", "independent creator")


def _is_bad_organization_name(value) -> bool:
    raw = str(value or "").strip()
    if not raw or len(raw) > 120 or is_id_like_label(raw):
        return True
    return raw.lower() in {"unknown", "system", "admin", "administrator"}


def _extract_creator_name(item: dict) -> str | None:
    creator = item.get("creator")
    if isinstance(creator, dict):
        return repair_mojibake(creator.get("name"))
    return repair_mojibake(creator) or repair_mojibake(item.get("creatorName"))


def _extract_creator_id(item: dict) -> str | None:
    creator = item.get("creator")
    if isinstance(creator, dict):
        return creator.get("id") or None
    return item.get("creatorId") or None


def _pick_organization_name(item: dict) -> str | None:
    org = item.get("organization")
    if isinstance(org, dict):
        name = repair_mojibake(org.get("name"))
        if name:
            return name
    return repair_mojibake(item.get("organizationName"))


def _is_organization_publisher(item: dict) -> bool:
    if not isinstance(item, dict):
        return False
    org = _pick_organization_name(item)
    return bool(
        org
        and not _is_independent_org(org)
        and not _is_bad_organization_name(org)
    )


def pick_attribution_kind(item: dict) -> str:
    if _is_organization_publisher(item):
        return "organization"
    creator = _extract_creator_name(item)
    if creator and not is_bad_credit_name(creator):
        return "creator"
    return "creator"


def pick_attribution_credit(item: dict) -> str | None:
    creator = _extract_creator_name(item)
    org = _pick_organization_name(item)
    org_pub = _is_organization_publisher(item)
    if org_pub and org:
        return org
    if creator and not is_bad_credit_name(creator):
        return creator
    if org and not _is_bad_organization_name(org) and not _is_independent_org(org):
        return org
    return None


def pick_content_credit(item: dict) -> str | None:
    """Pick the content credit for playback attribution."""
    return pick_attribution_credit(item)


def pick_content_source(item: dict) -> dict | None:
    if not isinstance(item, dict):
        return None
    organization_name = _pick_organization_name(item)
    organization_id = item.get("organizationId")
    organization = item.get("organization")
    if isinstance(organization, dict):
        organization_id = organization.get("id") or organization_id
    if _is_organization_publisher(item) and organization_id:
        return {
            "kind": "organization",
            "id": organization_id,
            "name": organization_name,
        }
    creator_name = _extract_creator_name(item)
    creator_id = _extract_creator_id(item)
    if creator_id and creator_name and not is_bad_credit_name(creator_name):
        return {"kind": "creator", "id": creator_id, "name": creator_name}
    return None


def pick_menu_credit(item: dict) -> str | None:
    """Pick the menu credit for browse listing display."""
    return pick_attribution_credit(item)


def pick_main_topic(item: dict) -> str | None:
    return nullable_string(item.get("mainTopic"))


def pick_summary(item: dict) -> str | None:
    return nullable_string(item.get("shortDescription"))


def _pick_playback_speeds(item: dict) -> list | None:
    if isinstance(item.get("playback_speed"), list) and item["playback_speed"]:
        return item["playback_speed"]
    if isinstance(item.get("playbackSpeed"), list) and item["playbackSpeed"]:
        return item["playbackSpeed"]
    return None


def _pick_duration_secs(source: dict) -> int | None:
    if not isinstance(source, dict):
        return None
    for key in ("durationSecs", "duration_secs"):
        v = source.get(key)
        if isinstance(v, (int, float)) and v > 0:
            return int(v)
    return None


def _extract_named_entity(item: dict, key: str) -> tuple[str | None, str | None]:
    value = item.get(key)
    if isinstance(value, dict):
        return nullable_string(value.get("id")), nullable_string(value.get("name"))
    return (
        nullable_string(item.get(f"{key}Id")),
        nullable_string(value) or nullable_string(item.get(f"{key}Name")),
    )


def _category_value(item: dict):
    category = item.get("category")
    if category:
        return category
    categories = item.get("categories")
    return categories[0] if isinstance(categories, list) and categories else None


def _is_https_url(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    parsed = urlparse(value.strip())
    return parsed.scheme == "https" and bool(parsed.netloc)


def normalize_content_item(item: dict) -> dict:
    if not isinstance(item, dict):
        return item
    content_id = nullable_string(item.get("contentId"))
    creator_id, creator_name = _extract_named_entity(item, "creator")
    organization_id, organization_name = _extract_named_entity(item, "organization")
    publication_id, publication_title = _extract_named_entity(item, "publication")
    is_publication = bool(item.get("isPublication") or item.get("type") == "publication")
    publication_id = (
        nullable_string(item.get("publicationId"))
        or publication_id
        or (content_id if is_publication else None)
    )
    publication_title = (
        repair_mojibake(item.get("publicationTitle"))
        or publication_title
        or (repair_mojibake(item.get("title")) if is_publication else None)
    )
    duration_secs = _pick_duration_secs(item)
    return {
        "contentId": content_id,
        "title": repair_mojibake(item.get("title")),
        "displayTitle": repair_mojibake(_pick_display_title(item)),
        "spokenTitle": repair_mojibake(pick_spoken_title(item)),
        "summary": pick_summary(item),
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
        "category": _category_value(item),
        "tags": item.get("tags") if isinstance(item.get("tags"), list) else [],
        "audioUrl": nullable_string(item.get("audioUrl")),
        "playbackSpeeds": _pick_playback_speeds(item) or [],
        "durationMs": duration_secs * 1000 if duration_secs else None,
        "publishedAt": item.get("publishedAt"),
    }


def is_playable_content_item(item: dict) -> bool:
    """Return whether an item has a content ID and Alexa-compatible audio."""
    return bool(
        isinstance(item, dict)
        and item.get("contentId")
        and _is_https_url(item.get("audioUrl"))
    )


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
        if not is_publication or not isinstance(tracks, list) or not tracks:
            expanded.append(item)
            continue
        publication_id = nullable_string(item.get("publicationId")) or nullable_string(item.get("contentId"))
        publication_title = repair_mojibake(item.get("title"))
        track_count = int(item.get("trackCount") or len(tracks))
        for index, track in enumerate(tracks):
            if not isinstance(track, dict):
                continue
            merged = dict(item)
            merged.pop("tracks", None)
            merged.pop("durationSecs", None)
            merged.pop("duration_secs", None)
            merged.update(track)
            merged.update({
                "publicationId": publication_id,
                "publicationTitle": publication_title,
                "type": "publication_track",
                "isPublication": True,
                "trackIndex": index,
                "trackCount": track_count,
            })
            expanded.append(merged)
    normalized = (normalize_content_item(item) for item in expanded)
    return [i for i in normalized if is_playable_content_item(i)]


def content_title_for_speech(item: dict) -> str | None:
    if not isinstance(item, dict):
        return None
    title = item.get("spokenTitle") or item.get("displayTitle") or nullable_string(item.get("title"))
    if title and not is_id_like_label(title) and not is_weak_title(title):
        return _humanize_spoken_title_safe(title) or title
    curated = _pick_curated_title(item)
    if curated and not is_weak_title(curated) and not is_id_like_label(curated):
        return _humanize_spoken_title_safe(curated) or curated
    return curated or "a local recording"


def _humanize_spoken_title_safe(value: str) -> str | None:
    """Safely clean a title for speech output."""
    if not isinstance(value, str):
        return None
    t = value.strip()
    if not t or is_id_like_label(t):
        return None
    return t
