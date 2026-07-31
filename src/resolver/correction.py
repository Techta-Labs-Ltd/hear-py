from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from rapidfuzz import fuzz, process
from rapidfuzz.distance import DamerauLevenshtein

from src.resolver.taxonomy import TaxonomySnapshot, taxonomy_manager
from src.services.semantic_routing import SEARCH_ROUTE_NAMES, semantic_intent_router

_SLOT = re.compile(r"\{[^{}]+\}")
_WORD = re.compile(r"[a-z0-9]+(?:['-][a-z0-9]+)?", re.I)
_SOURCE_TYPES = {"creator", "organization", "publication"}


@dataclass(frozen=True)
class CorrectionResult:
    utterance: str
    corrections: tuple[dict, ...]

class ContextualCommandCorrector:
    def __init__(self, model_path: Path | None = None):
        self._model_path = model_path or Path(__file__).parents[2] / "en-GB.json"
        vocabulary, source_carriers, phrases, starters = self._learn_interaction_language()
        self.vocabulary = tuple(sorted(vocabulary))
        self.source_carriers = frozenset(source_carriers)
        self.command_phrases = frozenset(phrases)
        self.command_starters = frozenset(starters)

    def _learn_interaction_language(
        self,
    ) -> tuple[set[str], set[str], set[str], set[str]]:
        payload = json.loads(self._model_path.read_text(encoding="utf-8"))
        intents = payload["interactionModel"]["languageModel"]["intents"]
        counts: Counter[str] = Counter()
        carriers: set[str] = set()
        phrases: set[str] = set()
        starters: set[str] = set()
        for intent in intents:
            for raw_sample in intent.get("samples") or []:
                sample = str(raw_sample).lower()
                literals = _SLOT.sub(" ", sample)
                words = _WORD.findall(literals)
                counts.update(words)
                if words and not sample.lstrip().startswith("{"):
                    starters.add(words[0])
                for size in range(1, min(4, len(words)) + 1):
                    phrases.update(
                        " ".join(words[index:index + size])
                        for index in range(len(words) - size + 1)
                    )
                for slot_match in _SLOT.finditer(sample):
                    slot_name = slot_match.group(0).lower()
                    if not any(name in slot_name for name in ("creator", "organization", "publication")):
                        continue
                    prefix_words = _WORD.findall(sample[:slot_match.start()])
                    if prefix_words:
                        carriers.add(prefix_words[-1])
        vocabulary = {word for word, count in counts.items() if count >= 2 and len(word) >= 3}
        return vocabulary, carriers, phrases, starters

    @staticmethod
    def _source_suffix_known(text: str, token_end: int, snapshot: TaxonomySnapshot) -> bool:
        suffix = text[token_end:].strip()
        if not suffix:
            return False
        if any(entity.entity_type in _SOURCE_TYPES for entity in snapshot.exact(suffix)):
            return True
        return any(
            snapshot.fuzzy_match(suffix, entity_type, minimum_score=85)
            for entity_type in _SOURCE_TYPES
        )

    @staticmethod
    def _overlaps_entity(start: int, end: int, snapshot: TaxonomySnapshot, text: str) -> bool:
        return any(
            start < entity.end and end > entity.start
            for entity in snapshot.exact(text)
        )

    def correct(
        self,
        utterance: str | None,
        snapshot: TaxonomySnapshot | None = None,
    ) -> CorrectionResult:
        original = str(utterance or "").strip()
        if not original:
            return CorrectionResult("", ())
        active_snapshot = snapshot or taxonomy_manager.snapshot
        tokens = list(_WORD.finditer(original))
        command_ranges = []
        for start_index, first in enumerate(tokens):
            for size in range(1, min(4, len(tokens) - start_index) + 1):
                last = tokens[start_index + size - 1]
                phrase = " ".join(
                    tokens[index].group(0).lower()
                    for index in range(start_index, start_index + size)
                )
                if phrase in self.command_phrases:
                    command_ranges.append((first.start(), last.end()))
        replacements: list[tuple[int, int, str, str]] = []
        for token in tokens:
            value = token.group(0).lower()
            if (
                not value.isalpha()
                or value in self.vocabulary
                or len(value) < 4
                or self._overlaps_entity(token.start(), token.end(), active_snapshot, original)
            ):
                continue
            matches = process.extract(value, self.vocabulary, scorer=fuzz.ratio, limit=5)
            for candidate, score, _ in matches:
                distance = DamerauLevenshtein.distance(value, candidate)
                source_context = (
                    candidate in self.source_carriers
                    and distance <= 2
                    and score >= 70
                    and self._source_suffix_known(original, token.end(), active_snapshot)
                )
                near_command = any(
                    token.start() <= end + 2 and token.end() >= start - 2
                    for start, end in command_ranges
                )
                general_context = (
                    near_command and len(value) >= 5 and distance <= 2 and score >= 78
                )
                initial_command = (
                    token is tokens[0]
                    and candidate in self.command_starters
                    and distance <= 2
                    and score >= 78
                )
                if not source_context and not general_context and not initial_command:
                    continue
                replacements.append((token.start(), token.end(), candidate, value))
                break

        if not replacements:
            return CorrectionResult(original, ())
        corrected = original
        for start, end, candidate, _ in reversed(replacements):
            corrected = corrected[:start] + candidate + corrected[end:]

        original_route = semantic_intent_router.route(original, SEARCH_ROUTE_NAMES)
        corrected_route = semantic_intent_router.route(corrected, SEARCH_ROUTE_NAMES)
        if original_route and corrected_route and original_route.route != corrected_route.route:
            return CorrectionResult(original, ())

        correction_type = "semantic_contextual" if corrected_route else "contextual"
        corrections = tuple({
            "original": source,
            "replacement": candidate,
            "type": correction_type,
        } for _, _, candidate, source in replacements)
        return CorrectionResult(corrected, corrections)


command_corrector = ContextualCommandCorrector()
