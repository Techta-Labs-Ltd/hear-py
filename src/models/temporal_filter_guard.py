from __future__ import annotations

import re


class TemporalFilterGuard:
    SOURCE_TYPES = frozenset({"organization", "creator", "publication"})
    TEMPORAL_SLOT_KEYS = frozenset(
        {"publishedFrom", "publishedTo", "dateQuery", "dateLabel", "temporalOriginal"}
    )
    _RELATIVE = re.compile(
        r"\b(?:today|tomorrow|yesterday|tonight|now|this\s+(?:morning|afternoon|evening|weekend)|last\s+(?:night|weekend)|next\s+(?:morning|afternoon|evening|weekend))\b",
        re.IGNORECASE,
    )
    _WEEKDAY = re.compile(
        r"\b(?:(?:this|next|last|previous|coming)\s+)?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|weekdays?|weekends?|weekenders?)\b",
        re.IGNORECASE,
    )
    _MONTH = re.compile(
        r"\b(?:(?:this|next|last|previous|coming|in|on|from|during)\s+)?(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)(?:\s+\d{1,2}(?:st|nd|rd|th)?|\s+\d{4})?\b",
        re.IGNORECASE,
    )
    _PERIOD = re.compile(
        r"\b(?:(?:(?:this|next|last|previous|coming)\s+)?(?:day|week|month|year|quarter)|(?:first|second|third|fourth|1st|2nd|3rd|4th)\s+quarter|q[1-4](?:\s+\d{4})?)\b",
        re.IGNORECASE,
    )
    _NUMERIC = re.compile(
        r"\b(?:\d{4}-\d{2}(?:-\d{2})?|\d{4}-W\d{2}(?:-WE)?|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|\d{1,2}(?:st|nd|rd|th)?\s+(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)(?:\s+\d{4})?|(?:19|20)\d{2})\b",
        re.IGNORECASE,
    )
    _TEMPORAL_PATTERNS = (_RELATIVE, _WEEKDAY, _MONTH, _PERIOD, _NUMERIC)

    @classmethod
    def _text(cls, value: object) -> str:
        return " ".join(str(value or "").split())

    @classmethod
    def _entity_span(cls, entity: dict, utterance: str) -> tuple[int, int] | None:
        start_value = entity.get("start")
        end_value = entity.get("end")
        try:
            if (
                isinstance(start_value, bool)
                or isinstance(end_value, bool)
                or not isinstance(start_value, (str, int))
                or not isinstance(end_value, (str, int))
            ):
                return None
            start, end = int(start_value), int(end_value)
        except (TypeError, ValueError):
            start, end = -1, -1
        original = cls._text(entity.get("originalText"))
        canonical = cls._text(entity.get("canonicalValue"))
        span_text = cls._text(utterance[start:end]) if 0 <= start < end <= len(utterance) else ""
        if span_text and span_text.casefold() in {original.casefold(), canonical.casefold()}:
            return start, end
        return None

    @classmethod
    def _source_spans(cls, entities: object, utterance: str) -> tuple[tuple[int, int], ...]:
        if not isinstance(entities, list):
            return ()
        spans = [
            span
            for entity in entities
            if isinstance(entity, dict)
            and str(entity.get("entityType") or entity.get("type") or "").casefold()
            in cls.SOURCE_TYPES
            and (span := cls._entity_span(entity, utterance)) is not None
        ]
        return tuple(sorted(spans))

    @classmethod
    def _temporal_spans(cls, utterance: str) -> tuple[tuple[int, int], ...]:
        spans = {
            (match.start(), match.end())
            for pattern in cls._TEMPORAL_PATTERNS
            for match in pattern.finditer(utterance)
        }
        return tuple(sorted(spans))

    @staticmethod
    def _contained(span: tuple[int, int], sources: tuple[tuple[int, int], ...]) -> bool:
        return any(source_start <= span[0] and span[1] <= source_end for source_start, source_end in sources)

    @classmethod
    def _has_temporal_filter(cls, result: dict) -> bool:
        slots = result.get("slots") or {}
        payload = result.get("searchPayload") or {}
        search_plan = slots.get("searchPlan") or {}
        values = (
            *(slots.get(key) for key in cls.TEMPORAL_SLOT_KEYS),
            *(payload.get(key) for key in cls.TEMPORAL_SLOT_KEYS),
            *(dict(payload.get("filter") or {}).get(key) for key in cls.TEMPORAL_SLOT_KEYS),
            *(search_plan.get(key) for key in cls.TEMPORAL_SLOT_KEYS),
            *(dict(search_plan.get("filter") or {}).get(key) for key in cls.TEMPORAL_SLOT_KEYS),
        )
        return any(value is not None and str(value).strip() for value in values)

    @classmethod
    def apply(cls, result: dict, original_utterance: object) -> dict:
        utterance = str(original_utterance or "")
        if not utterance or not cls._has_temporal_filter(result):
            return result
        sources = cls._source_spans(result.get("entities"), utterance)
        temporal = cls._temporal_spans(utterance)
        if not sources or not temporal or not all(cls._contained(span, sources) for span in temporal):
            return result
        guarded = dict(result)
        slots = dict(guarded.get("slots") or {})
        for key in cls.TEMPORAL_SLOT_KEYS:
            slots.pop(key, None)
        search_plan = dict(slots.get("searchPlan") or {})
        for key in cls.TEMPORAL_SLOT_KEYS:
            search_plan.pop(key, None)
        search_plan_filter = dict(search_plan.get("filter") or {})
        for key in cls.TEMPORAL_SLOT_KEYS:
            search_plan_filter.pop(key, None)
        if search_plan_filter:
            search_plan["filter"] = search_plan_filter
        else:
            search_plan.pop("filter", None)
        if search_plan:
            slots["searchPlan"] = search_plan
        else:
            slots.pop("searchPlan", None)
        payload = dict(guarded.get("searchPayload") or {})
        for key in cls.TEMPORAL_SLOT_KEYS:
            payload.pop(key, None)
        payload_filter = dict(payload.get("filter") or {})
        for key in cls.TEMPORAL_SLOT_KEYS:
            payload_filter.pop(key, None)
        if payload_filter:
            payload["filter"] = payload_filter
        else:
            payload.pop("filter", None)
        guarded["slots"] = slots
        guarded["searchPayload"] = payload
        return guarded
