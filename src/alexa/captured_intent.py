from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path

from src.alexa.request import AlexaRequest
from src.utils.filters import SearchFilterUtils


class CapturedIntentRouter:
    """Restore normal intent routing when an open SearchQuery dialog captures a command."""

    logger = logging.getLogger(__name__)
    MAX_CONSTRAINED_VALUES = 25

    @staticmethod
    def _model_path() -> Path:
        return Path(__file__).resolve().parents[2] / "en-GB.json"

    @staticmethod
    def _slot_names(sample: str) -> list[str]:
        return list(dict.fromkeys(re.findall(r"\{([A-Za-z][A-Za-z0-9_]*)\}", sample)))

    @staticmethod
    def _sample_pattern(sample: str) -> re.Pattern[str]:
        pieces = re.split(r"(\{[A-Za-z][A-Za-z0-9_]*\})", sample)
        seen: set[str] = set()
        pattern = ""
        for piece in pieces:
            slot = re.fullmatch(r"\{([A-Za-z][A-Za-z0-9_]*)\}", piece)
            if slot:
                name = slot.group(1)
                pattern += rf"(?P={name})" if name in seen else rf"(?P<{name}>.+?)"
                seen.add(name)
                continue
            literal_parts = re.split(r"(\s+)", piece)
            pattern += "".join(
                r"\s+" if part.isspace() else re.escape(part)
                for part in literal_parts
                if part
            )
        return re.compile(rf"^{pattern}$", re.IGNORECASE)

    @staticmethod
    def _type_values(model: dict) -> dict[str, dict]:
        values_by_type: dict[str, dict] = {}
        for slot_type in model.get("types", []):
            values: dict[str, str] = {}
            canonical_values = slot_type.get("values", [])
            for item in canonical_values:
                name = item.get("name") or {}
                canonical = str(name.get("value") or "").strip()
                if not canonical:
                    continue
                for value in (canonical, *name.get("synonyms", [])):
                    normalized = SearchFilterUtils.normalize_discovery_phrase(value)
                    if normalized:
                        values.setdefault(normalized, canonical)
            values_by_type[slot_type["name"]] = {
                "canonicalCount": len(canonical_values),
                "values": values,
            }
        return values_by_type

    @classmethod
    @lru_cache(maxsize=1)
    def _routes(cls) -> tuple[dict[str, dict], tuple[dict, ...]]:
        model = json.loads(cls._model_path().read_text(encoding="utf-8"))[
            "interactionModel"
        ]["languageModel"]
        type_values = cls._type_values(model)
        static_routes: dict[str, dict] = {}
        patterned_routes: list[dict] = []
        for intent_order, intent in enumerate(model.get("intents", [])):
            intent_name = intent["name"]
            slot_types = {
                slot["name"]: slot["type"] for slot in intent.get("slots", [])
            }
            for sample_order, sample in enumerate(intent.get("samples", [])):
                names = cls._slot_names(sample)
                if not names:
                    static_routes.setdefault(
                        SearchFilterUtils.normalize_discovery_phrase(sample),
                        {"name": intent_name, "slots": {}},
                    )
                    continue
                literal_weight = len(re.sub(r"\{[^}]+\}", "", sample).strip())
                patterned_routes.append(
                    {
                        "name": intent_name,
                        "slotNames": names,
                        "slotTypes": slot_types,
                        "pattern": cls._sample_pattern(sample),
                        "literalWeight": literal_weight,
                        "intentOrder": intent_order,
                        "sampleOrder": sample_order,
                        "typeValues": type_values,
                    }
                )
        patterned_routes.sort(
            key=lambda route: (
                -route["literalWeight"],
                len(route["slotNames"]),
                route["intentOrder"],
                route["sampleOrder"],
            )
        )
        return static_routes, tuple(patterned_routes)

    @classmethod
    def _patterned_route(cls, raw: str) -> dict | None:
        _, routes = cls._routes()
        for route in routes:
            match = route["pattern"].fullmatch(raw)
            if not match:
                continue
            slots: dict[str, dict] = {}
            valid = True
            for name in route["slotNames"]:
                value = str(match.group(name) or "").strip()
                slot_type = route["slotTypes"].get(name, "")
                type_values = route["typeValues"].get(slot_type)
                if (
                    type_values is not None
                    and type_values["canonicalCount"] <= cls.MAX_CONSTRAINED_VALUES
                ):
                    canonical = type_values["values"].get(
                        SearchFilterUtils.normalize_discovery_phrase(value)
                    )
                    if canonical is None:
                        valid = False
                        break
                    value = canonical
                slots[name] = {
                    "name": name,
                    "value": value,
                    "confirmationStatus": "NONE",
                }
            if valid:
                return {"name": route["name"], "slots": slots}
        return None

    @classmethod
    def resolve(cls, raw: object) -> dict | None:
        value = str(raw or "").strip()
        if not value:
            return None
        static, _ = cls._routes()
        route = static.get(SearchFilterUtils.normalize_discovery_phrase(value))
        return route or cls._patterned_route(value)

    @classmethod
    def apply(cls, handler_input) -> None:
        request = AlexaRequest.read(handler_input.request_envelope, "request")
        intent = AlexaRequest.read(request, "intent")
        if (
            AlexaRequest.read(request, "type") != "IntentRequest"
            or AlexaRequest.read(request, "dialogState", "dialog_state") != "IN_PROGRESS"
            or AlexaRequest.read(intent, "name") != "SearchContentIntent"
        ):
            return
        slots = AlexaRequest.read(intent, "slots") or {}
        raw = AlexaRequest.get_resolved_slot_value(AlexaRequest.read(slots, "searchQuery"))
        route = cls.resolve(raw)
        if not route:
            return
        request["intent"] = {
            "name": route["name"],
            "confirmationStatus": "NONE",
            "slots": route["slots"],
        }
        request["dialogState"] = "COMPLETED"
        cls.logger.info(
            "Hear: restored captured command intent=%s raw=%s",
            route["name"],
            raw,
        )
