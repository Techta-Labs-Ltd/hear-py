from __future__ import annotations

import re

from src.nlp.dynamic_data import get_categories, get_creators, get_organizations, get_locations
from src.nlp.patterns import (
    TRENDING_HINTS, LOCAL_HINTS, FOLLOWING_HINTS, BROWSE_HINTS,
    MORE_HINTS, COMMAND_DENY,
    FEEDBACK_ENJOYED_HINTS, FEEDBACK_NOT_ENJOYED_HINTS,
    FEEDBACK_SOMEWHAT_HINTS, FEEDBACK_SKIP_HINTS,
)
from src.nlp.preprocess import preprocess_utterance
from src.nlp.wink_instance import get_spacy_nlp

RELATED: dict[str, list[str]] = {
    "creator": ["following", "browse"],
    "organization": ["browse", "trending"],
    "category": ["browse", "trending"],
    "trending": ["browse", "following"],
    "local": ["browse", "trending"],
    "following": ["creator", "trending"],
    "browse": ["trending", "following"],
    "general": ["browse", "trending"],
}

DISPLAY_TEXT = {
    "creator": lambda q: f"play from {q}",
    "organization": lambda q: f"play from {q}",
    "category": lambda q: f"play {q} content",
    "trending": lambda: "what's trending",
    "local": lambda: "content near me",
    "following": lambda: "from people I follow",
    "browse": lambda: "what's new",
    "show_more": lambda: "show more results",
    "general": lambda q: f"search for {q}",
    "feedback_enjoyed": lambda: "you enjoyed it",
    "feedback_not_enjoyed": lambda: "you did not enjoy it",
    "feedback_somewhat": lambda: "it was okay",
    "feedback_skip": lambda: "skip feedback",
}


def tokenize(raw: str | None) -> list[str]:
    """Tokenize a raw string into lowercase alphanumeric tokens."""
    if not raw or not str(raw).strip():
        return []
    return [t for t in re.sub(r"[^a-z0-9\s]", " ", str(raw).lower()).split() if t]


def bigrams(tokens: list[str]) -> list[str]:
    """Generate bigrams from a list of tokens."""
    out: list[str] = []
    for i in range(len(tokens) - 1):
        out.append(f"{tokens[i]} {tokens[i + 1]}")
    return out


def trigrams(tokens: list[str]) -> list[str]:
    """Generate trigrams from a list of tokens."""
    out: list[str] = []
    for i in range(len(tokens) - 2):
        out.append(f"{tokens[i]} {tokens[i + 1]} {tokens[i + 2]}")
    return out


def clean_tokens(tokens: list[str]) -> list[str]:
    """Remove command/deny words from a list of tokens."""
    return [t for t in tokens if t not in COMMAND_DENY]


def levenshtein(a: str, b: str) -> int:
    """Compute the Levenshtein edit distance between two strings."""
    if len(a) == 0:
        return len(b)
    if len(b) == 0:
        return len(a)
    m, n = len(a), len(b)
    prev = list(range(n + 1))
    curr = [0] * (n + 1)
    for i in range(1, m + 1):
        curr[0] = i
        for j in range(1, n + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev, curr = curr, prev
    return prev[n]


def smart_max_dist(name_len: int) -> int:
    """Calculate the maximum allowable edit distance for a name of given length."""
    return max(2, (name_len + 2) // 3)


def fuzzy_match_entity(word: str, entity_map: dict) -> dict | None:
    """Fuzzy-match a word against an entity map, returning the best match with confidence."""
    word_lower = word.lower()
    word_tokens = word_lower.split()
    names = list(entity_map.get("names", set()))
    aliases = entity_map.get("aliases") or entity_map.get("synonyms") or {}

    candidates: list[dict] = []

    for name in names:
        name_lower = name.lower()
        name_tokens = name_lower.split()

        if word_lower == name_lower:
            candidates.append({"name": name, "distance": 0, "confidence": 10, "matchType": "exact"})
            continue

        if word_lower.find(name_lower) >= 0:
            candidates.append({"name": name, "distance": 0, "confidence": 9, "matchType": "word_contains_name"})
            continue
        if name_lower.find(word_lower) >= 0:
            candidates.append({"name": name, "distance": 0, "confidence": 8, "matchType": "name_contains_word"})
            continue

        overlap_count = 0
        for wt in word_tokens:
            for nt in name_tokens:
                if wt == nt:
                    overlap_count += 1
                    break
                if len(wt) >= 4 and nt.find(wt) >= 0:
                    overlap_count += 1
                    break
                if len(nt) >= 4 and wt.find(nt) >= 0:
                    overlap_count += 1
                    break
        if overlap_count > 0:
            overlap_conf = min(9, 6 + overlap_count)
            candidates.append({
                "name": name, "distance": len(name_tokens) - overlap_count,
                "confidence": overlap_conf, "matchType": "token_overlap",
            })
            continue

        max_dist = smart_max_dist(max(len(word_lower), len(name_lower)))
        dist = levenshtein(word_lower, name_lower)
        if len(word_lower) >= 4 and dist < max_dist:
            lev_conf = max(7 - dist, 4)
            candidates.append({"name": name, "distance": dist, "confidence": lev_conf, "matchType": "levenshtein"})

    for alias, canonical in aliases.items():
        alias_lower = alias.lower()
        if word_lower == alias_lower:
            candidates.append({"name": canonical, "distance": 0, "confidence": 10, "matchType": "alias_exact"})
        elif (
            (len(alias_lower) >= 4 and word_lower.find(alias_lower) >= 0)
            or (len(word_lower) >= 4 and alias_lower.find(word_lower) >= 0)
        ):
            candidates.append({"name": canonical, "distance": 0, "confidence": 8, "matchType": "alias_substring", "alias": alias_lower})
        else:
            alias_dist = levenshtein(word_lower, alias_lower)
            alias_max = smart_max_dist(max(len(word_lower), len(alias_lower)))
            if len(word_lower) >= 4 and len(alias_lower) >= 3 and alias_dist < alias_max:
                candidates.append({
                    "name": canonical, "distance": alias_dist,
                    "confidence": max(6 - alias_dist, 4),
                    "matchType": "alias_levenshtein", "alias": alias_lower,
                })

    if not candidates:
        return None

    candidates.sort(key=lambda c: (-c["confidence"], -len(c["name"]), c["distance"]))

    best = candidates[0]
    return {"name": best["name"], "distance": best["distance"], "confidence": best["confidence"]}


def match_category(tokens: list[str], stems: list[str]) -> dict | None:
    """Try to match tokens against known categories with confidence scoring."""
    dyn_cats = get_categories()
    names = dyn_cats.get("names", set())
    synonyms = dyn_cats.get("synonyms", {})
    dyn_stems = dyn_cats.get("stems", {})

    if names:
        for tok in tokens:
            if tok in names:
                return {"name": tok, "confidence": 10}
        if synonyms:
            for tok in tokens:
                if tok in synonyms:
                    return {"name": synonyms[tok], "confidence": 9}
        for tok in tokens:
            for cat in names:
                if len(tok) >= 3 and tok.find(cat) >= 0 and len(cat) >= 3:
                    return {"name": cat, "confidence": 7}
                if len(cat) >= 3 and cat.find(tok) >= 0 and len(tok) >= 3:
                    return {"name": cat, "confidence": 6}
        for stem in stems:
            for cat_name, cat_stem in dyn_stems.items():
                if stem == cat_stem:
                    return {"name": cat_name, "confidence": 8}
                if stem.find(cat_stem) >= 0 or cat_stem.find(stem) >= 0:
                    return {"name": cat_name, "confidence": 6}

    return None


def _add_deduped(results: list[dict], item: dict) -> None:
    """Add an item to results, skipping duplicates by intent + query."""
    for r in results:
        if r["intent"] == item["intent"] and (r.get("query") or "") == (item.get("query") or ""):
            return
    results.append(item)


def suggest(raw: str | None) -> list[dict]:
    """Generate a ranked list of intent suggestions from a raw utterance."""
    if not raw or not str(raw).strip():
        return []

    text = str(raw).strip()
    normalized = re.sub(r"[^a-z0-9\s]", " ", text.lower()).strip()
    normalized = re.sub(r"\s+", " ", normalized)
    all_tokens = tokenize(text)
    clean_all = clean_tokens(all_tokens)
    clean_long = [t for t in clean_all if len(t) > 1]
    bg = bigrams(clean_all)
    tg = trigrams(clean_all)
    nlp_instance = get_spacy_nlp()
    stems = []
    for t in clean_all:
        try:
            doc = nlp_instance(t)
            tok = list(doc)
            stems.append(tok[0].lemma_.lower() if tok else t)
        except Exception:
            stems.append(t)

    results: list[dict] = []

    candidate_tokens = clean_all + bg + tg

    creators = get_creators()
    if creators.get("names"):
        for candidate in candidate_tokens:
            match = fuzzy_match_entity(candidate, creators)
            if match:
                _add_deduped(results, {
                    "intent": "creator", "query": match["name"],
                    "displayText": DISPLAY_TEXT["creator"](match["name"]),
                    "confidence": match["confidence"], "match": "dynamodb_creator",
                })

    orgs = get_organizations()
    if orgs.get("names"):
        for candidate in candidate_tokens:
            org_match = fuzzy_match_entity(candidate, orgs)
            if org_match:
                _add_deduped(results, {
                    "intent": "organization", "query": org_match["name"],
                    "displayText": DISPLAY_TEXT["organization"](org_match["name"]),
                    "confidence": org_match["confidence"], "match": "dynamodb_org",
                })

    if clean_all:
        cat = match_category(clean_all, stems)
        if cat:
            _add_deduped(results, {
                "intent": "category", "query": cat["name"],
                "displayText": DISPLAY_TEXT["category"](cat["name"]),
                "confidence": cat["confidence"], "match": "category",
            })

    hint_checks = [
        (TRENDING_HINTS, "trending"),
        (LOCAL_HINTS, "local"),
        (FOLLOWING_HINTS, "following"),
        (BROWSE_HINTS, "browse"),
        (MORE_HINTS, "show_more"),
        (FEEDBACK_ENJOYED_HINTS, "feedback_enjoyed"),
        (FEEDBACK_NOT_ENJOYED_HINTS, "feedback_not_enjoyed"),
        (FEEDBACK_SOMEWHAT_HINTS, "feedback_somewhat"),
        (FEEDBACK_SKIP_HINTS, "feedback_skip"),
    ]

    for w in clean_all:
        for hint_set, intent_name in hint_checks:
            if w in hint_set and not any(r["intent"] == intent_name for r in results):
                _add_deduped(results, {
                    "intent": intent_name, "query": None,
                    "displayText": DISPLAY_TEXT[intent_name]() if callable(DISPLAY_TEXT.get(intent_name)) else intent_name,
                    "confidence": 7, "match": "hint_set",
                })

    locations = get_locations()
    location_set = locations.get("cities", set())
    if location_set:
        for tok in clean_all:
            if tok in location_set:
                _add_deduped(results, {
                    "intent": "local", "query": tok,
                    "displayText": f"content near {tok}",
                    "confidence": 9, "match": "dynamodb_location",
                })

    pp = preprocess_utterance(text)
    if pp["places"]:
        place_name = pp["places"][0]
        place_lower = place_name.lower()
        already_found = any(r["intent"] == "local" and r.get("query") == place_lower for r in results)
        if not already_found:
            _add_deduped(results, {
                "intent": "local", "query": place_name,
                "displayText": f"content near {place_name}",
                "confidence": 7, "match": "preprocess_place",
            })

    if clean_long:
        topic = " ".join(clean_long)
        _add_deduped(results, {
            "intent": "general", "query": topic,
            "displayText": DISPLAY_TEXT["general"](topic),
            "confidence": 3, "match": "keyword_fallback",
        })

    results.sort(key=lambda r: -r["confidence"])

    if 0 < len(results) < 3:
        top_intent = results[0]["intent"]
        related = RELATED.get(top_intent, [])
        for rel in related:
            if len(results) >= 3:
                break
            if not any(r["intent"] == rel for r in results):
                fn = DISPLAY_TEXT.get(rel)
                results.append({
                    "intent": rel, "query": None,
                    "displayText": fn() if callable(fn) else str(rel),
                    "confidence": 5, "match": "related",
                })

    if not results:
        results.append({
            "intent": "browse", "query": None,
            "displayText": DISPLAY_TEXT["browse"](),
            "confidence": 2, "match": "default",
        })
        results.append({
            "intent": "trending", "query": None,
            "displayText": DISPLAY_TEXT["trending"](),
            "confidence": 1, "match": "default",
        })

    return results[:3]


def find_suggestions(raw: str | None) -> list[dict]:
    """Convenience alias for suggest()."""
    return suggest(raw)
