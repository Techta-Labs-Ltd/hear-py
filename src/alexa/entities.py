from __future__ import annotations

from src.constants.discovery import DiscoveryConstants


class AlexaEntities:
    @staticmethod
    def build_ambiguity_dynamic_entities_directive(
        candidates: list[dict],
    ) -> dict | None:
        unique: dict[str, dict] = {}
        for candidate in candidates:
            name = str(candidate.get("name") or "").strip()
            if not name or name.casefold() in unique:
                continue
            unique[name.casefold()] = candidate
        choices = list(unique.values())
        if not choices:
            return None
        word_lists = [str(item["name"]).split() for item in choices]
        common_words: list[str] = []
        for words in zip(*word_lists):
            if len({word.casefold() for word in words}) != 1:
                break
            common_words.append(words[0])
        prefix = " ".join(common_words)
        values = []
        ordinal_synonyms = DiscoveryConstants.CHOICE_ORDINAL_SYNONYMS
        for index, candidate in enumerate(choices):
            name = str(candidate["name"]).strip()
            synonyms = [
                str(value).strip()
                for value in candidate.get("synonyms") or []
                if str(value or "").strip()
            ]
            if prefix and name.casefold().startswith(prefix.casefold()):
                suffix = name[len(prefix) :].strip(" ,-–—")
                if suffix and suffix.casefold() != name.casefold():
                    synonyms.append(suffix)
            if index < len(ordinal_synonyms):
                synonyms.extend(ordinal_synonyms[index])
            values.append(
                {
                    "id": str(candidate.get("id") or f"choice-{index + 1}"),
                    "name": {"value": name, "synonyms": synonyms},
                }
            )
        return {
            "type": "Dialog.UpdateDynamicEntities",
            "updateBehavior": "REPLACE",
            "types": [{"name": "HEAR_CLARIFICATION", "values": values}],
        }
