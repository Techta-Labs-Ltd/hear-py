from __future__ import annotations

import re

from src.nlp.dynamic_data import get_categories, get_creators, get_organizations, get_locations
from src.nlp.patterns import (
    TRENDING_HINTS, LOCAL_HINTS, FOLLOWING_HINTS, BROWSE_HINTS,
    MORE_HINTS, COMMAND_DENY,
    FEEDBACK_SKIP_HINTS, FEEDBACK_SOMEWHAT_HINTS,
    FEEDBACK_NOT_ENJOYED_HINTS, FEEDBACK_ENJOYED_HINTS,
)
from src.nlp.preprocess import preprocess_utterance
from src.nlp.suggestions import fuzzy_match_entity
from src.nlp.wink_instance import resolve_name, resolve_name_prefix

GENERIC_CONTENT: set[str] = {
    "track", "tracks", "content", "recording", "recordings", "audio",
    "clip", "clips", "episode", "episodes", "podcast", "podcasts",
}

RESIDUAL_STOP: set[str] = {
    "play", "find", "search", "show", "tell", "give", "get", "read", "hear", "listen",
    "start", "put", "me", "my", "i", "a", "an", "the", "some", "something",
    "anything", "content", "recording", "recordings", "track", "tracks", "audio",
    "podcast", "podcasts", "episode", "episodes", "latest", "newest", "recent", "most",
    "new", "from", "by", "near", "in", "on", "about", "of", "to", "for", "with",
    "please", "want", "would", "like", "you", "have", "do", "us",
    "what", "whats", "what\u2019s", "is", "are", "was", "were", "trending", "popular", "hot",
    "browse", "available", "recommend", "recommended", "everyone", "anyone", "people",
    "listening", "going", "happening", "around", "here", "today", "fresh", "now",
}


def match_hints(normalized: str, hints: set[str]) -> bool:
    """Check whether a normalized utterance matches any hint in a set."""
    if normalized in hints:
        return True
    words = normalized.split()
    for hint in hints:
        if normalized == hint:
            return True
        if normalized.startswith(hint + " ") or normalized.endswith(" " + hint):
            return True
        hint_words = hint.split()
        if len(hint_words) == 1:
            if hint in words:
                return True
        else:
            if f" {hint} " in f" {normalized} ":
                return True
    return False


def match_suffix_hints(normalized: str, hints: set[str]) -> bool:
    """Check whether a normalized utterance ends with any hint."""
    if normalized in hints:
        return True
    for hint in hints:
        if normalized == hint:
            return True
        if normalized.endswith(" " + hint):
            return True
    return False


def detect_category(pp: dict) -> str | None:
    """Detect a content category from preprocessed utterance data."""
    dyn_cats = get_categories()
    names = dyn_cats.get("names", set())
    synonyms = dyn_cats.get("synonyms", {})
    stems_map = dyn_cats.get("stems", {})

    best: str | None = None
    best_conf = 0

    def consider(name: str, conf: int) -> None:
        nonlocal best, best_conf
        if conf > best_conf:
            best_conf = conf
            best = name

    cat_stem_values: list[str] = list(stems_map.values()) if isinstance(stems_map, dict) else []

    for i, stem in enumerate(pp["stems"]):
        stem_tok = re.sub(r"[^a-z]", "", str(pp["tokens"][i] if i < len(pp["tokens"]) else "").lower())
        if stem_tok in GENERIC_CONTENT:
            continue
        if isinstance(stems_map, dict):
            for cat_name, cat_stem in stems_map.items():
                if stem == cat_stem:
                    consider(cat_name, 8)
                elif len(stem) >= 4 and len(cat_stem) >= 4 and stem.find(cat_stem) >= 0:
                    consider(cat_name, 6)

    skip_nouns_re = re.compile(r"^(play|find|show|tell|give|get|read|hear|listen|start)$", re.IGNORECASE)
    for noun in pp["nouns"]:
        n = re.sub(r"[^a-z]", "", noun.lower())
        if n in COMMAND_DENY or skip_nouns_re.match(n) or n in GENERIC_CONTENT:
            continue
        if n in names:
            consider(n, 10)
        if synonyms and n in synonyms:
            consider(synonyms[n], 9)

    for token in pp["tokens"]:
        clean = re.sub(r"[^a-z]", "", str(token).lower())
        if clean in COMMAND_DENY or skip_nouns_re.match(clean) or clean in GENERIC_CONTENT:
            continue
        if clean in names:
            consider(clean, 10)
        if synonyms and clean in synonyms:
            consider(synonyms[clean], 9)

    return best


def detect_multi_word_category(pp: dict) -> dict | None:
    """Detect a multi-word category (e.g. 'talking newspaper') from preprocessed data."""
    dyn_cats = get_categories()
    names = dyn_cats.get("names", set()) if dyn_cats else set()
    synonyms = dyn_cats.get("synonyms", {}) if dyn_cats else {}

    toks = [re.sub(r"[^a-z0-9]", "", str(t).lower()) for t in (pp.get("tokens") or [])]

    def lookup(key: str) -> str | None:
        if names and key in names:
            return key
        if synonyms and key in synonyms:
            return synonyms[key]
        return None

    for i in range(len(toks) - 2):
        a, b, c = toks[i], toks[i + 1], toks[i + 2]
        if not a or not b or not c:
            continue
        for form in (f"{a}-{b}-{c}", f"{a}{b}{c}", f"{a} {b} {c}"):
            hit = lookup(form)
            if hit:
                return {"name": hit, "words": [a, b, c]}

    for i in range(len(toks) - 1):
        x, y = toks[i], toks[i + 1]
        if not x or not y:
            continue
        for form in (f"{x}-{y}", f"{x}{y}", f"{x} {y}"):
            hit = lookup(form)
            if hit:
                return {"name": hit, "words": [x, y]}

    return None


def build_residual_query(pp: dict, slots: dict, extra_removed: list[str] | None = None) -> str:
    """Build a residual query by removing already-matched entities from the utterance."""
    dyn_cats = get_categories()
    names = dyn_cats.get("names", set()) if dyn_cats else set()
    synonyms = dyn_cats.get("synonyms", {}) if dyn_cats else {}
    stems = dyn_cats.get("stems", {}) if dyn_cats else {}
    cat_stem_vals = list(stems.values()) if isinstance(stems, dict) else []

    removed: set[str] = set()
    for v in [slots.get("creatorQuery"), slots.get("organizationQuery"), slots.get("city"),
              slots.get("placeName"), slots.get("category")]:
        if not v:
            continue
        for w in str(v).lower().split(r"[\s-]+"):
            c = re.sub(r"[^a-z0-9]", "", w)
            if c:
                removed.add(c)

    if extra_removed:
        for w in extra_removed:
            c = re.sub(r"[^a-z0-9]", "", str(w).lower())
            if c:
                removed.add(c)

    creator_lc = str(slots.get("creatorQuery", "")).lower() if slots.get("creatorQuery") else None
    org_lc = str(slots.get("organizationQuery", "")).lower() if slots.get("organizationQuery") else None
    city_lc = str(slots.get("city") or slots.get("placeName", "")).lower() if (slots.get("city") or slots.get("placeName")) else None

    def resolves_to_matched(tk: str) -> bool:
        if creator_lc and (
            resolve_name("CREATOR", tk).lower() == creator_lc
            or resolve_name_prefix("CREATOR", tk).lower() == creator_lc
        ):
            return True
        if org_lc and (
            resolve_name("ORGANIZATION", tk).lower() == org_lc
            or resolve_name_prefix("ORGANIZATION", tk).lower() == org_lc
        ):
            return True
        if city_lc and resolve_name("LOCATION", tk).lower() == city_lc:
            return True
        return False

    out: list[str] = []
    pp_stems = pp.get("stems") or []
    for i, token in enumerate(pp.get("tokens") or []):
        tk = re.sub(r"[^a-z0-9]", "", str(token).lower())
        if not tk:
            continue
        st = str(pp_stems[i]).lower() if i < len(pp_stems) else ""
        if tk in RESIDUAL_STOP:
            continue
        if tk in removed:
            continue
        if tk in names or (synonyms and tk in synonyms):
            continue
        if st and st in cat_stem_vals:
            continue
        if resolves_to_matched(tk):
            continue
        out.append(re.sub(r"[^a-zA-Z0-9]", "", str(token)))
    return " ".join(out).strip()


def route_to_correct_intent(normalized: str) -> str:
    """Determine the primary intent from a normalized utterance using hint sets."""
    if match_hints(normalized, TRENDING_HINTS):
        return "trending"
    if match_hints(normalized, LOCAL_HINTS):
        return "local"
    if match_hints(normalized, FOLLOWING_HINTS):
        return "following"
    if match_hints(normalized, BROWSE_HINTS):
        return "browse"
    if match_hints(normalized, MORE_HINTS):
        return "show_more"
    return "general"


def classify_utterance(raw: str | None) -> dict:
    """Classify a raw user utterance into an intent with extracted slots."""
    if not raw or not str(raw).strip():
        return {"intent": "general", "confidence": "low", "slots": {}}

    text = str(raw).strip()
    pp = preprocess_utterance(text)
    normalized = re.sub(r"[^a-z0-9\s]", "", pp["raw"].lower()).strip()
    wants_latest = bool(re.search(r"\b(latest|newest|most\s+recent|recent)\b", normalized, re.IGNORECASE))

    slots: dict = {}

    found_creator: str | None = None
    found_org: str | None = None
    found_city: str | None = None
    found_category: str | None = None
    found_intent: str | None = None

    cleaned_tokens = normalized.split()

    if pp["places"]:
        place_name = pp["places"][0]
        locations = get_locations()
        place_lower = place_name.lower()
        city_set = locations.get("cities", set()) if locations else set()
        if city_set and place_lower in city_set:
            found_city = place_name
            slots["city"] = place_name
            slots["placeName"] = place_name
        else:
            slots["placeName"] = place_name

    if not found_city:
        dyn_locs = get_locations()
        city_set2 = dyn_locs.get("cities", set()) if dyn_locs else set()
        if city_set2:
            for tok in cleaned_tokens:
                if tok in city_set2:
                    pp_raw_lower = re.sub(r"[^a-z0-9\s]", "", pp["raw"].lower()).strip()
                    pp_tokens = pp_raw_lower.split()
                    orig_idx = pp_tokens.index(tok) if tok in pp_tokens else -1
                    raw_tokens = pp["raw"].split()
                    orig_city = raw_tokens[orig_idx] if 0 <= orig_idx < len(raw_tokens) else tok
                    found_city = orig_city
                    slots["city"] = orig_city
                    slots["placeName"] = orig_city
                    break

    is_search_prefix = bool(re.match(
        r"^(find|play|search|show|give|get|look|i want|i need|tell me|do you have|anything)\s",
        normalized,
    ))

    if not is_search_prefix:
        if match_hints(normalized, FEEDBACK_SKIP_HINTS):
            return {"intent": "feedback_skip", "confidence": "high", "slots": {}}
        if match_hints(normalized, FEEDBACK_SOMEWHAT_HINTS):
            return {"intent": "feedback_somewhat", "confidence": "high", "slots": {}}
        if match_hints(normalized, FEEDBACK_NOT_ENJOYED_HINTS):
            return {"intent": "feedback_not_enjoyed", "confidence": "high", "slots": {}}
        if match_hints(normalized, FEEDBACK_ENJOYED_HINTS):
            return {"intent": "feedback_enjoyed", "confidence": "high", "slots": {}}

    if pp["people"]:
        person_name = resolve_name("CREATOR", pp["people"][0])
        found_creator = person_name
        slots["creatorQuery"] = person_name

    if pp["organisations"]:
        org_name = resolve_name("ORGANIZATION", pp["organisations"][0])
        found_org = org_name
        slots["organizationQuery"] = org_name

    custom_ents = pp.get("customEntities") or []
    found_categories: list[str] = []
    is_prefix = bool(re.match(r"^(play|find|show|tell|give|get|read|hear|listen|start)", normalized, re.IGNORECASE))
    prefix_words = ["play", "show", "find", "tell", "give", "get", "read", "hear", "listen", "start"]

    for ent in custom_ents:
        ent_type = ent.get("type") if isinstance(ent, dict) else None
        ent_value = ent.get("value") if isinstance(ent, dict) else ent
        if ent_type == "CREATOR" and not found_creator:
            found_creator = resolve_name("CREATOR", str(ent_value))
            slots["creatorQuery"] = found_creator
        if ent_type == "ORGANIZATION" and not found_org:
            found_org = resolve_name("ORGANIZATION", str(ent_value))
            slots["organizationQuery"] = found_org
        if ent_type == "CATEGORY":
            val = str(ent_value)
            skip_word = is_prefix and val in prefix_words
            skip_local = val in LOCAL_HINTS or val.lower() in LOCAL_HINTS
            skip_generic = val.lower() in GENERIC_CONTENT
            if not skip_word and not skip_local and not skip_generic:
                found_categories.append(val)
        if ent_type == "LOCATION" and not found_city:
            found_city = resolve_name("LOCATION", str(ent_value))
            slots["city"] = found_city
            slots["placeName"] = found_city

    if found_categories:
        best_cat_conf = 0
        for cat_name in found_categories:
            dyn_cats = get_categories()
            conf = 0
            resolved = cat_name
            if dyn_cats and dyn_cats.get("names") and cat_name in dyn_cats["names"]:
                conf = 10
                resolved = cat_name
            elif dyn_cats and dyn_cats.get("synonyms") and cat_name in dyn_cats["synonyms"]:
                conf = 9
                resolved = dyn_cats["synonyms"][cat_name]
            if conf > best_cat_conf:
                best_cat_conf = conf
                found_category = resolved
        if found_category:
            slots["category"] = found_category

    if match_hints(normalized, TRENDING_HINTS):
        found_intent = "trending"
    elif match_hints(normalized, LOCAL_HINTS):
        found_intent = "local"
    elif match_hints(normalized, FOLLOWING_HINTS):
        found_intent = "following"
    elif match_suffix_hints(normalized, BROWSE_HINTS):
        found_intent = "browse"
    if match_hints(normalized, MORE_HINTS):
        found_intent = "show_more"

    if not found_creator and not found_org and not found_city:
        fb_re = re.compile(r"\b(?:from|by)\s+([a-z][a-z ]{0,39}?)(?:\s*$|\s+(?:the )?(?:latest|newest|most recent)\b)")
        fb_m = fb_re.search(normalized)
        if fb_m:
            fb_text = fb_m.group(1).strip()
            fb_tokens = fb_text.split()
            fb_resolved = False
            for fbl in range(len(fb_tokens), 0, -1):
                fb_phrase = " ".join(fb_tokens[:fbl])
                fb_cr = resolve_name("CREATOR", fb_phrase)
                if fb_cr != fb_phrase:
                    found_creator = fb_cr
                    slots["creatorQuery"] = fb_cr
                    fb_resolved = True
                    break
                fb_org = resolve_name("ORGANIZATION", fb_phrase)
                if fb_org != fb_phrase:
                    found_org = fb_org
                    slots["organizationQuery"] = fb_org
                    fb_resolved = True
                    break
            if not fb_resolved:
                for fbl2 in range(len(fb_tokens), 0, -1):
                    fb_phrase2 = " ".join(fb_tokens[:fbl2])
                    fb_cr2 = resolve_name_prefix("CREATOR", fb_phrase2)
                    if fb_cr2 != fb_phrase2:
                        found_creator = fb_cr2
                        slots["creatorQuery"] = fb_cr2
                        fb_resolved = True
                        break
                    fb_org2 = resolve_name_prefix("ORGANIZATION", fb_phrase2)
                    if fb_org2 != fb_phrase2:
                        found_org = fb_org2
                        slots["organizationQuery"] = fb_org2
                        fb_resolved = True
                        break

    if not found_category:
        found_category = detect_category(pp)
        if found_category:
            slots["category"] = found_category
            if "topic" not in slots:
                slots["topic"] = found_category

    multi_cat = detect_multi_word_category(pp)
    multi_cat_words = None
    if multi_cat:
        found_category = multi_cat["name"]
        slots["category"] = multi_cat["name"]
        multi_cat_words = multi_cat["words"]
        if "topic" not in slots or slots.get("topic") == pp["raw"]:
            slots["topic"] = multi_cat["name"]

    if not found_city:
        locs = get_locations()
        city_set3 = locs.get("cities", set()) if locs else set()
        if city_set3:
            for tok in cleaned_tokens:
                if tok in city_set3:
                    found_city = tok
                    slots["city"] = tok
                    slots["placeName"] = tok
                    break

    fuzzy_city_word = None
    if not found_city:
        locs_f = get_locations()
        dyn_cats_f = get_categories()
        city_set_f = locs_f.get("cities", set()) if locs_f else set()
        if city_set_f:
            city_map_f = {"names": city_set_f}
            for ftok in cleaned_tokens:
                if not ftok or len(ftok) < 5:
                    continue
                if ftok in RESIDUAL_STOP:
                    continue
                cat_names_f = dyn_cats_f.get("names", set()) if dyn_cats_f else set()
                cat_syns_f = dyn_cats_f.get("synonyms", {}) if dyn_cats_f else {}
                if cat_names_f and ftok in cat_names_f:
                    continue
                if cat_syns_f and ftok in cat_syns_f:
                    continue
                if resolve_name("CREATOR", ftok) != ftok or resolve_name("ORGANIZATION", ftok) != ftok:
                    continue
                fm = fuzzy_match_entity(ftok, city_map_f)
                if fm and fm["confidence"] >= 6 and fm["distance"] <= 2:
                    found_city = fm["name"]
                    slots["city"] = fm["name"]
                    slots["placeName"] = fm["name"]
                    fuzzy_city_word = ftok
                    break

    if wants_latest:
        slots["latest"] = True

    extra_removed = (multi_cat_words or []) + ([fuzzy_city_word] if fuzzy_city_word else [])
    slots["residualQuery"] = build_residual_query(pp, slots, extra_removed)

    if found_intent:
        intent = found_intent
    elif found_creator:
        intent = "creator"
    elif found_org:
        intent = "organization"
    elif found_city:
        intent = "local"
    elif found_category:
        intent = "category"
        slots["category"] = found_category
        if "topic" not in slots:
            slots["topic"] = found_category
    else:
        intent = "general"
        if "topic" not in slots:
            slots["topic"] = pp["raw"]

    if intent in ("trending", "browse", "following", "show_more"):
        slots["residualQuery"] = ""

    return {"intent": intent, "confidence": "high", "slots": slots}
