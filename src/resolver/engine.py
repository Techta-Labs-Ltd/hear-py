from __future__ import annotations

import logging
import re
import time
from dataclasses import replace

from rapidfuzz.distance import DamerauLevenshtein

from src.resolver.models import ResolvedEntity, SearchPlan, UnresolvedReference
from src.resolver.normalize import (
    CONTENT_NOUNS,
    is_reserved_content_noun,
    normalize_utterance,
    parse_command_modifiers,
)
from src.resolver.taxonomy import TaxonomyManager, taxonomy_manager
from src.resolver.temporal import parse_temporal

logger = logging.getLogger(__name__)
CONTEXT_TYPES = {
    "by": ("creator", "organization"),
    "from": ("creator", "organization", "publication"),
    "in": ("location",),
    "near": ("location",),
    "around": ("location",),
}
# A misspelled place following "from" should still be recoverable, while exact
# "from Burnley" continues to prefer the organisation and unresolved names
# retain the creator/publisher clarification contract.
FUZZY_CONTEXT_TYPES = {
    **CONTEXT_TYPES,
    "from": (*CONTEXT_TYPES["from"], "location"),
}
CONTEXT_PATTERN = re.compile(
    r"\b(by|from|in|near|around)\s+"
    r"([a-z0-9][a-z0-9' -]{2,80}?)"
    r"(?=\s+(?:about|on|from|in|near|around|since)\b|$)"
)
MAX_CONTEXT_ENTITY_WORDS = 4


def _context_types(match: re.Match, *, fuzzy: bool = False) -> tuple[str, ...]:
    """Return entity types allowed by a contextual phrase.

    A spoken ``city`` qualifier is an explicit location signal, including
    after ``from`` where a bare name may otherwise legitimately be an
    organisation or creator.
    """
    if re.search(r"\bcity\s*$", match.group(2)):
        return ("location",)
    mapping = FUZZY_CONTEXT_TYPES if fuzzy else CONTEXT_TYPES
    return mapping[match.group(1)]


def _overlaps(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(start < stop and end > begin for begin, stop in spans)


def _apply_context_type_constraints(
    text: str,
    entities: list[ResolvedEntity],
) -> list[ResolvedEntity]:
    """Remove exact entities whose type conflicts with an explicit relation."""
    constrained = list(entities)
    for match in CONTEXT_PATTERN.finditer(text):
        allowed = set(_context_types(match))
        start, end = match.start(2), match.end(2)
        constrained = [
            entity
            for entity in constrained
            if not (
                entity.start < end
                and entity.end > start
                and entity.entity_type not in allowed
            )
        ]
    return constrained


def _contextual_fuzzy(text: str, claimed: list[tuple[int, int]], manager: TaxonomyManager):
    found: list[ResolvedEntity] = []
    for match in CONTEXT_PATTERN.finditer(text):
        word_matches = list(re.finditer(r"[a-z0-9][a-z0-9'-]*", match.group(2)))
        candidates: list[tuple[ResolvedEntity, int, int]] = []
        for word_count in range(1, min(len(word_matches), MAX_CONTEXT_ENTITY_WORDS) + 1):
            local_end = word_matches[word_count - 1].end()
            start = match.start(2)
            end = match.start(2) + local_end
            if _overlaps(start, end, claimed):
                continue
            phrase = text[start:end]
            for entity_type in _context_types(match, fuzzy=True):
                entity = manager.snapshot.fuzzy_match(phrase, entity_type)
                if entity:
                    candidates.append((entity, start, end))
        by_identity: dict[str, tuple[ResolvedEntity, int, int]] = {}
        for candidate in candidates:
            entity, start, end = candidate
            identity = entity.entity_id or entity.canonical_value
            current = by_identity.get(identity)
            if current is None or end - start > current[2] - current[1]:
                by_identity[identity] = candidate
        candidates = list(by_identity.values())
        candidates.sort(
            key=lambda item: (item[0].confidence, item[2] - item[1]),
            reverse=True,
        )
        if not candidates:
            continue
        winner, winner_start, winner_end = candidates[0]
        preferred_fuzzy_location = False
        # A one-edit town and an organisation that owns the same town alias
        # commonly receive identical scores (for example "swidon"). For a
        # fuzzy "from" phrase, prefer the place; exact spellings continue
        # through the exact matcher and preserve organisation precedence.
        if match.group(1) == "from":
            location_candidates = [
                item for item in candidates
                if item[0].entity_type == "location"
            ]
            if (
                location_candidates
                and location_candidates[0][0].confidence >= winner.confidence
            ):
                winner, winner_start, winner_end = location_candidates[0]
                preferred_fuzzy_location = True
                candidates = [
                    (winner, winner_start, winner_end),
                    *[
                        item for item in candidates
                        if item[0].entity_type != "location"
                    ],
                ]
        if (
            not preferred_fuzzy_location
            and
            len(candidates) > 1
            and winner.confidence - candidates[1][0].confidence < 0.03
            and (winner.entity_id or winner.canonical_value)
            != (candidates[1][0].entity_id or candidates[1][0].canonical_value)
        ):
            continue
        found.append(replace(winner, start=winner_start, end=winner_end))
    return found


def _unresolved_contextual_references(
    text: str,
    claimed: list[tuple[int, int]],
) -> list[UnresolvedReference]:
    unresolved = []
    for match in CONTEXT_PATTERN.finditer(text):
        if _overlaps(match.start(2), match.end(2), claimed):
            continue
        unresolved.append(UnresolvedReference(
            relation=match.group(1),
            phrase=match.group(2).strip(),
            expected_types=_context_types(match),
            start=match.start(2),
            end=match.end(2),
        ))
    return unresolved


def _location_qualifier_spans(
    text: str,
    entities: list[ResolvedEntity],
) -> list[tuple[int, int]]:
    """Claim ``city`` only when it qualifies an actually resolved location."""
    spans: list[tuple[int, int]] = []
    for match in CONTEXT_PATTERN.finditer(text):
        city = re.search(r"\bcity\s*$", match.group(2))
        if not city:
            continue
        phrase_start, phrase_end = match.start(2), match.end(2)
        if any(
            entity.entity_type == "location"
            and entity.start < phrase_end
            and entity.end > phrase_start
            for entity in entities
        ):
            spans.append((
                phrase_start + city.start(),
                phrase_start + city.end(),
            ))
    return spans


def _facet_fuzzy(
    text: str,
    claimed: list[tuple[int, int]],
    manager: TaxonomyManager,
) -> list[ResolvedEntity]:
    """Resolve one-edit category/tag ASR variants from taxonomy data."""
    proposals: list[ResolvedEntity] = []
    ignored = CONTENT_NOUNS | {
        "about", "and", "around", "by", "for", "from", "in", "near",
        "on", "regarding", "since", "the", "to",
    }
    words = list(re.finditer(r"\b[a-z][a-z-]*\b", text))
    aliases = [
        (entity_type, alias, record)
        for entity_type in ("category", "tag")
        for alias, record in manager.snapshot.fuzzy.get(entity_type, {}).items()
    ]
    for start_index, first in enumerate(words):
        for word_count in range(1, min(4, len(words) - start_index) + 1):
            last = words[start_index + word_count - 1]
            start, end = first.start(), last.end()
            phrase = text[start:end]
            if _overlaps(start, end, claimed):
                continue
            if word_count == 1 and phrase in ignored:
                continue
            if any(
                words[index].group(0) in {
                    "about", "around", "by", "from", "in", "near", "on", "since", "to",
                }
                for index in range(start_index, start_index + word_count)
            ):
                continue
            normalized_phrase = phrase.replace("-", " ")
            candidates: dict[tuple[str, str], tuple[str, str, object, int]] = {}
            for entity_type, alias, record in aliases:
                normalized_alias = alias.replace("-", " ")
                if len(normalized_alias.split()) != word_count:
                    continue
                distance = DamerauLevenshtein.distance(
                    normalized_phrase, normalized_alias,
                )
                if distance > 1:
                    continue
                identity = record.entity_id or record.slug or record.canonical
                key = (entity_type, identity)
                current = candidates.get(key)
                if current is None or distance < current[3]:
                    candidates[key] = (
                        entity_type, normalized_alias, record, distance,
                    )
            if len(candidates) != 1:
                continue
            entity_type, alias, record, distance = next(iter(candidates.values()))
            similarity = 1.0 - (
                distance / max(len(normalized_phrase), len(alias))
            )
            if similarity < 0.82:
                continue
            proposals.append(ResolvedEntity(
                entity_type,
                record.entity_id,
                record.slug or record.canonical,
                phrase,
                similarity,
                "fuzzy-category",
                start,
                end,
                record.metadata,
            ))
    proposals.sort(key=lambda item: (-(item.end - item.start), item.start))
    found = []
    for item in proposals:
        if not any(_overlaps(item.start, item.end, [(x.start, x.end)]) for x in found):
            found.append(item)
    return found


def _extract_query(text: str, claimed: list[tuple[int, int]]) -> str:
    chars = list(text)
    for start, end in claimed:
        for index in range(max(start, 0), min(end, len(chars))):
            chars[index] = " "
    relation_words = {"about", "on", "regarding", "by", "from", "in", "near", "around", "since"}
    tokens = [
        token for token in re.sub(r"[-']", " ", "".join(chars)).split()
        if not is_reserved_content_noun(token) and token not in relation_words
    ]
    return " ".join(tokens).strip()


def _append_unique(target: list[str], value: str | None) -> None:
    if value and value not in target:
        target.append(value)


class Resolver:
    def __init__(self, taxonomy: TaxonomyManager | None = None):
        self.taxonomy = taxonomy or taxonomy_manager

    def resolve(
        self,
        utterance: str,
        alexa_user_id: str = "",
        timezone: str = "Europe/London",
        *,
        page: int = 0,
        limit: int = 20,
    ) -> SearchPlan:
        started = time.perf_counter()
        normalized = normalize_utterance(utterance)
        normalized_at = time.perf_counter()
        commands = parse_command_modifiers(normalized)
        temporal = parse_temporal(normalized, timezone)
        temporal_at = time.perf_counter()
        claimed = list(commands.claimed)
        if temporal:
            claimed.append((temporal.start, temporal.end))
        protected_claimed = list(claimed)
        entities = self.taxonomy.snapshot.exact(normalized, claimed)
        entities = _apply_context_type_constraints(normalized, entities)
        claimed.extend((item.start, item.end) for item in entities)
        fuzzy = _contextual_fuzzy(normalized, protected_claimed, self.taxonomy)
        # A fuzzy place must not override an exact creator/publisher occupying
        # the same spoken span. Other fuzzy candidates may extend a partial
        # exact name, such as "David Beerd".
        fuzzy = [
            item for item in fuzzy
            if not (
                item.entity_type == "location"
                and any(
                    item.start < exact.end and item.end > exact.start
                    for exact in entities
                    if exact.entity_type != "location"
                )
            )
        ]
        fuzzy_keys = {(item.entity_type, item.entity_id or item.canonical_value) for item in fuzzy}
        entities = [
            item for item in entities
            if (item.entity_type, item.entity_id or item.canonical_value) not in fuzzy_keys
        ]
        entities.extend(fuzzy)
        claimed.extend((item.start, item.end) for item in fuzzy)
        for entity in entities:
            if entity.entity_type != "location":
                continue
            suffix = re.match(
                r"\s+(?:city|town|village|borough)\b",
                normalized[entity.end:],
            )
            if suffix:
                claimed.append((entity.end, entity.end + suffix.end()))
        claimed.extend(_location_qualifier_spans(normalized, entities))
        # Search the full non-command text so a longer one-edit taxonomy
        # phrase ("community service" -> tag "community-services") can
        # replace shorter exact facet fragments ("community" + "service").
        facet_fuzzy = _facet_fuzzy(
            normalized, protected_claimed, self.taxonomy,
        )
        entities = [
            item
            for item in entities
            if not (
                item.entity_type in {"category", "tag"}
                and any(
                    fuzzy.start < item.end and fuzzy.end > item.start
                    for fuzzy in facet_fuzzy
                )
            )
        ]
        entities.extend(facet_fuzzy)
        claimed.extend((item.start, item.end) for item in facet_fuzzy)
        ambiguous_references = self.taxonomy.snapshot.ambiguous(normalized, claimed)
        claimed.extend((item.start, item.end) for item in ambiguous_references)
        unresolved_references = _unresolved_contextual_references(normalized, claimed)
        query = _extract_query(normalized, claimed)
        plan = SearchPlan(
            alexa_user_id=alexa_user_id,
            query=query,
            is_local=commands.is_local,
            is_recommended=commands.is_recommended,
            sort=commands.sort,
            page=page,
            limit=limit,
            temporal=temporal,
            entities=entities,
            unresolved_references=unresolved_references,
            ambiguous_references=ambiguous_references,
            normalized_text=normalized,
            taxonomy_revision=self.taxonomy.snapshot.revision,
        )
        for entity in entities:
            value = entity.entity_id or entity.canonical_value
            if entity.entity_type == "category":
                _append_unique(plan.category_slugs, entity.canonical_value)
            elif entity.entity_type == "tag":
                _append_unique(plan.tags, entity.canonical_value)
            elif entity.entity_type == "creator":
                _append_unique(plan.creator_ids, value)
            elif entity.entity_type == "organization":
                _append_unique(plan.organization_ids, value)
            elif entity.entity_type == "publication":
                _append_unique(plan.publication_ids, value)
            elif entity.entity_type == "location":
                plan.city = entity.metadata.get("city") or entity.canonical_value
                plan.country_code = (
                    entity.metadata.get("countryCode") or entity.metadata.get("country_code")
                )
        if commands.is_local and not plan.city:
            plan.city = None
        plan.confidence = min((entity.confidence for entity in entities), default=1.0)
        finished = time.perf_counter()
        plan.timing_ms = {
            "normalize": round((normalized_at - started) * 1000, 3),
            "temporal": round((temporal_at - normalized_at) * 1000, 3),
            "entityResolution": round((finished - temporal_at) * 1000, 3),
            "total": round((finished - started) * 1000, 3),
        }
        logger.info("Hear resolver decision", extra={"resolver": diagnostic(plan, utterance)})
        return plan


def diagnostic(plan: SearchPlan, utterance: str) -> dict:
    return {
        "utterance": utterance,
        "normalized": plan.normalized_text,
        "taxonomyRevision": plan.taxonomy_revision,
        "entities": [
            {"text": item.original_text, "type": item.entity_type,
             "value": item.entity_id or item.canonical_value,
             "method": item.method, "confidence": item.confidence}
            for item in plan.entities
        ],
        "unresolvedReferences": [
            {
                "relation": item.relation,
                "phrase": item.phrase,
                "expectedTypes": list(item.expected_types),
            }
            for item in plan.unresolved_references
        ],
        "ambiguousReferences": [
            {
                "phrase": item.phrase,
                "candidates": [
                    {
                        "type": candidate.entity_type,
                        "id": candidate.entity_id,
                        "name": candidate.canonical_value,
                    }
                    for candidate in item.candidates
                ],
            }
            for item in plan.ambiguous_references
        ],
        "query": plan.query,
        "isLocal": plan.is_local,
        "isRecommended": plan.is_recommended,
        "sort": plan.sort,
        "timingMs": plan.timing_ms,
    }


resolver = Resolver()
