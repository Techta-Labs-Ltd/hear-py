from __future__ import annotations

import re

from src.constants.dialog import DialogConstants


class DialogPolicy:
    @staticmethod
    def choices(pending: dict) -> list[dict]:
        choices = pending.get("choiceCandidates")
        if choices:
            return list(choices)
        return DialogPolicy.unique_candidates(list(pending.get("candidates") or []))

    @staticmethod
    def normalize(value: object) -> str:
        raw = str(value or "").strip().casefold().replace("&", " and ")
        for apostrophe in ("'", "’", "‘", "ʼ", "`"):
            raw = raw.replace(apostrophe, "")
        return re.sub(r"[^a-z0-9]+", " ", raw).strip()

    @staticmethod
    def unique_candidates(candidates: list[dict]) -> list[dict]:
        seen: set[str] = set()
        unique = []
        for candidate in candidates:
            name = str(candidate.get("name") or "").strip()
            key = name.casefold()
            if name and key not in seen:
                seen.add(key)
                unique.append(candidate)
        return unique

    @staticmethod
    def normalize_ordinal(value: object) -> str:
        raw = DialogPolicy.normalize(value)
        raw = raw.replace("1st", "first").replace("2nd", "second").replace("3rd", "third")
        raw = raw.replace("4th", "fourth").replace("5th", "fifth").replace("6th", "sixth")
        raw = re.sub(r"^(?:(?:please\s+)?(?:play|choose|select|pick)|i\s+meant)\s+", "", raw)
        raw = re.sub("^(?:the\\s+)", "", raw)
        raw = re.sub(r"^(?:option|choice|number)\s+", "", raw)
        return re.sub("\\s+(?:one|option|choice)$", "", raw)

    @staticmethod
    def is_dismiss_phrase(value: object) -> bool:
        normalized = DialogPolicy.normalize(value)
        return bool(normalized) and (
            normalized in DialogConstants.CHOICE_DISMISS_PHRASES
            or normalized.startswith(("no ", "none of ", "neither of "))
        )
